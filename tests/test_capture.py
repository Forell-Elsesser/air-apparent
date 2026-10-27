from air_apparent.capture import summarize


def test_summary_lists_stories_grids_counts_and_groups(snap):
    snap.groups["W_Wall_+X"] = ["A:W_S_L2_1", "A:W_S_L2_2"]
    text = summarize(snap)
    assert "base elevation" in text
    assert "L2" in text and "ROOF" in text
    assert "W_Wall_+X" in text and " 2" in text
    assert "shells" in text and "frames" in text and "joints" in text
