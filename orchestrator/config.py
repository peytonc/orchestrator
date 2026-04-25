from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import json
import re
from collections import Counter


VALID_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ControlError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionConfig:
    mode: str
    max_cases: int
    random_seed: int
    max_cpu_threads: int = 999
    prefer_physical_cores: bool = True
    worker_dir_root: str = "tmp"
    preserve_workdirs: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionConfig":
        mode = str(data.get("mode", "")).strip()
        if mode not in {"monte_carlo", "sweep"}:
            raise ControlError(f"execution.mode must be 'monte_carlo' or 'sweep', got {mode!r}")

        max_cases = int(data.get("max_cases", 0))
        if max_cases <= 0:
            raise ControlError("execution.max_cases must be a positive integer")

        random_seed = int(data.get("random_seed", 0))
        max_cpu_threads = int(data.get("max_cpu_threads", 999))
        if max_cpu_threads <= 0:
            raise ControlError("execution.max_cpu_threads must be a positive integer")

        prefer_physical_cores = bool(data.get("prefer_physical_cores", True))
        worker_dir_root = str(data.get("worker_dir_root", "tmp")).strip() or "tmp"
        preserve_workdirs = bool(data.get("preserve_workdirs", True))

        return cls(
            mode=mode,
            max_cases=max_cases,
            random_seed=random_seed,
            max_cpu_threads=max_cpu_threads,
            prefer_physical_cores=prefer_physical_cores,
            worker_dir_root=worker_dir_root,
            preserve_workdirs=preserve_workdirs,
        )


@dataclass(frozen=True)
class PathsConfig:
    template_file: Path
    generated_input_file: Path
    physics_command: str
    physics_output_file: Path
    results_file: Path

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PathsConfig":
        try:
            template_file = Path(data["template_file"])
            generated_input_file = Path(data["generated_input_file"])
            physics_command = str(data["physics_command"]).strip()
            physics_output_file = Path(data["physics_output_file"])
            results_file = Path(data["results_file"])
        except KeyError as exc:
            raise ControlError(f"paths missing required field: {exc.args[0]}") from exc

        if not physics_command:
            raise ControlError("paths.physics_command must not be empty")

        return cls(
            template_file=template_file,
            generated_input_file=generated_input_file,
            physics_command=physics_command,
            physics_output_file=physics_output_file,
            results_file=results_file,
        )


@dataclass(frozen=True)
class VariableSpec:
    name: str
    kind: str  # "sweep" or "distribution"
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VariableSpec":
        try:
            name = str(data["name"]).strip()
            kind = str(data["kind"]).strip()
        except KeyError as exc:
            raise ControlError(f"variable missing required field: {exc.args[0]}") from exc

        if not VALID_NAME_RE.match(name):
            raise ControlError(
                f"invalid variable name {name!r}; must match {VALID_NAME_RE.pattern}"
            )
        if kind not in {"sweep", "distribution"}:
            raise ControlError(f"variable {name!r} has invalid kind {kind!r}")
            
        if kind == "sweep":
            for forbidden in ("group", "iteration"):
                if forbidden in data:
                    raise ControlError(
                        f"variable {name!r}: field {forbidden!r} is not supported; "
                        "define nesting order by variable position in the array instead"
                    )

        clean_data = {k: v for k, v in data.items() if k not in ("name", "kind")}
        return cls(name=name, kind=kind, data=clean_data)

    def is_required_placeholder(self) -> bool:
        return True


@dataclass(frozen=True)
class ParsingRuleSpec:
    name: str
    type: str
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParsingRuleSpec":
        try:
            name = str(data["name"]).strip()
            rule_type = str(data["type"]).strip()
        except KeyError as exc:
            raise ControlError(f"parsing rule missing required field: {exc.args[0]}") from exc

        if rule_type not in {"csv", "regex"}:
            raise ControlError(f"parsing rule {name!r} has invalid type {rule_type!r}")

        return cls(name=name, type=rule_type, data=dict(data))


@dataclass(frozen=True)
class ControlConfig:
    execution: ExecutionConfig
    paths: PathsConfig
    variables: List[VariableSpec]
    parsing: List[ParsingRuleSpec]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ControlConfig":
        if not isinstance(data, dict):
            raise ControlError("control file must decode to a JSON object")

        execution = ExecutionConfig.from_dict(data.get("execution", {}))
        paths = PathsConfig.from_dict(data.get("paths", {}))

        raw_variables = data.get("variables", [])
        if not isinstance(raw_variables, list) or not raw_variables:
            raise ControlError("variables must be a non-empty list")

        variables = [VariableSpec.from_dict(item) for item in raw_variables]
        variable_names = [v.name for v in variables]
        duplicate_variables = sorted(name for name, count in Counter(variable_names).items() if count > 1)
        if duplicate_variables:
            raise ControlError(
                "variables contains duplicate names: " + ", ".join(duplicate_variables)
            )

        raw_parsing = data.get("parsing", [])
        if not isinstance(raw_parsing, list):
            raise ControlError("parsing must be a list")
        parsing = [ParsingRuleSpec.from_dict(item) for item in raw_parsing]
        parsing_names = [r.name for r in parsing]
        duplicate_parsing = sorted(name for name, count in Counter(parsing_names).items() if count > 1)
        if duplicate_parsing:
            raise ControlError(
                "parsing contains duplicate names: " + ", ".join(duplicate_parsing)
            )

        return cls(execution=execution, paths=paths, variables=variables, parsing=parsing)

    @classmethod
    def load_json(cls, path: str | Path) -> "ControlConfig":
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        return cls.from_dict(data)

    @property
    def variable_names(self) -> Set[str]:
        return {v.name for v in self.variables}

    def validate_against_template(self, template_placeholders: Set[str]) -> None:
        defined = self.variable_names
        missing = sorted(template_placeholders - defined)
        if missing:
            raise ControlError(
                "template placeholders missing from control file: " + ", ".join(missing)
            )
        extra = sorted(defined - template_placeholders)
        if extra:
            raise ControlError(
                "control file variables not used in template: " + ", ".join(extra)
            )
