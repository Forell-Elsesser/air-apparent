from pathlib import Path

import pytest

from air_apparent.config import load_config
from air_apparent.demo import build_demo_snapshot
from air_apparent.workflow import WindSession

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "examples" / "reference_sample.yaml"
TEMPLATE = ROOT / "templates" / "wind_inputs.yaml"


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
