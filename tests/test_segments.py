from air_apparent.categorization.segments import penthouse_edges, place, resolve_segments
from air_apparent.models import CategorizationSettings, ExteriorSegment, GridLine, Penthouse

G = [GridLine("G1", "y", "J", 0.0), GridLine("G1", "y", "E", 238.0),
     GridLine("G1", "x", "28.5", 2.25), GridLine("G1", "x", "39", 421.75)]
S = CategorizationSettings()


def test_resolve_labels_and_numbers():
    segs, diags = resolve_segments([ExteriorSegment("J_E", "J", 241.667, "39", "-Y"),
                                    ExteriorSegment("SW_s", -11.0, "28.5", 25.5, "-Y", axis="y"),
                                    ExteriorSegment("J_top", "J", 2.25, 25.5, "-Y", z_from=46.0)], G)
    assert diags == []
    assert (segs[0].axis, segs[0].ordinate_ft, segs[0].start_ft, segs[0].end_ft) == ("y", 0.0, 241.667, 421.75)
    assert (segs[1].axis, segs[1].ordinate_ft, segs[1].start_ft) == ("y", -11.0, 2.25)
    assert (segs[2].z_from, segs[2].z_to) == (46.0, None)


def test_unknown_label_overlap_and_numeric_label():
    segs, diags = resolve_segments([ExteriorSegment("a", "Q", 0, 1, "-Y"),
                                    ExteriorSegment("b", "J", 0, 100, "-Y"), ExteriorSegment("c", "J", 50, 150, "-Y"),
                                    ExteriorSegment("d", 39.0, "J", "E", "+X", axis="x")], G)
    assert sorted(d.code for d in diags) == ["grid_label_unknown", "numeric_along_matches_label",
                                             "segment_overlap", "segment_overlap"]
    assert [s.id for s in segs] == ["d"]


def test_height_ranges_make_same_line_segments_compatible():
    segs, diags = resolve_segments([ExteriorSegment("low", "J", 0, 100, "-Y", z_to=46.0),
                                    ExteriorSegment("high", "J", 0, 100, "-Y", z_from=46.0)], G)
    assert diags == [] and [s.id for s in segs] == ["low", "high"]


def test_penthouse_edges():
    ph = Penthouse("PH1", 266.083, 301.333, 214.25, 238.0, 60.0, 15.0, 70.0, 25.0)
    e = {s.id: s for s in penthouse_edges(ph)}
    n = e["PH1_N"]
    assert (n.axis, n.ordinate_ft, n.outside, n.component) == ("y", 238.0, "+Y", "PH1")
    assert (e["PH1_W"].start_ft, e["PH1_W"].end_ft, e["PH1_W"].outside) == (214.25, 238.0, "-X")


def test_place_plane_tolerance_gap_and_height():
    segs, _ = resolve_segments([ExteriorSegment("J_W", "J", 25.5, 218.417, "-Y"),
                                ExteriorSegment("J_E", "J", 241.667, "39", "-Y"),
                                ExteriorSegment("J_top", "J", 2.25, 25.5, "-Y", z_from=46.0)], G)
    assert place("y", 0.05, 100.0, 112.0, 20.0, segs, S)[1] == "placed"
    assert place("y", 0.3, 100.0, 112.0, 20.0, segs, S)[1] == "none"       # plane tolerance 0.1 ft
    assert place("y", 0.0, 219.0, 230.0, 20.0, segs, S)[1] == "none"       # inside the bump-out gap
    assert place("x", 0.0, 100.0, 112.0, 20.0, segs, S)[1] == "none"       # wrong axis
    seg, status = place("y", 0.0, 10.0, 20.0, 50.0, segs, S)               # behind the bump-out, above 46 ft
    assert status == "placed" and seg.id == "J_top"
    assert place("y", 0.0, 10.0, 20.0, 30.0, segs, S)[1] == "none"         # same spot, below 46 ft


def test_place_largest_overlap_wins_and_ties_are_ambiguous():
    touching, _ = resolve_segments([ExteriorSegment("a", "J", 0.0, 100.0, "-Y"),
                                    ExteriorSegment("b", "J", 100.0, 200.0, "-Y")], G)
    seg, status = place("y", 0.0, 99.0, 101.8, 20.0, touching, S)   # 1.0 ft on a, 1.8 ft on b
    assert status == "placed" and seg.id == "b"
    assert place("y", 0.0, 99.0, 101.0, 20.0, touching, S)[1] == "ambiguous"
    assert place("y", 0.0, 90.0, 105.0, 20.0, touching, S)[0].id == "a"     # 10 ft on a beats 5 ft on b
    assert place("y", 0.0, 95.0, 220.0, 20.0, touching, S)[1] == "placed"   # b covers 100 of 125 ft
    assert place("y", 0.0, 60.0, 270.0, 20.0, touching, S)[1] == "none"     # b covers 100 of 210: under half
