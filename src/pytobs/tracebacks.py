"""Turn CPython's traceback text into a short, readable summary."""

from __future__ import annotations

import os
import re
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path

FRAME_RE = re.compile(r'^  File "(?P<file>.+)", line (?P<line>\d+)(?:, in (?P<func>.+))?$')
HEADER = "Traceback (most recent call last):"
CHAINED = (
    "During handling of the above exception, another exception occurred:",
    "The above exception was the direct cause of the following exception:",
)
_LIB_MARKERS = ("site-packages", "dist-packages", "<frozen ", "<string>")


@dataclass
class Frame:
    file: str
    line: int
    func: str | None
    code: list[str] = field(default_factory=list)  # source line plus any ^^^ marker lines


@dataclass
class ParsedError:
    frames: list[Frame]
    message: list[str]  # "KeyError: 'x'" plus any notes that follow
    raw: str

    @property
    def exception(self) -> str:
        return self.message[0] if self.message else ""


def _stdlib_dirs() -> tuple[str, ...]:
    dirs = {sysconfig.get_paths().get(k, "") for k in ("stdlib", "platstdlib")}
    return tuple(os.path.normcase(d) for d in dirs if d)


def is_user_frame(frame: Frame, script: Path) -> bool:
    if frame.file.startswith("<"):
        return False
    norm = os.path.normcase(frame.file)
    if any(m in norm for m in _LIB_MARKERS):
        return False
    if norm.startswith(_stdlib_dirs()) or os.sep + "lib" + os.sep + "python" in norm:
        return False
    try:
        return Path(frame.file).resolve().is_relative_to(script.parent.resolve())
    except (OSError, ValueError):
        return False


def looks_like_error_start(line: str) -> bool:
    """True for the first stderr line of a traceback or a SyntaxError report."""
    return line.startswith(HEADER) or bool(FRAME_RE.match(line))


REPEATED_RE = re.compile(r"^\s*\[Previous line repeated \d+ more times?\]$")


def parse(text: str) -> ParsedError | None:
    lines = [line for line in text.rstrip("\n").split("\n") if not REPEATED_RE.match(line)]
    # Only the last exception in a chain matters for fixing the code.
    start = None
    for i, line in enumerate(lines):
        if line.startswith(HEADER) or (start is None and FRAME_RE.match(line)):
            start = i
        elif line in CHAINED:
            start = None
    if start is None:
        return None
    block = lines[start:]
    if block[0].startswith(HEADER):
        block = block[1:]
    frames: list[Frame] = []
    i = 0
    while i < len(block):
        m = FRAME_RE.match(block[i])
        if m:
            frames.append(Frame(m["file"], int(m["line"]), m["func"]))
            i += 1
            continue
        if frames and block[i].startswith("    ") and not block[i].startswith("    ..."):
            frames[-1].code.append(block[i][4:])
            i += 1
            continue
        if block[i].startswith("  ") and not frames:
            i += 1
            continue
        break
    message = [line for line in block[i:] if line.strip()]
    if not frames and not message:
        return None
    return ParsedError(frames=frames, message=message, raw=text)


def user_frames(err: ParsedError, script: Path) -> list[Frame]:
    return [f for f in err.frames if is_user_frame(f, script)]


def jump_target(err: ParsedError, script: Path) -> int | None:
    """1-based line in `script` to jump to: the deepest frame that is in the script itself."""
    target = os.path.normcase(str(script.resolve()))
    for frame in reversed(err.frames):
        try:
            if os.path.normcase(str(Path(frame.file).resolve())) == target:
                return frame.line
        except OSError:
            continue
    return None
