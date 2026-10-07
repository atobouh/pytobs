"""The "Watch it run" panel: steps through a recorded run, one line at a time."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static

from .theme import C, G


@dataclass
class Loop:
    kind: str  # "item" (for x in xs) or "index" (for i in range(len(xs)) / enumerate)
    target: str
    seq: str
    start: int  # first body line
    end: int  # last body line


@dataclass
class Trace:
    steps: list[dict[str, Any]]
    output: list[tuple[int, str]]
    truncated: bool
    exception: str | None
    max_steps: int
    loops: list[Loop] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict[str, Any], source: str) -> Trace:
        trace = cls(
            steps=data.get("steps", []),
            output=[(int(i), str(t)) for i, t in data.get("output", [])],
            truncated=bool(data.get("truncated")),
            exception=data.get("exception"),
            max_steps=int(data.get("max_steps", 0)),
        )
        trace.loops = find_loops(source)
        return trace


def find_loops(source: str) -> list[Loop]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    loops = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not node.body:
            continue
        start, end = node.body[0].lineno, node.end_lineno or node.body[-1].lineno
        it, tgt = node.iter, node.target
        if isinstance(tgt, ast.Name) and isinstance(it, ast.Name):
            loops.append(Loop("item", tgt.id, it.id, start, end))
        elif isinstance(it, ast.Call) and isinstance(it.func, ast.Name):
            fn, args = it.func.id, it.args
            if (
                fn == "range"
                and len(args) == 1
                and isinstance(args[0], ast.Call)
                and isinstance(args[0].func, ast.Name)
                and args[0].func.id == "len"
                and args[0].args
                and isinstance(args[0].args[0], ast.Name)
                and isinstance(tgt, ast.Name)
            ):
                loops.append(Loop("index", tgt.id, args[0].args[0].id, start, end))
            elif (
                fn == "enumerate"
                and args
                and isinstance(args[0], ast.Name)
                and isinstance(tgt, ast.Tuple)
                and tgt.elts
                and isinstance(tgt.elts[0], ast.Name)
            ):
                loops.append(Loop("index", tgt.elts[0].id, args[0].id, start, end))
    return loops


def _previous_same_frame(trace: Trace, i: int) -> dict[str, Any] | None:
    stack = trace.steps[i]["s"]
    for j in range(i - 1, -1, -1):
        if trace.steps[j]["s"] == stack:
            return trace.steps[j]
    return None


def _pointers(trace: Trace, step: dict[str, Any]) -> dict[str, tuple[int, str]]:
    """seq name -> (index, label) for loops whose body contains this line."""
    out: dict[str, tuple[int, str]] = {}
    vars_ = step["v"]
    for loop in trace.loops:
        if not (loop.start <= step["l"] <= loop.end):
            continue
        seq, tgt = vars_.get(loop.seq), vars_.get(loop.target)
        if not seq or not tgt or "items" not in seq:
            continue
        if loop.kind == "item":
            if tgt["r"] in seq["items"]:
                out[loop.seq] = (seq["items"].index(tgt["r"]), loop.target)
        else:
            try:
                idx = int(tgt["r"])
            except ValueError:
                continue
            if 0 <= idx < len(seq["items"]):
                out[loop.seq] = (idx, loop.target)
    return out


def _boxes(items: list[str], pointer: tuple[int, str] | None, width: int) -> list[Text] | None:
    cells = [f" {r} " for r in items]
    total = sum(len(c) for c in cells) + len(cells) + 3
    if not items or total > width:
        return None
    top = Text("  ╭", style=C.overlay)
    mid = Text("  │", style=C.overlay)
    bot = Text("  ╰", style=C.overlay)
    idx = Text("   ")
    arrow = Text("   ")
    for i, cell in enumerate(cells):
        last = i == len(cells) - 1
        selected = pointer is not None and pointer[0] == i
        top.append("─" * len(cell) + ("╮" if last else "┬"), style=C.overlay)
        mid.append(cell, style=Style(color=C.text, bold=True) if selected else Style(color=C.muted))
        mid.append("│", style=C.overlay)
        bot.append("─" * len(cell) + ("╯" if last else "┴"), style=C.overlay)
        label = str(i)
        pad = (len(cell) - len(label)) // 2
        idx.append(
            " " * pad + label + " " * (len(cell) - pad - len(label) + 1),
            style=Style(color=C.accent, bold=True) if selected else Style(color=C.faint),
        )
        if selected:
            arrow.append(" " * pad + f"▲ {pointer[1]}", style=C.accent)
        elif pointer is not None and i < pointer[0]:
            arrow.append(" " * (len(cell) + 1))
    rows = [top, mid, bot, idx]
    if pointer is not None:
        rows.append(arrow)
    return rows


def render_step(trace: Trace, i: int, source_lines: list[str], width: int) -> Text:
    step = trace.steps[i]
    width = max(30, width)
    out = Text()

    def line(text: Text | str = "") -> None:
        if out.plain:
            out.append("\n")
        out.append_text(text if isinstance(text, Text) else Text(text))

    # progress bar
    bar_w = max(10, width - 2)
    filled = round(bar_w * (i + 1) / len(trace.steps))
    bar = Text()
    bar.append("━" * filled, style=C.accent)
    bar.append("━" * (bar_w - filled), style=C.surface)
    line(bar)
    line()

    lineno = step["l"]
    code = source_lines[lineno - 1].strip() if 0 < lineno <= len(source_lines) else ""
    head = Text()
    head.append(f"line {lineno}  ", style=C.muted)
    head.append(code, style=C.text)
    line(head)
    if step["f"] != "<module>":
        where = Text()
        where.append("in ", style=C.faint)
        where.append(f"{step['f']}()", style=C.callable)
        callers = [f for f in reversed(step["s"][:-1])]
        if callers:
            where.append(
                "  ← " + "  ← ".join(f if f == "<module>" else f + "()" for f in callers), style=C.faint
            )
        line(where)
    if step.get("k") == "return":
        ret = Text()
        ret.append("returns ", style=C.accent)
        ret.append(step.get("ret", ""), style=Style(color=C.text, bold=True))
        line(ret)

    prev = _previous_same_frame(trace, i)
    prev_vars = prev["v"] if prev else {}
    vars_ = step["v"]
    line()
    line(Text("variables", style=C.accent))
    if not vars_:
        line(Text("  none yet", style=C.faint))
    name_w = min(14, max((len(n) for n in vars_), default=4))
    for name, info in vars_.items():
        changed = prev is not None and prev_vars.get(name, {}).get("r") != info["r"]
        row = Text("  ")
        row.append(f"{name:<{name_w}} ", style=C.text)
        row.append(f"{info['t']:<5} ", style=C.faint)
        room = max(8, width - name_w - 18)
        value = info["r"] if len(info["r"]) <= room else info["r"][: room - 1] + "…"
        row.append(value, style=Style(color=C.accent, bold=True) if changed else Style(color=C.muted))
        if changed:
            row.append("  changed" if name in prev_vars else "  new", style=C.accent)
        line(row)

    pointers = _pointers(trace, step)
    for name, info in vars_.items():
        if "items" in info and info["items"]:
            boxes = _boxes(info["items"], pointers.get(name), width)
            if boxes:
                line()
                line(Text(name, style=C.accent))
                for row in boxes:
                    line(row)
        elif "map" in info and info["map"]:
            line()
            line(Text(name, style=C.accent))
            for key, value in info["map"][:8]:
                row = Text("  ")
                row.append(key, style=C.muted)
                row.append("  →  ", style=C.faint)
                row.append(value, style=C.constant if value[:1].isdigit() else C.text)
                line(row)

    printed = "".join(text for at, text in trace.output if at <= i + 1)
    if printed.strip():
        line()
        line(Text("output so far", style=C.accent))
        for out_line in printed.rstrip("\n").split("\n")[-4:]:
            line(Text("  " + out_line, style=C.text))

    if i == len(trace.steps) - 1:
        line()
        if trace.exception:
            err = Text()
            err.append(f"{G.cross} ", style=C.error)
            err.append(trace.exception, style=C.error)
            line(err)
            line(Text("Esc shows the full error and how to fix it", style=C.faint))
        elif trace.truncated:
            line(
                Text(
                    f"Recording stopped after {trace.max_steps} steps; the program kept running.",
                    style=C.faint,
                )
            )
        else:
            line(Text(f"{G.dot} finished", style=C.ok))
    return out


class TraceView(VerticalScroll, can_focus=True):
    DEFAULT_CSS = f"""
    TraceView {{ height: 1fr; background: {C.mantle}; padding-right: 2; display: none;
                 scrollbar-size-vertical: 1; }}
    TraceView.show {{ display: block; }}
    TraceView > Static {{ width: 1fr; height: auto; }}
    """
    BINDINGS = [
        Binding("right,l,space", "step(1)", "Next step", show=False),
        Binding("left,h,backspace", "step(-1)", "Previous step", show=False),
        Binding("shift+right,pagedown", "step(10)", "Forward 10", show=False),
        Binding("shift+left,pageup", "step(-10)", "Back 10", show=False),
        Binding("home", "jump(0)", "First step", show=False),
        Binding("end", "jump(-1)", "Last step", show=False),
        Binding("escape", "close", "Close", show=False),
    ]

    class Moved(Message):
        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    class Closed(Message):
        pass

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.trace: Trace | None = None
        self.index = 0
        self.source_lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static(id="trace-body")

    def load(self, trace: Trace, source: str) -> None:
        self.trace = trace
        self.source_lines = source.split("\n")
        self.index = 0
        self.redraw()
        self.post_message(self.Moved(0))

    def redraw(self) -> None:
        if self.trace and self.trace.steps:
            width = (self.scrollable_content_region.width or 50) - 1
            self.query_one("#trace-body", Static).update(
                render_step(self.trace, self.index, self.source_lines, width)
            )

    def on_resize(self) -> None:
        self.redraw()

    def action_step(self, delta: int) -> None:
        if not self.trace:
            return
        new = max(0, min(len(self.trace.steps) - 1, self.index + delta))
        if new != self.index:
            self.index = new
            self.redraw()
            self.post_message(self.Moved(new))

    def action_jump(self, where: int) -> None:
        if self.trace:
            self.action_step((len(self.trace.steps) - 1 if where < 0 else where) - self.index)

    def action_close(self) -> None:
        self.post_message(self.Closed())
