from __future__ import annotations

import math
from decimal import Decimal
from random import Random
from typing import Any, Callable, Dict, Iterator, Tuple

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

    def iter_cases(self) -> Iterator[Dict[str, Any]]:
        mode = self.config.execution.mode
        if mode == "monte_carlo":
            yield from self._iter_monte_carlo_cases()
        elif mode == "sweep":
            yield from self._iter_sweep_cases()
        else:
            raise ControlError(f"unsupported execution mode: {mode!r}")

    def _iter_monte_carlo_cases(self) -> Iterator[Dict[str, Any]]:
        dist_vars = [v for v in self.config.variables if v.kind == "distribution"]

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

        compiled_axes = [self._compile_axis(var) for var in sweep_vars]
        lengths = [length for length, _ in compiled_axes]
        getters = [getter for _, getter in compiled_axes]
        names = [var.name for var in sweep_vars]

        total_combinations = 1
        for length in lengths:
            total_combinations *= length

        max_cases = min(self.config.execution.max_cases, total_combinations)

        for case_id in range(1, max_cases + 1):
            linear_index = case_id - 1
            current_values: Dict[str, Any] = {}

            for i in range(len(lengths) - 1, -1, -1):
                linear_index, axis_index = divmod(linear_index, lengths[i])
                current_values[names[i]] = getters[i](axis_index)

            yield {
                "case_id": case_id,
                "seed": None,
                "mode": "sweep",
                "values": current_values,
            }

    def _compile_axis(self, var: VariableSpec) -> Tuple[int, Callable[[int], Any]]:
        spec = var.data

        if "values" in spec:
            values = spec["values"]
            return len(values), values.__getitem__

        if all(self._is_integral_number(spec[k]) for k in ("min", "max", "step")):
            start_int = int(float(spec["min"]))
            stop_int = int(float(spec["max"]))
            step_int = int(float(spec["step"]))

            axis_length = ((stop_int - start_int) // step_int) + 1
            return axis_length, lambda idx: start_int + (idx * step_int)

        start = Decimal(str(spec["min"]))
        stop = Decimal(str(spec["max"]))
        step = Decimal(str(spec["step"]))

        max_iters = int(spec.get("max_iters", 1000000))

        delta = stop - start
        axis_length = int((delta // step) + 1)
        if axis_length > max_iters:
            raise ControlError(f"{var.name!r}: exceeded max_iters while building sweep values")

        return axis_length, lambda idx: self._decimal_to_python(start + (Decimal(idx) * step))

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
            except (ValueError, OverflowError):
                return False
        return False
