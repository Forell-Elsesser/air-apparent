from pathlib import Path

import pytest

from air_apparent.config import load_config
from air_apparent.demo import build_demo_snapshot
from air_apparent.workflow import WindSession

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "examples" / "reference_sample.yaml"
TEMPLATE = ROOT / "templates" / "wind_inputs.yaml"
TEST_MODEL_SNAPSHOT = ROOT / "tests" / "fixtures" / "test_model_snapshot.json"


@pytest.fixture(scope="session")
def test_model_snap():
    """Snapshot captured from the live seven-story Test Model (python -m air_apparent.capture)."""
    from air_apparent.snapshot_io import snapshot_from_json

    return snapshot_from_json(TEST_MODEL_SNAPSHOT.read_text(encoding="utf-8"))


@pytest.fixture
def cfg():
    return load_config(REFERENCE)


@pytest.fixture
def snap(cfg):
    return build_demo_snapshot(cfg)


@pytest.fixture
def session():
    s = WindSession()
    s.load_config(str(REFERENCE))
    s.use_offline_demo()
    s.read_model()
    s.calculate()
    s.build_plan()
    return s
