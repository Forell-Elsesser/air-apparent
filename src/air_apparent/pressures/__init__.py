"""Pressure calculations (no GUI, no ETABS). Public entry point: :func:`calculate_pressures`."""

from __future__ import annotations

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
    return module.calculate(cfg, dims)
