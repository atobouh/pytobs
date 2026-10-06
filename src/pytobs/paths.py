"""Where pytobs keeps config, session state and scratch files."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def data_dir() -> Path:
    if IS_WINDOWS:
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "pytobs"


def config_path() -> Path:
    if IS_WINDOWS:
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "pytobs" / "config.toml"


def scratch_dir() -> Path:
    return data_dir() / "scratch"


def new_scratch_path() -> Path:
    folder = scratch_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return folder / f"scratch-{stamp}.py"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".pytobs-tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


@dataclass
class Config:
    python: str | None = None
    format_on_save: bool = False
    autosave: bool = True

    @classmethod
    def load(cls) -> Config:
        path = config_path()
        if not path.exists():
            return cls()
        try:
            import tomllib
        except ModuleNotFoundError:  # Python 3.10
            return cls()
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(
            python=data.get("python") or None,
            format_on_save=bool(data.get("format_on_save", False)),
            autosave=bool(data.get("autosave", True)),
        )


@dataclass
class Session:
    last_file: str | None = None
    cursors: dict[str, list[int]] = field(default_factory=dict)

    @staticmethod
    def path() -> Path:
        return data_dir() / "session.json"

    @classmethod
    def load(cls) -> Session:
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
            return cls(last_file=data.get("last_file"), cursors=dict(data.get("cursors", {})))
        except (OSError, ValueError):
            return cls()

    def save(self) -> None:
        # keep the 200 most recent cursor positions
        if len(self.cursors) > 200:
            self.cursors = dict(list(self.cursors.items())[-200:])
        try:
            atomic_write(self.path(), json.dumps({"last_file": self.last_file, "cursors": self.cursors}))
        except OSError:
            pass
