import math

from air_apparent.combinations import build_combinations


def test_counts_and_factors():
    combos = build_combinations()
    lin = [c for c in combos if c.kind == "linear"]
    by = {f: [c for c in lin if c.family == f] for f in ("W1", "W2", "W3", "W4")}
    assert [len(by[f]) for f in ("W1", "W2", "W3", "W4")] == [4, 8, 4, 16]
    env = {c.family: c for c in combos if c.kind == "envelope"}
    assert [len(env[f].terms) for f in ("W1", "W2", "W3", "W4")] == [4, 8, 4, 16]
    w4 = next(c for c in lin if c.name == "W4_+X_-Y_+EX_-EY")
    d = dict(w4.terms)
    assert d["W_Wall_+X"] == 0.5625 and d["W_Mech_-Y"] == 0.5625
    assert d["W_Ecc_+X"] == 0.5625 and d["W_Ecc_-Y"] == -0.5625
    w2 = next(c for c in lin if c.name == "W2_-X_-E")
    assert dict(w2.terms)["W_Ecc_-X"] == -0.75 and dict(w2.terms)["W_PH_-X"] == 0.75
    assert math.isclose(0.75 * 0.75, 0.5625)
    assert all(c.status == "provisional" for c in combos)


def test_all_terms_reference_defined_cases(cfg):
    from air_apparent.patterns import case_specs
    names = {c.name for c in case_specs()}
    for c in build_combinations():
        if c.kind == "linear":
            assert {t for t, _ in c.terms} <= names
