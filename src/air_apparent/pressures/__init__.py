"""Pressure calculations (no GUI, no ETABS). Public entry point: :func:`calculate_pressures`."""

from __future__ import annotations

import math

from ..models import Config, PlanDims, PressureSet
from . import asce7_10
from .eccentricity import EccStory, eccentric_torsion, eccentricity_length

__all__ = [
    "SUPPORTED_EDITIONS",
    "EccStory",
    "UnsupportedEditionError",
    "calculate_pressures",
    "eccentric_torsion",
    "eccentricity_length",
]

# Extension point: register a new code edition by adding a module that exposes
# ``calculate(cfg, dims) -> PressureSet`` and listing it here.
SUPPORTED_EDITIONS = {"ASCE 7-10": asce7_10}


class UnsupportedEditionError(ValueError):
    pass


def calculate_pressures(cfg: Config, dims: dict[str, PlanDims] | None = None) -> PressureSet:
    """Calculate all pressures for ``cfg``. ``dims`` maps "X"/"Y" wind axis to L/B used.

    Defaults to the YAML dimensions. Unsupported editions raise instead of falling back.
    """
    module = SUPPORTED_EDITIONS.get(cfg.code_edition)
    if module is None:
        raise UnsupportedEditionError(
            f"code edition {cfg.code_edition!r} is not supported; "
            f"supported: {sorted(SUPPORTED_EDITIONS)}"
        )
    if dims is None:
        dims = {"X": cfg.geometry.x_wind, "Y": cfg.geometry.y_wind}
    for axis in ("X", "Y"):
        if axis not in dims:
            raise ValueError(f"missing plan dimensions for {axis}-wind")
        for name in ("parallel_l", "perpendicular_b"):
            value = getattr(dims[axis], name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{axis}-wind {name} must be finite and greater than zero; "
                                 f"got {value!r} ft. Check the model envelope and input dimensions")
    return module.calculate(cfg, dims)
