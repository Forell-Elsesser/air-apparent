"""Whole-model categorization and preview-group specifications (no GUI, no ETABS)."""

from .groups import (
    PREFIX,
    STAIR_GROUP,
    UNRESOLVED_GROUP,
    detect_group_conflicts,
    face_role,
    reconcile_membership,
)
from .rules import categorize

__all__ = [
    "PREFIX",
    "STAIR_GROUP",
    "UNRESOLVED_GROUP",
    "categorize",
    "detect_group_conflicts",
    "face_role",
    "reconcile_membership",
]
