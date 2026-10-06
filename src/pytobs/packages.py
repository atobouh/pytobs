"""Install packages into the project's .venv (creating it if needed)."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .env import VENV_NAMES, Interpreter, _venv_python

# A requirement like `requests`, `rich==13.7`, `pandas>=2`, `uvicorn[standard]`.
REQUIREMENT_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._\-]*(\[[A-Za-z0-9,._\-]+\])?([<>=!~]=?[A-Za-z0-9.*+!\-]+)?$"
)


@dataclass
class InstallPlan:
    steps: list[list[str]]
    python: str  # the interpreter that will have the packages
    creates_venv: bool
    where: str  # human label: ".venv", "venv", "C:/Python313/python.exe"


def parse_packages(text: str) -> tuple[list[str], list[str]]:
    """Split user input into valid requirements and rejected words."""
    words = [w for w in re.split(r"[\s,]+", text.strip()) if w]
    good = [w for w in words if REQUIREMENT_RE.match(w)]
    bad = [w for w in words if not REQUIREMENT_RE.match(w)]
    return good, bad


def plan(folder: Path, interp: Interpreter, packages: list[str], uv: str | None = None) -> InstallPlan:
    uv = uv if uv is not None else shutil.which("uv")
    steps: list[list[str]] = []
    if interp.source in VENV_NAMES or interp.source in ("VIRTUAL_ENV", "config"):
        python = interp.executable
        creates = False
        where = interp.source if interp.source in VENV_NAMES else python
    else:
        venv = folder / ".venv"
        python = str(_venv_python(venv))
        creates = True
        where = ".venv"
        if uv:
            steps.append([uv, "venv", "--quiet", "--python", interp.executable, str(venv)])
        else:
            steps.append([interp.executable, "-m", "venv", str(venv)])
    if uv:
        steps.append([uv, "pip", "install", "--python", python, *packages])
    else:
        steps.append([python, "-m", "pip", "install", *packages])
    return InstallPlan(steps=steps, python=python, creates_venv=creates, where=where)
