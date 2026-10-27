"""Whole-model categorization and preview-group specifications (no GUI, no ETABS)."""

from .groups import (
    build_group_specs,
    build_pattern_groups,
    compare_groups,
    detect_group_conflicts,
    face_role,
)
from .rules import categorize, categorize_frames, categorize_shells

__all__ = [
    "build_group_specs",
    "build_pattern_groups",
    "categorize",
    "categorize_frames",
    "categorize_shells",
    "compare_groups",
    "detect_group_conflicts",
    "face_role",
]
