import math
import statistics
from random import Random
from typing import Any

from .config import ControlError, VariableSpec
from .config_validator import ConfigValidator


class DistributionSampler:
    """
    Samples one value for one distribution variable definition.

    Supported distributions:
      - uniform
      - normal
      - choice
      - truncated_normal
    """
    
    def sample(self, var: VariableSpec, rng: Random) -> Any:
        spec = var.data
        dist_val = spec["distribution"]
        dist = str(dist_val).strip().lower()

        if dist == "uniform":
            return self._sample_uniform(var.name, spec, rng)
        if dist in {"normal", "gaussian"}:
            return self._sample_normal(var.name, spec, rng)
        if dist == "choice":
            return self._sample_choice(var.name, spec, rng)
        if dist == "truncated_normal":
            return self._sample_truncated_normal(var.name, spec, rng)

        raise ControlError(f"variable {var.name!r} has unsupported distribution {dist!r}")

    def _sample_uniform(self, name: str, spec: dict[str, Any], rng: Random) -> float:
        low = ConfigValidator._require_number(spec, "min", name)
        high = ConfigValidator._require_number(spec, "max", name)
        return rng.uniform(low, high)
    
    def _sample_truncated_normal(self, name: str, spec: dict[str, Any], rng: Random) -> float:
        mean = ConfigValidator._require_number(spec, "mean", name)
        stddev = ConfigValidator._require_number(spec, "stddev", name)

        low = ConfigValidator._require_number(spec, "min", name)
        high = ConfigValidator._require_number(spec, "max", name)
        if low == high:
            return low

        dist = statistics.NormalDist(mu=mean, sigma=stddev)
        p_low = dist.cdf(low)
        p_high = dist.cdf(high)
        if p_low == p_high:
             raise ControlError(
                 f"{name!r}: bounds [{low}, {high}] are too far in the distribution tail. "
                 f"The acceptance area is indistinguishable from 0% due to float precision."
             )
        u = rng.uniform(p_low, p_high)
        safe_low = math.nextafter(0.0, 1.0)
        safe_high = math.nextafter(1.0, 0.0)
        u = max(safe_low, min(u, safe_high))
        return max(low, min(dist.inv_cdf(u), high))

    def _sample_normal(self, name: str, spec: dict[str, Any], rng: Random) -> float:
        mean = ConfigValidator._require_number(spec, "mean", name)
        stddev = ConfigValidator._require_number(spec, "stddev", name)
        return rng.gauss(mean, stddev)

    def _sample_choice(self, name: str, spec: dict[str, Any], rng: Random) -> Any:
        values = spec.get("values")
        return rng.choice(values)
