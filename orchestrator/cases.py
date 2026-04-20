from __future__ import annotations

from decimal import Decimal
from itertools import product
from random import Random
from typing import Any, Dict, Iterator, List, Sequence

from .config import ControlConfig, ControlError, VariableSpec
from .sampling import DistributionSampler


class CaseGenerator:
    """
    Generates normalized case dictionaries for either:
      - Monte Carlo sampling
      - deterministic sweeps

    Each yielded case looks like:
      {
          "case_id": 1,
          "seed": 123456789,
          "mode": "monte_carlo" | "sweep",
          "values": { "TEMPERATURE": 300.0, ... }
      }

    Note:
      OUTPUT_FILENAME is typically injected later by the worker layer because it
      depends on the per-thread local directory and case id.
    """

    def __init__(self, config: ControlConfig):
        self.config = config
        self._master_rng = Random(config.execution.random_seed)
        self._sampler = DistributionSampler()

    def iter_cases(self) -> Iterator[Dict[str, Any]]:
        mode = self.config.execution.mode
        if mode == "monte_carlo":
            yield from self._iter_monte_carlo_cases()
            return
        if mode == "sweep":
            yield from self._iter_sweep_cases()
            return
        raise ControlError(f"unsupported execution mode: {mode!r}")

    def generate_cases(self) -> List[Dict[str, Any]]:
        return list(self.iter_cases())

    def _iter_monte_carlo_cases(self) -> Iterator[Dict[str, Any]]:
        dist_vars = [v for v in self.config.variables if v.kind == "distribution"]
        if not dist_vars:
            raise ControlError("monte_carlo mode requires at least one distribution variable")

        for case_id in range(1, self.config.execution.max_cases + 1):
            case_seed = self._master_rng.randrange(1 << 63)
            rng = Random(case_seed)

            values: Dict[str, Any] = {}
            for var in dist_vars:
                values[var.name] = self._sampler.sample(var, rng)

            yield {
                "case_id": case_id,
                "seed": case_seed,
                "mode": "monte_carlo",
                "values": values,
            }

    def _iter_sweep_cases(self) -> Iterator[Dict[str, Any]]:
        sweep_vars = [v for v in self.config.variables if v.kind == "sweep"]
        if not sweep_vars:
            raise ControlError("sweep mode requires at least one sweep variable")

        # Build groups. Variables with the same non-empty group are paired/aligned.
        # Variables with no group each become their own independent group.
        grouped: Dict[str, List[VariableSpec]] = {}
        auto_index = 0
        for var in sweep_vars:
            group_name = str(var.data.get("group", "")).strip()

            if group_name:
                grouped.setdefault(group_name, []).append(var)
                continue

            # No explicit group means this variable is independent.
            auto_key = f"__auto_{auto_index}_{var.name}"
            auto_index += 1
            grouped[auto_key] = [var]

        group_case_blocks: List[List[Dict[str, Any]]] = []
        for group_name, vars_in_group in grouped.items():
            group_block = self._expand_group(group_name, vars_in_group)
            group_case_blocks.append(group_block)

        case_id = 1
        for combo in product(*group_case_blocks):
            merged: Dict[str, Any] = {}
            for part in combo:
                merged.update(part)

            if case_id > self.config.execution.max_cases:
                break

            case_seed = self._master_rng.randrange(1 << 63)
            yield {
                "case_id": case_id,
                "seed": case_seed,
                "mode": "sweep",
                "values": merged,
            }
            case_id += 1

    def _expand_group(self, group_name: str, vars_in_group: Sequence[VariableSpec]) -> List[Dict[str, Any]]:
        if len(vars_in_group) == 1:
            var = vars_in_group[0]
            values = self._sweep_values(var)
            return [{var.name: value} for value in values]

        # Paired / aligned iteration across multiple variables.
        lengths = []
        expanded: List[List[Any]] = []
        for var in vars_in_group:
            values = self._sweep_values(var)
            expanded.append(values)
            lengths.append(len(values))

        if len(set(lengths)) != 1:
            names = ", ".join(v.name for v in vars_in_group)
            raise ControlError(
                f"sweep group {group_name!r} has mismatched value counts for variables: {names}"
            )

        paired_cases: List[Dict[str, Any]] = []
        for idx in range(lengths[0]):
            entry: Dict[str, Any] = {}
            for var, values in zip(vars_in_group, expanded):
                entry[var.name] = values[idx]
            paired_cases.append(entry)
        return paired_cases

    def _sweep_values(self, var: VariableSpec) -> List[Any]:
        spec = var.data

        if "values" in spec:
            values = spec["values"]
            if not isinstance(values, list) or not values:
                raise ControlError(f"{var.name!r}: sweep values must be a non-empty list")
            return list(values)

        # Range form: min / max / step
        if not all(k in spec for k in ("min", "max", "step")):
            raise ControlError(
                f"{var.name!r}: sweep variable must define either 'values' or 'min'/'max'/'step'"
            )

        start = Decimal(str(spec["min"]))
        stop = Decimal(str(spec["max"]))
        step = Decimal(str(spec["step"]))

        if step <= 0:
            raise ControlError(f"{var.name!r}: step must be > 0")
        if stop < start:
            raise ControlError(f"{var.name!r}: max must be >= min")

        values: List[Any] = []
        current = start
        max_iters = int(spec.get("max_iters", 1000000))
        if max_iters <= 0:
            raise ControlError(f"{var.name!r}: max_iters must be positive")

        for _ in range(max_iters):
            if current > stop:
                break
            values.append(self._decimal_to_python(current))
            current += step
        else:
            raise ControlError(f"{var.name!r}: exceeded max_iters while building sweep values")

        if not values:
            raise ControlError(f"{var.name!r}: sweep range produced no values")

        return values

    @staticmethod
    def _decimal_to_python(value: Decimal) -> Any:
        if value == value.to_integral_value():
            return int(value)
        return float(value)
