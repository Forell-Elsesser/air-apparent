"""Validation for combination references and definitions."""

from __future__ import annotations

import math
from collections.abc import Iterable

from ..models import CombinationSpec


def validate_combinations(combinations: Iterable[CombinationSpec], case_names: set[str]) -> None:
    """Raise ``ValueError`` if names, kinds, factors, or references are inconsistent."""
    items = list(combinations)
    names = [item.name for item in items]
    if len(names) != len(set(names)):
        raise ValueError("combination names must be unique")

    linear_names = {item.name for item in items if item.kind == "linear"}
    envelope_names = {item.name for item in items if item.kind == "envelope"}
    unknown_kinds = {item.kind for item in items} - {"linear", "envelope"}
    if unknown_kinds:
        raise ValueError(f"unsupported combination kind(s): {sorted(unknown_kinds)}")

    for item in items:
        if not item.terms:
            raise ValueError(f"combination {item.name!r} has no terms")
        for reference, factor in item.terms:
            if not math.isfinite(factor):
                raise ValueError(f"combination {item.name!r} has a non-finite factor")
            if item.kind == "linear" and reference not in case_names:
                raise ValueError(f"linear combination {item.name!r} references unknown case {reference!r}")
            if item.kind == "envelope" and reference not in linear_names:
                raise ValueError(f"envelope {item.name!r} references unknown linear combination {reference!r}")
        if item.kind == "envelope" and any(factor != 1.0 for _, factor in item.terms):
            raise ValueError(f"envelope {item.name!r} must use a factor of 1.0 for each member")

    if linear_names & envelope_names:
        raise ValueError("a combination name cannot be both linear and envelope")
