from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

from .config import ControlConfig, ControlError, VariableSpec


class ConfigValidator:
    """
    Centralized configuration validation for ControlConfig.

    This class intentionally consolidates validation logic that historically
    lived in multiple runtime components (case generation, sampling, parsing).
    It does not change execution behavior by itself unless explicitly invoked
    by the caller.
    """

    SUPPORTED_DISTRIBUTIONS = {"uniform", "normal", "gaussian", "choice", "truncated_normal"}
    SUPPORTED_PARSING_TYPES = {"csv", "regex"}
    SUPPORTED_VALUE_TYPES = {"text", "str", "", "int", "integer", "float", "number", "double", "bool", "boolean"}

    def validate_control_config(self, config: ControlConfig) -> None:
        self._validate_mode_variable_compatibility(config)
        self._validate_variables(config)
        self._validate_parsing_rules(config)

    def _validate_mode_variable_compatibility(self, config: ControlConfig) -> None:
        mode = config.execution.mode
        invalid_kinds_by_mode = {
            "monte_carlo": "sweep",
            "sweep": "distribution",
        }
        invalid_kind = invalid_kinds_by_mode.get(mode)
        if not invalid_kind:
            return

        invalid_names = sorted(v.name for v in config.variables if v.kind == invalid_kind)
        if invalid_names:
            raise ControlError(
                f"{mode} mode does not support {invalid_kind} variables: "
                + ", ".join(invalid_names)
            )
        if mode == "monte_carlo" and not any(v.kind == "distribution" for v in config.variables):
            raise ControlError("monte_carlo mode requires at least one distribution variable")
        if mode == "sweep" and not any(v.kind == "sweep" for v in config.variables):
            raise ControlError("sweep mode requires at least one sweep variable")

    def _validate_variables(self, config: ControlConfig) -> None:
        for var in config.variables:
            if var.kind == "distribution":
                self._validate_distribution_variable(var)
            elif var.kind == "sweep":
                self._validate_sweep_variable(var)

    def _validate_distribution_variable(self, var: VariableSpec) -> None:
        spec = var.data
        if not isinstance(spec, dict):
            raise ControlError(f"variable {var.name!r} data must be a dictionary configuration")
        if "distribution" not in spec:
            raise ControlError(f"distribution variable {var.name!r} is missing 'distribution'")

        dist = str(spec["distribution"]).strip().lower()
        if dist not in self.SUPPORTED_DISTRIBUTIONS:
            raise ControlError(f"variable {var.name!r} has unsupported distribution {dist!r}")

        if dist == "uniform":
            low = self._require_number(spec, "min", var.name)
            high = self._require_number(spec, "max", var.name)
            if high < low:
                raise ControlError(f"{var.name!r}: max must be >= min")
        elif dist in {"normal", "gaussian"}:
            stddev = self._require_number(spec, "stddev", var.name)
            self._require_number(spec, "mean", var.name)
            if stddev <= 0:
                raise ControlError(f"{var.name!r}: stddev must be > 0")
        elif dist == "choice":
            values = spec.get("values")
            if not isinstance(values, list) or not values:
                raise ControlError(
                    f"{var.name!r}: choice distribution requires a non-empty sequence of values"
                )
        elif dist == "truncated_normal":
            self._require_number(spec, "mean", var.name)
            stddev = self._require_number(spec, "stddev", var.name)
            if stddev <= 0:
                raise ControlError(f"{var.name!r}: stddev must be > 0")
            low = self._require_number(spec, "min", var.name)
            high = self._require_number(spec, "max", var.name)
            if high < low:
                raise ControlError(f"{var.name!r}: max must be >= min")

    def _validate_sweep_variable(self, var: VariableSpec) -> None:
        spec = var.data
        if not isinstance(spec, dict):
            raise ControlError(f"variable {var.name!r} data must be a dictionary configuration")

        if "values" in spec:
            values = spec["values"]
            if not isinstance(values, list) or not values:
                raise ControlError(f"{var.name!r}: sweep values must be a non-empty list")
            return

        if not all(k in spec for k in ("min", "max", "step")):
            raise ControlError(
                f"{var.name!r}: sweep variable must define either 'values' or 'min'/'max'/'step'"
            )

        if all(self._is_integral_number(spec[k]) for k in ("min", "max", "step")):
            start_int = int(float(spec["min"]))
            stop_int = int(float(spec["max"]))
            step_int = int(float(spec["step"]))
            if step_int <= 0:
                raise ControlError(f"{var.name!r}: step must be > 0")
            if stop_int < start_int:
                raise ControlError(f"{var.name!r}: max must be >= min")
            return

        start = Decimal(str(spec["min"]))
        stop = Decimal(str(spec["max"]))
        step = Decimal(str(spec["step"]))

        if step <= 0:
            raise ControlError(f"{var.name!r}: step must be > 0")
        if stop < start:
            raise ControlError(f"{var.name!r}: max must be >= min")

        max_iters = int(spec.get("max_iters", 1000000))
        if max_iters <= 0:
            raise ControlError(f"{var.name!r}: max_iters must be positive")

        delta = stop - start
        axis_length = int((delta // step) + 1)
        if axis_length <= 0:
            raise ControlError(f"{var.name!r}: sweep range produced no values")
        if axis_length > max_iters:
            raise ControlError(f"{var.name!r}: exceeded max_iters while building sweep values")

    def _validate_parsing_rules(self, config: ControlConfig) -> None:
        for rule in config.parsing:
            if rule.type not in self.SUPPORTED_PARSING_TYPES:
                raise ControlError(f"parsing rule {rule.name!r} has invalid type {rule.type!r}")

            if rule.type == "csv":
                self._validate_csv_rule(rule.data)
            elif rule.type == "regex":
                self._validate_regex_rule(rule.data)

    def _validate_csv_rule(self, spec: dict[str, Any]) -> None:
        target_file = str(spec.get("target_file", "")).strip()
        if "target_file" in spec and not target_file:
            raise ControlError("csv parsing rule target_file cannot be empty when provided")

        required_columns = spec.get("columns", {})
        if not isinstance(required_columns, dict) or not required_columns:
            raise ControlError("csv parsing rule requires a non-empty 'columns' mapping")

        for _, column_spec in required_columns.items():
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
            if converter not in self.SUPPORTED_VALUE_TYPES:
                raise ControlError(f"unsupported conversion type: {converter!r}")

    def _validate_regex_rule(self, spec: dict[str, Any]) -> None:
        target_file = str(spec.get("target_file", "")).strip()
        if "target_file" in spec and not target_file:
            raise ControlError("regex parsing rule target_file cannot be empty when provided")

        start_pattern = str(spec.get("start_pattern", "")).strip()
        if not start_pattern:
            raise ControlError("regex parsing rule requires 'start_pattern'")
        if "required" in spec and not isinstance(spec["required"], bool):
            raise ControlError("regex parsing rule 'required' flag must be a boolean when provided")
        try:
            re.compile(start_pattern)
        except re.error as exc:
            raise ControlError(f"invalid regex start_pattern: {start_pattern!r}") from exc

        try:
            context_before = int(spec.get("context_before", 0))
            context_after = int(spec.get("context_after", 5))
        except (ValueError, TypeError) as exc:
            raise ControlError("context_before/context_after must be integers") from exc
        if context_before < 0 or context_after < 0:
            raise ControlError("context_before/context_after must be non-negative")

        capture_map = spec.get("captures", {})
        if not isinstance(capture_map, dict) or not capture_map:
            raise ControlError("regex parsing rule requires a non-empty 'captures' mapping")

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
                re.compile(pattern)
            except re.error as exc:
                raise ControlError(f"invalid capture regex for {field_name!r}: {pattern!r}") from exc
            if converter not in self.SUPPORTED_VALUE_TYPES:
                raise ControlError(f"unsupported conversion type: {converter!r}")
            if isinstance(capture_spec, dict) and "required" in capture_spec and not isinstance(
                capture_spec["required"], bool
            ):
                raise ControlError(
                    f"regex capture {field_name!r} has invalid required flag; expected bool"
                )

    @staticmethod
    def _require_number(spec: dict[str, Any], key: str, name: str) -> float:
        if key not in spec:
            raise ControlError(f"{name!r}: missing required field {key!r}")
        try:
            val = float(spec[key])
            if not math.isfinite(val):
                raise ControlError(f"{name!r}: field {key!r} must be a finite number")
            return val
        except (TypeError, ValueError) as exc:
            raise ControlError(f"{name!r}: field {key!r} must be numeric") from exc

    @staticmethod
    def _is_integral_number(value: Any) -> bool:
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        if isinstance(value, float):
            return math.isfinite(value) and value.is_integer()
        if isinstance(value, str):
            try:
                num = float(value)
                return math.isfinite(num) and num.is_integer()
            except (ValueError, OverflowError):
                return False
        return False
