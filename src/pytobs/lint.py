"""ruff check and ruff format, fed the unsaved buffer over stdin."""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .paths import IS_WINDOWS

_FLAGS = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}  # type: ignore[attr-defined]


@dataclass(frozen=True)
class Diagnostic:
    row: int  # 0-based
    col: int  # 0-based
    code: str
    message: str
    error: bool  # syntax errors and F821-style failures vs. style warnings


@lru_cache(maxsize=1)
def ruff_bin() -> str | None:
    try:
        from ruff.__main__ import find_ruff_bin

        return str(find_ruff_bin())
    except Exception:
        import shutil

        return shutil.which("ruff")


async def _run(args: list[str], source: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **_FLAGS,  # type: ignore[arg-type]
    )
    out, err = await proc.communicate(source.encode("utf-8"))
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


ERROR_CODES = ("F821", "F822", "F823", "F63", "F7", "E9")


async def check(source: str, path: Path) -> list[Diagnostic]:
    exe = ruff_bin()
    if not exe:
        return []
    args = [
        exe,
        "check",
        "--output-format=json",
        "--no-cache",
        "--exit-zero",
        "--quiet",
        "--stdin-filename",
        str(path),
        "-",
    ]
    try:
        _, out, _ = await _run(args, source)
        items = json.loads(out or "[]")
    except (OSError, ValueError):
        return []
    diags = []
    for item in items:
        loc = item.get("location") or {}
        code = item.get("code") or "syntax"
        diags.append(
            Diagnostic(
                row=max(0, int(loc.get("row", 1)) - 1),
                col=max(0, int(loc.get("column", 1)) - 1),
                code=code,
                message=item.get("message", "").strip(),
                error=code == "syntax" or code.startswith(ERROR_CODES),
            )
        )
    diags.sort(key=lambda d: (d.row, d.col))
    return diags


async def format_source(source: str, path: Path) -> str | None:
    exe = ruff_bin()
    if not exe:
        return None
    try:
        code, out, _ = await _run([exe, "format", "--quiet", "--stdin-filename", str(path), "-"], source)
    except OSError:
        return None
    return out if code == 0 else None
