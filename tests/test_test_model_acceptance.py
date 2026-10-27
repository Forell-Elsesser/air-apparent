"""The engineers' W_* groups in the Test Model are the expected answer (spec section 9)."""

from air_apparent.categorization import categorize
from air_apparent.config import load_config
from air_apparent.models import DIRECTIONS
from tests.conftest import ROOT

EXPECTED = {**{f"W_Parapet_{d}": 695 for d in DIRECTIONS},
            "W_PH_+X": 18, "W_PH_-X": 22, "W_PH_+Y": 22, "W_PH_-Y": 22,
            **{f"W_Wall_{d}": 569 for d in DIRECTIONS},
            "W_Mech_+X": 135, "W_Mech_-X": 135, "W_Mech_+Y": 93, "W_Mech_-Y": 93}
SLIVER_LABELS = {"W2048", "W2046", "W2032", "W2029", "W2027"}


def _categorized(test_model_snap):
    cfg = load_config(ROOT / "examples" / "test_model.yaml")
    return categorize(cfg, test_model_snap)


def test_rules_reproduce_engineer_groups(test_model_snap):
    c = _categorized(test_model_snap)
    errors = [d.message for d in c.diagnostics if d.level == "error"]
    assert not errors, errors
    assert {k: len(v) for k, v in c.pattern_groups.items()} == EXPECTED
    for row in c.comparison:
        assert row.missing_from_rules == (), (row.name, row.missing_from_rules)
        extra = {test_model_snap.labels[r][0] for r in row.extra_in_rules}
        if row.name.startswith("W_Wall"):
            # the 6 in sliver column at the west end of J, which the model loads inconsistently
            assert extra <= SLIVER_LABELS and len(row.extra_in_rules) == (4 if row.name == "W_Wall_+Y" else 1), row
        else:
            assert row.extra_in_rules == (), row


def test_no_shell_silently_dropped(test_model_snap):
    c = _categorized(test_model_snap)
    unresolved = [o for o in c.objects.values() if o.category == "unresolved"]
    loaded = set().union(*test_model_snap.groups.values())
    assert not [o.ref for o in unresolved if o.ref in loaded]
    assert all(any(d.object_ref == o.ref for d in c.diagnostics) for o in unresolved)
    cut = [o for o in c.objects.values() if o.category == "excluded" and o.segment_id == "W_cut"]
    assert len(cut) == 16
    assert not [d for d in c.diagnostics if d.code == "ambiguous_segment"]
