from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import csv
import re

from .config import ControlError


class OutputParser:
    """
    Parses the Physics output file using declarative rules.

    Supported rule types:
      - csv
      - regex
    """

    def parse(self, output_path: str | Path, parsing_rules: List[Any]) -> Dict[str, Any]:
        default_output_path = Path(output_path)

        parsed: Dict[str, Any] = {}
        for rule in parsing_rules:
            rule_output_path = self._resolve_rule_output_path(default_output_path, rule.data)
            if not rule_output_path.exists():
                raise ControlError(f"output file not found: {rule_output_path}")

            if rule.type == "csv":
                parsed[rule.name] = self._parse_csv(rule_output_path, rule.data)
            elif rule.type == "regex":
                text = rule_output_path.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
                parsed[rule.name] = self._parse_regex(lines, rule.data)
            else:
                raise ControlError(f"unsupported parsing rule type: {rule.type!r}")

        return parsed

    @staticmethod
    def _resolve_rule_output_path(default_output_path: Path, spec: Dict[str, Any]) -> Path:
        target = spec.get("target_file", "")
        if target:
            return Path(str(target).strip())
        return default_output_path

    def _parse_csv(self, output_path: Path, spec: Dict[str, Any]) -> Dict[str, Any]:
        required_columns = spec.get("columns", {})
        if not isinstance(required_columns, dict) or not required_columns:
            raise ControlError("csv parsing rule requires a non-empty 'columns' mapping")

        result_row: Dict[str, Any] = {}
        with output_path.open("r", encoding="utf-8", newline="") as f:
            try:
                reader = csv.DictReader(f)
                first_row = next(reader, None)
            except csv.Error as exc:
                raise ControlError(f"malformed CSV in {output_path}") from exc

            if first_row is None:
                raise ControlError(f"CSV file is empty: {output_path}")

            for target_name, column_spec in required_columns.items():
                if isinstance(column_spec, str):
                    source_column = column_spec
                    converter = "text"
                elif isinstance(column_spec, dict):
                    source_column = str(column_spec.get("column", "")).strip()
                    converter = str(column_spec.get("type", "text")).strip().lower()
                else:
                    raise ControlError("csv column mapping must be a string or object")

                if not source_column:
                    raise ControlError("csv column mapping missing source column name")

                if source_column not in first_row:
                    raise ControlError(f"CSV column not found: {source_column!r}")

                result_row[target_name] = self._convert_value(first_row[source_column], converter)

        return result_row

    def _parse_regex(self, lines: List[str], spec: Dict[str, Any]) -> Dict[str, Any]:
        start_pattern = str(spec.get("start_pattern", "")).strip()
        if not start_pattern:
            raise ControlError("regex parsing rule requires 'start_pattern'")

        required = bool(spec.get("required", True))
        context_before = int(spec.get("context_before", 0))
        context_after = int(spec.get("context_after", 5))

        try:
            start_re = re.compile(start_pattern)
        except re.error as exc:
            raise ControlError(f"invalid regex start_pattern: {start_pattern!r}") from exc

        capture_map = spec.get("captures", {})
        if not isinstance(capture_map, dict) or not capture_map:
            raise ControlError("regex parsing rule requires a non-empty 'captures' mapping")

        match_index: Optional[int] = None
        for idx, line in enumerate(lines):
            if start_re.search(line):
                match_index = idx
                break

        if match_index is None:
            if required:
                raise ControlError(f"regex start pattern not found: {start_pattern!r}")
            return {}

        start = max(0, match_index - context_before)
        end = min(len(lines), match_index + context_after + 1)
        window = lines[start:end]

        parsed: Dict[str, Any] = {}
        for field_name, capture_spec in capture_map.items():
            if isinstance(capture_spec, str):
                pattern = capture_spec
                converter = "text"
            elif isinstance(capture_spec, dict):
                pattern = str(capture_spec.get("pattern", "")).strip()
                converter = str(capture_spec.get("type", "text")).strip().lower()
            else:
                raise ControlError("regex capture mapping must be a string or object")

            if not pattern:
                raise ControlError(f"regex capture for {field_name!r} is missing 'pattern'")

            try:
                capture_re = re.compile(pattern)
            except re.error as exc:
                raise ControlError(f"invalid capture regex for {field_name!r}: {pattern!r}") from exc

            value = None
            for line in window:
                m = capture_re.search(line)
                if m:
                    if m.groups():
                        value = m.group(1)
                    else:
                        value = m.group(0)
                    break

            if value is None:
                if bool(capture_spec.get("required", True)) if isinstance(capture_spec, dict) else required:
                    raise ControlError(f"required regex value not found for field {field_name!r}")
                parsed[field_name] = None
            else:
                parsed[field_name] = self._convert_value(value, converter)

        return parsed

    @staticmethod
    def _convert_value(raw: Any, kind: str) -> Any:
        if raw is None:
            return None

        text = str(raw).strip()
        if kind in {"text", "str", ""}:
            return text
        if kind in {"int", "integer"}:
            try:
                return int(text)
            except ValueError:
                f = float(text)
                if f != int(f):
                    raise ControlError(f"cannot losslessly convert {text!r} to int")
                return int(f)
        if kind in {"float", "number", "double"}:
            try:
                return float(text)
            except ValueError:
                raise ControlError(f"cannot convert {text!r} to float")
        if kind in {"bool", "boolean"}:
            lowered = text.lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
            raise ControlError(f"cannot convert {text!r} to bool")

        raise ControlError(f"unsupported conversion type: {kind!r}")
