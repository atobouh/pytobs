"""Small text helpers shared by the editor features (no Textual imports)."""

from __future__ import annotations

import io
import re
import tokenize

WORD_CHARS = re.compile(r"[A-Za-z0-9_]")


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def code_part(line: str) -> str:
    """The line without a trailing # comment (quotes are respected)."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def word_at(line: str, col: int) -> tuple[str, int]:
    """The identifier touching column `col`, and where it starts."""
    start = col
    while start > 0 and WORD_CHARS.match(line[start - 1]):
        start -= 1
    end = col
    while end < len(line) and WORD_CHARS.match(line[end]):
        end += 1
    word = line[start:end]
    if not word or word[0].isdigit():
        return "", col
    return word, start


def find_all(lines: list[str], query: str) -> list[tuple[int, int, int]]:
    """(row, start, end) of every match. Lowercase queries ignore case; any capital makes it exact."""
    if not query:
        return []
    fold = query == query.lower()
    needle = query.lower() if fold else query
    out = []
    for row, line in enumerate(lines):
        hay = line.lower() if fold else line
        start = hay.find(needle)
        while start >= 0:
            out.append((row, start, start + len(needle)))
            start = hay.find(needle, start + len(needle))
    return out


def rename_symbol(source: str, old: str, new: str) -> tuple[str, int]:
    """Replace the name `old` with `new` wherever it is used as a name (not inside strings or
    comments). Returns the new source and how many were replaced."""
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        tokens = None
    lines = source.split("\n")
    spots: list[tuple[int, int]] = []
    if tokens is not None:
        spots = [(t.start[0] - 1, t.start[1]) for t in tokens if t.type == tokenize.NAME and t.string == old]
    else:
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])")
        for row, line in enumerate(lines):
            spots.extend((row, m.start()) for m in pattern.finditer(code_part(line)))
    for row, col in sorted(spots, reverse=True):
        line = lines[row]
        lines[row] = line[:col] + new + line[col + len(old) :]
    return "\n".join(lines), len(spots)


OUTLINE_RE = re.compile(r"^(\s*)(async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(\([^)]*\)?)?")


def outline(lines: list[str]) -> list[tuple[int, int, str, str]]:
    """Every def and class: (row, depth, kind, label). Works on code that doesn't parse yet."""
    out = []
    for row, line in enumerate(lines):
        m = OUTLINE_RE.match(line)
        if not m:
            continue
        indent, kind, name, args = m.groups()
        kind = "class" if kind == "class" else "def"
        label = name + (args or ("()" if kind == "def" else ""))
        out.append((row, len(indent) // 4, kind, label))
    return out
