from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import product
from pathlib import Path
from random import Random
from typing import Any, Dict, Iterable, Iterator, List, Sequence, Tuple


class DistributionSampler:
    """
    Samples one value for one distribution variable definition.

    Supported distributions:
      - uniform
      - normal
      - choice
      - truncated_normal
    """

    def __init__(self) -> None:
        pass

    def sample(self, var: VariableSpec, rng: Random) -> Any:
        if var.kind != "distribution":
            raise ControlError(f"variable {var.name!r} is not a distribution variable")

        spec = var.data
        dist = str(spec.get("distribution", "")).strip().lower()
        if not dist:
            raise ControlError(f"distribution variable {var.name!r} is missing 'distribution'")

        if dist == "uniform":
            return self._sample_uniform(var.name, spec, rng)
        if dist in {"normal", "gaussian"}:
            return self._sample_normal(var.name, spec, rng)
        if dist == "choice":
            return self._sample_choice(var.name, spec, rng)
        if dist == "truncated_normal":
            return self._sample_truncated_normal(var.name, spec, rng)

        raise ControlError(f"variable {var.name!r} has unsupported distribution {dist!r}")

    def _sample_uniform(self, name: str, spec: Dict[str, Any], rng: Random) -> float:
        low = self._require_number(spec, "min", name)
        high = self._require_number(spec, "max", name)
        if high < low:
            raise ControlError(f"{name!r}: max must be >= min")
        return rng.uniform(low, high)

    def _sample_normal(self, name: str, spec: Dict[str, Any], rng: Random) -> float:
        mean = self._require_number(spec, "mean", name)
        stddev = self._require_number(spec, "stddev", name)
        if stddev <= 0:
            raise ControlError(f"{name!r}: stddev must be > 0")
        return rng.gauss(mean, stddev)

    def _sample_choice(self, name: str, spec: Dict[str, Any], rng: Random) -> Any:
        values = spec.get("values")
        if not isinstance(values, list) or not values:
            raise ControlError(f"{name!r}: choice distribution requires a non-empty 'values' list")
        return rng.choice(values)

    def _sample_truncated_normal(self, name: str, spec: Dict[str, Any], rng: Random) -> float:
        mean = self._require_number(spec, "mean", name)
        stddev = self._require_number(spec, "stddev", name)
        if stddev <= 0:
            raise ControlError(f"{name!r}: stddev must be > 0")

        low = self._require_number(spec, "min", name)
        high = self._require_number(spec, "max", name)
        if high < low:
            raise ControlError(f"{name!r}: max must be >= min")

        max_tries = int(spec.get("max_tries", 10000))
        if max_tries <= 0:
            raise ControlError(f"{name!r}: max_tries must be positive")

        for _ in range(max_tries):
            value = rng.gauss(mean, stddev)
            if low <= value <= high:
                return value

        raise ControlError(
            f"{name!r}: failed to sample truncated normal inside bounds after {max_tries} tries"
        )

    @staticmethod
    def _require_number(spec: Dict[str, Any], key: str, name: str) -> float:
        if key not in spec:
            raise ControlError(f"{name!r}: missing required field {key!r}")
        try:
            return float(spec[key])
        except (TypeError, ValueError) as exc:
            raise ControlError(f"{name!r}: field {key!r} must be numeric") from exc
