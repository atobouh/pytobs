import sys
from pathlib import Path

from pytobs import packages
from pytobs.env import Interpreter


def test_parse_packages() -> None:
    good, bad = packages.parse_packages("requests, rich==13.7  uvicorn[standard] pandas>=2 --index-url")
    assert good == ["requests", "rich==13.7", "uvicorn[standard]", "pandas>=2"]
    assert bad == ["--index-url"]


def test_plan_creates_venv_for_system_python(tmp_path: Path) -> None:
    interp = Interpreter("C:/Python313/python.exe", "py launcher")
    plan = packages.plan(tmp_path, interp, ["requests"], uv="uv")
    assert plan.creates_venv
    assert plan.steps[0] == ["uv", "venv", "--quiet", "--python", interp.executable, str(tmp_path / ".venv")]
    assert plan.steps[1][:4] == ["uv", "pip", "install", "--python"]
    assert plan.steps[1][-1] == "requests"
    assert ".venv" in plan.python


def test_plan_uses_existing_venv_and_pip_without_uv(tmp_path: Path) -> None:
    interp = Interpreter(str(tmp_path / ".venv" / "bin" / "python"), ".venv")
    plan = packages.plan(tmp_path, interp, ["rich"], uv="")
    assert not plan.creates_venv
    assert plan.steps == [[interp.executable, "-m", "pip", "install", "rich"]]


def test_plan_without_uv_creates_venv_with_python(tmp_path: Path) -> None:
    plan = packages.plan(tmp_path, Interpreter(sys.executable, "PATH"), ["rich"], uv="")
    assert plan.steps[0] == [sys.executable, "-m", "venv", str(tmp_path / ".venv")]
