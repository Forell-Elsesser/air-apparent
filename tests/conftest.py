from pathlib import Path

import pytest

from air_apparent.config import parse_config
from air_apparent.demo import build_demo_snapshot
from air_apparent.workflow import WindSession

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "examples" / "reference_sample.yaml"
TEMPLATE = ROOT / "templates" / "wind_inputs.yaml"


@pytest.fixture
def cfg():
    # Exercise all load families in the benchmark suite, independent of the GUI's chosen scope.
    return parse_config(REFERENCE.read_text().replace("scope: walls_parapets", "scope: all"),
                        source_path=str(REFERENCE))


@pytest.fixture
def snap(cfg):
    return build_demo_snapshot(cfg)


@pytest.fixture
def session():
    s = WindSession()
    s.load_config(str(REFERENCE))
    s.set_loading_scope("all")
    s.use_offline_demo()
    s.read_model()
    s.calculate()
    s.build_plan()
    return s
