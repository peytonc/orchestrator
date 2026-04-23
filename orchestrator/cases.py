from __future__ import annotations

from decimal import Decimal
from itertools import product
import math
from random import Random
from typing import Any, Dict, Iterator, List

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
    """

    def __init__(self, config: ControlConfig):
        self.config = config
        self._master_rng = Random(config.execution.random_seed)
        self._sampler = DistributionSampler()
        self._validate_mode_variable_compatibility()

    def _validate_mode_variable_compatibility(self) -> None:
        mode = self.config.execution.mode
        invalid_kinds_by_mode = {
            "monte_carlo": "sweep",
            "sweep": "distribution",
        }
        invalid_kind = invalid_kinds_by_mode.get(mode)
        if not invalid_kind:
            return

        invalid_names = sorted(v.name for v in self.config.variables if v.kind == invalid_kind)
        if invalid_names:
            raise ControlError(
                f"{mode} mode does not support {invalid_kind} variables: "
                + ", ".join(invalid_names)
            )

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

        if len(sweep_vars) == 1:
            yield from self._iter_single_sweep(sweep_vars[0])
        else:
            yield from self._iter_nested_sweep(sweep_vars)

    def _iter_single_sweep(self, var: VariableSpec) -> Iterator[Dict[str, Any]]:
        """Iterates through every value of one sweep variable."""
        case_id = 1
        for value in self._sweep_values(var):
            if case_id > self.config.execution.max_cases:
                break
            case_seed = self._master_rng.randrange(1 << 63)
            yield {
                "case_id": case_id,
                "seed": case_seed,
                "mode": "sweep",
                "values": {var.name: value},
            }
            case_id += 1

    def _iter_nested_sweep(self, sweep_vars: List[VariableSpec]) -> Iterator[Dict[str, Any]]:
        """
        Nested for-loop iteration (Cartesian product).
        The first variable in the array is the outermost loop;
        the last variable is the innermost loop.
        """
        all_values = [self._sweep_values(var) for var in sweep_vars]
        case_id = 1
        for combo in product(*all_values):
            if case_id > self.config.execution.max_cases:
                break
            case_seed = self._master_rng.randrange(1 << 63)
            yield {
                "case_id": case_id,
                "seed": case_seed,
                "mode": "sweep",
                "values": {var.name: val for var, val in zip(sweep_vars, combo)},
            }
            case_id += 1

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

        if all(self._is_integral_number(spec[k]) for k in ("min", "max", "step")):
            start_int = int(float(spec["min"]))
            stop_int = int(float(spec["max"]))
            step_int = int(float(spec["step"]))
            if step_int <= 0:
                raise ControlError(f"{var.name!r}: step must be > 0")
            if stop_int < start_int:
                raise ControlError(f"{var.name!r}: max must be >= min")
            return list(range(start_int, stop_int + 1, step_int))

        start = Decimal(str(spec["min"]))
        stop = Decimal(str(spec["max"]))
        step = Decimal(str(spec["step"]))

        if step <= 0:
            raise ControlError(f"{var.name!r}: step must be > 0")
        if stop < start:
            raise ControlError(f"{var.name!r}: max must be >= min")

        values: List[Any] = []
        max_iters = int(spec.get("max_iters", 1000000))
        if max_iters <= 0:
            raise ControlError(f"{var.name!r}: max_iters must be positive")

        for i in range(max_iters):
            current = start + (Decimal(i) * step)
            if current > stop:
                break
            values.append(self._decimal_to_python(current))
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
            except ValueError:
                return False
        return False
