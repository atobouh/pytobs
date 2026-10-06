"""Find the Python interpreter that should run the user's code."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .paths import IS_WINDOWS

VENV_NAMES = (".venv", "venv", "env")


@dataclass(frozen=True)
class Interpreter:
    executable: str
    source: str  # where it came from: "config", ".venv", "VIRTUAL_ENV", "py launcher", "PATH"

    @property
    def venv_name(self) -> str | None:
        if self.source in VENV_NAMES or self.source == "VIRTUAL_ENV":
            return self.source if self.source != "VIRTUAL_ENV" else Path(self.executable).parents[1].name
        return None


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def _is_store_stub(path: str) -> bool:
    # The Microsoft Store "python.exe" alias opens the Store instead of running code.
    return IS_WINDOWS and "windowsapps" in path.lower()


def find_interpreter(file: Path | None, override: str | None = None) -> Interpreter:
    if override:
        return Interpreter(override, "config")

    start = (file.parent if file else Path.cwd()).resolve()
    home = Path.home().resolve()
    for folder in (start, *start.parents):
        for name in VENV_NAMES:
            candidate = _venv_python(folder / name)
            if candidate.exists():
                return Interpreter(str(candidate), name)
        if folder == home:
            break

    virtual_env = os.environ.get("VIRTUAL_ENV")
    if virtual_env and _venv_python(Path(virtual_env)).exists():
        return Interpreter(str(_venv_python(Path(virtual_env))), "VIRTUAL_ENV")

    if IS_WINDOWS:
        launcher = shutil.which("py")
        if launcher:
            try:
                out = subprocess.run(
                    [launcher, "-3", "-c", "import sys; print(sys.executable)"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                exe = out.stdout.strip()
                if out.returncode == 0 and exe:
                    return Interpreter(exe, "py launcher")
            except (OSError, subprocess.SubprocessError):
                pass

    for name in ("python3", "python"):
        found = shutil.which(name)
        if found and not _is_store_stub(found):
            return Interpreter(found, "PATH")

    # Last resort: the interpreter pytobs itself runs on.
    import sys

    return Interpreter(sys.executable, "pytobs")


def interpreter_version(exe: str) -> str | None:
    try:
        out = subprocess.run(
            [exe, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None
