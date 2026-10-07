"""pytobs: write, run, fix."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Iterable
import dataclasses
from dataclasses import dataclass
from functools import partial, wraps
from pathlib import Path

from rich.style import Style
from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.command import CommandPalette, DiscoveryHit, Hit, Hits, Provider, SearchIcon
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.timer import Timer
from textual.message import Message
from textual.widgets import Input, Static, TextArea
from textual.widgets.text_area import Selection

from . import explain, lint, packages, tracebacks
from .completion.client import CompletionClient
from .editor import CodeEditor
from .env import Interpreter, find_interpreter, interpreter_version
from .output import OutputLog
from .paths import Config, Session, atomic_write, data_dir, new_scratch_path, scratch_dir
from .runner import Run
from .stats import Stats, fmt_duration, level
from .theme import APP_THEME, C, G
from .trace_view import Trace, TraceView

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "site-packages",
    ".idea",
    ".vscode",
    "dist",
    "build",
}


def short_path(path: Path) -> str:
    try:
        return "~" + os.sep + str(path.resolve().relative_to(Path.home().resolve()))
    except ValueError:
        return str(path)


class FileProvider(Provider):
    """Fuzzy-open Python files under the working folder and the scratch folder."""

    def _files(self) -> list[Path]:
        roots = [Path.cwd()]
        app = self.app
        if isinstance(app, Pytobs) and app.file_path:
            roots.insert(0, app.file_path.parent)
        roots.append(scratch_dir())
        seen: dict[str, Path] = {}
        for root in roots:
            if not root.exists():
                continue
            count = 0
            for folder, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
                for name in files:
                    if name.endswith((".py", ".pyw", ".txt", ".toml", ".json", ".md", ".csv")):
                        p = Path(folder) / name
                        seen.setdefault(str(p.resolve()), p)
                        count += 1
                if count > 3000 or folder.count(os.sep) - str(root).count(os.sep) > 6:
                    dirs[:] = []
        return sorted(seen.values(), key=lambda p: (p.suffix != ".py", str(p).lower()))

    async def startup(self) -> None:
        self._cache = await asyncio.to_thread(self._files)

    def _label(self, p: Path) -> str:
        try:
            return str(p.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            return short_path(p)

    async def discover(self) -> Hits:
        app = self.app
        if isinstance(app, Pytobs):
            for tab in app.tabs:
                yield DiscoveryHit(f"{self._label(tab.path)}   open", partial(self._open, tab.path))
        for p in self._cache[:40]:
            yield DiscoveryHit(self._label(p), partial(self._open, p), help=None)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for p in self._cache:
            label = self._label(p)
            score = matcher.match(label)
            if score > 0:
                yield Hit(score, matcher.highlight(label), partial(self._open, p))

    def _open(self, p: Path) -> None:
        app = self.app
        if isinstance(app, Pytobs):
            app.open_file(p)


MAX_RESTORED_TABS = 12


def ignore_after_exit(fn):
    """For background jobs: if the window is already closing, the widgets are gone; drop the result."""

    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            return await fn(self, *args, **kwargs)
        except NoMatches:
            return None

    return wrapper


@dataclass
class Tab:
    """An open file. The active tab's live state is in the editor; others keep theirs here."""

    path: Path
    text: str = ""
    saved_text: str = ""
    selection: Selection | None = None
    scroll: tuple[float, float] = (0.0, 0.0)
    history: object | None = None


class TabBar(Static):
    """One row of file tabs. Click a tab to focus it; click × or middle-click to close it."""

    class Clicked(Message):
        def __init__(self, index: int, close: bool) -> None:
            super().__init__()
            self.index = index
            self.close = close

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.hits: list[tuple[int, int, int, bool]] = []  # (x0, x1, tab index, is close button)

    def on_click(self, event: events.Click) -> None:
        for x0, x1, index, close in self.hits:
            if x0 <= event.x < x1:
                self.post_message(self.Clicked(index, close or event.button == 2))
                return


CSS = f"""
Screen {{ background: {C.base}; layers: base popup; }}
#main {{ height: 1fr; }}
#editor-col {{ width: 3fr; background: {C.base}; }}
#tabline {{ height: 1; margin-bottom: 1; color: {C.muted}; background: {C.mantle}; }}
CodeEditor {{ border: none; padding: 0 1 0 0; background: {C.base}; height: 1fr; scrollbar-size-vertical: 1; scrollbar-size-horizontal: 0; }}
CodeEditor:focus {{ border: none; }}
#output-col {{ width: 2fr; min-width: 30; background: {C.mantle}; padding: 0 0 0 2; }}
#runhead {{ height: 1; margin-bottom: 1; padding-right: 2; }}
OutputLog {{ height: 1fr; }}
#stdin {{ height: 1; border: none; padding: 0; margin: 1 2 0 0; background: {C.surface}; color: {C.text}; display: none; }}
#stdin:focus {{ border: none; }}
#stdin.show {{ display: block; }}
#status {{ dock: bottom; height: 1; background: {C.mantle}; color: {C.muted}; padding: 0 2; }}
Screen.stacked #main {{ layout: vertical; }}
Screen.stacked #editor-col {{ width: 1fr; height: 3fr; }}
Screen.stacked #output-col {{ width: 1fr; height: 2fr; padding: 1 0 0 2; }}
#popup {{ layer: popup; position: absolute; width: auto; height: auto; display: none; }}
#popup.show {{ display: block; }}
#menu {{ width: auto; height: auto; background: {C.surface}; }}
#doc {{ width: auto; max-width: 64; height: auto; overflow: hidden hidden; background: {C.surface}; padding: 1 2; margin-left: 1; display: none; }}
#doc.show {{ display: block; }}
#sig {{ layer: popup; position: absolute; width: auto; height: 1; background: {C.surface}; padding: 0 1; display: none; }}
#sig.show {{ display: block; }}
"""


class Pytobs(App[None]):
    TITLE = "pytobs"
    CSS = CSS
    COMMAND_PALETTE_BINDING = "ctrl+k"
    BINDINGS = [
        Binding("ctrl+r,f5", "run", "Run", priority=True),
        Binding("f6", "trace", "Watch it run", priority=True),
        Binding("ctrl+t", "run_tests", "Run tests", priority=True),
        Binding("ctrl+g", "progress", "Progress", priority=True),
        Binding("ctrl+c", "ctrl_c", "Stop / copy", priority=True, show=False),
        Binding("ctrl+e", "jump_error", "Jump to error", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("ctrl+o,ctrl+p", "open", "Open file", priority=True),
        Binding("ctrl+n", "new_scratch", "New scratch", priority=True),
        Binding("ctrl+w", "close_tab", "Close file", priority=True),
        Binding("ctrl+pagedown,alt+right", "next_tab", "Next file", priority=True),
        Binding("ctrl+pageup,alt+left", "prev_tab", "Previous file", priority=True),
        *[
            Binding(f"alt+{n}", f"goto_tab({n - 1})", f"File {n}", priority=True, show=False)
            for n in range(1, 10)
        ],
        Binding("alt+f,f8", "format", "Format", priority=True),
        Binding("ctrl+l", "clear_output", "Clear output", priority=True),
        Binding("ctrl+b", "toggle_layout", "Layout", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(self, path: Path | None = None, python: str | None = None) -> None:
        super().__init__()
        self.cfg = Config.load()
        self.session = Session.load()
        self.python_override = python or self.cfg.python
        self.file_path: Path | None = path
        self.saved_text = ""
        self.interp: Interpreter | None = None
        self.py_version: str | None = None
        self.current: Run | None = None
        self.run_count = 0
        self.last_run: tuple[int, float] | None = None  # exit code, seconds
        self.error_jump: int | None = None
        self._stderr_buffer: list[str] | None = None
        self.diags: list[lint.Diagnostic] = []
        self.completion = CompletionClient()
        self._comp_gen = 0
        self._comp_items: list[dict] = []
        self._comp_view: list[dict] = []
        self._comp_sel = 0
        self._comp_start: tuple[int, int] | None = None
        self._doc_gen = 0
        self._debouncers: dict[str, Timer] = {}
        self._layout_forced: str | None = None
        self.tabs: list[Tab] = []
        self.active = -1
        self.stats = Stats.load()
        self.mode = "run"  # what the current process is: "run", "trace" or "tests"
        self._result_path: Path | None = None
        self._stopped = False
        self.last_error: tuple[str, str] | None = None  # (exception type, concept to review)
        self._activity: str | None = None  # label shown while a non-script command runs
        self._note: Text | None = None  # result line for the run header (e.g. after an install)
        self.register_theme(APP_THEME)
        self.theme = "sumi"

    # ── layout ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="editor-col"):
                yield TabBar(id="tabline")
                yield CodeEditor(id="editor")
            with Vertical(id="output-col"):
                yield Static(id="runhead")
                yield OutputLog(id="output")
                yield TraceView(id="trace")
                yield Input(id="stdin", placeholder="type input for the program, Enter to send")
        yield Static(id="status")
        with Horizontal(id="popup"):
            yield Static(id="menu")
            yield Static(id="doc")
        yield Static(id="sig")

    @property
    def editor(self) -> CodeEditor:
        return self.query_one(CodeEditor)

    @property
    def output(self) -> OutputLog:
        return self.query_one(OutputLog)

    def on_mount(self) -> None:
        wanted = self.file_path
        restore = [Path(f) for f in self.session.open_files if Path(f).is_file()][-MAX_RESTORED_TABS:]
        last = Path(self.session.last_file) if self.session.last_file else None
        for path in restore:
            self._add_tab(path)
        if wanted is not None:
            target = wanted
        elif last is not None and last.is_file():
            target = last
        elif self.tabs:
            target = self.tabs[-1].path
        else:
            target = new_scratch_path()
        self.open_file(target, initial=True)
        self._show_welcome()
        self.editor.focus()
        self._apply_layout()
        self.call_after_refresh(self._after_first_paint)
        self.set_interval(60, self.stats.save)

    def _show_welcome(self) -> None:
        out = self.output
        out.clear()
        out.add_line(Text("Write some Python, then", style=C.muted))
        out.add_line(Text(""))
        for key, label in (
            ("Ctrl+R", "run"),
            ("F6", "watch it run, step by step"),
            ("Ctrl+T", "run tests"),
            ("Ctrl+E", "jump to an error"),
            ("Ctrl+P", "open a file in a new tab"),
            ("Alt+← →", "switch between open files"),
            ("Ctrl+G", "your progress"),
            ("Ctrl+K", "all commands, install packages"),
        ):
            line = Text()
            line.append(f"{key:<8}", style=C.text)
            line.append(label, style=C.muted)
            out.add_line(line)

    def _after_first_paint(self) -> None:
        self.editor.enable_highlighting()
        self.detect_interpreter()
        self.schedule_lint(0.2)

    def on_resize(self) -> None:
        self._apply_layout()
        self.call_after_refresh(self._render_tabline)
        self.hide_popups()

    def _apply_layout(self) -> None:
        stacked = self._layout_forced == "stacked" or (self._layout_forced is None and self.size.width < 100)
        self.screen.set_class(stacked, "stacked")

    def action_toggle_layout(self) -> None:
        current = self.screen.has_class("stacked")
        self._layout_forced = "side" if current else "stacked"
        self._apply_layout()

    # ── files ────────────────────────────────────────────────────────────────

    def _tab_index(self, path: Path) -> int:
        key = os.path.normcase(str(path))
        for i, tab in enumerate(self.tabs):
            if os.path.normcase(str(tab.path)) == key:
                return i
        return -1

    def _add_tab(self, path: Path, at: int | None = None) -> int:
        """Read a file into a new tab (created if missing). Returns its index, or -1 on failure."""
        path = path.expanduser().resolve()
        existing = self._tab_index(path)
        if existing >= 0:
            return existing
        try:
            text = path.read_text(encoding="utf-8-sig") if path.exists() else ""  # tolerate Notepad BOMs
        except (OSError, UnicodeDecodeError) as exc:
            self.notify(f"Can't open {path.name}: {exc}", severity="error")
            return -1
        if not path.exists():
            try:
                atomic_write(path, "")
            except OSError as exc:
                self.notify(f"Can't create {path}: {exc}", severity="error")
                return -1
        tab = Tab(path=path, text=text, saved_text=text)
        index = len(self.tabs) if at is None else at
        self.tabs.insert(index, tab)
        if 0 <= self.active and index <= self.active:
            self.active += 1
        return index

    def open_file(self, path: Path, initial: bool = False) -> None:
        index = self._add_tab(path, at=None if self.active < 0 else self.active + 1)
        if index >= 0:
            self._activate(index, initial=initial)
        elif not self.tabs:
            self._activate(self._add_tab(new_scratch_path()), initial=initial)

    def _stash(self) -> None:
        """Copy the editor's live state into the active tab."""
        if 0 <= self.active < len(self.tabs):
            tab = self.tabs[self.active]
            editor = self.editor
            tab.text = editor.text
            tab.saved_text = self.saved_text
            tab.selection = editor.selection
            tab.scroll = (editor.scroll_offset.x, editor.scroll_offset.y)
            tab.history = editor.history

    def _activate(self, index: int, initial: bool = False) -> None:
        if not (0 <= index < len(self.tabs)):
            return
        if index == self.active and not initial:
            self.editor.focus()
            return
        if self.active >= 0 and not initial:
            self.save()
            self.remember_cursor()
            self._stash()
        self.close_trace()
        self.active = index
        tab = self.tabs[index]
        self.file_path = tab.path
        editor = self.editor
        # load_text clears the editor's history object in place; detach the stashed one first
        editor.history = dataclasses.replace(editor.history)
        editor.load_text(tab.text)
        if tab.history is not None:
            editor.history = tab.history  # undo/redo survive switching files
        if not initial:
            editor.enable_highlighting()
        self.saved_text = tab.saved_text
        if tab.selection is not None:
            editor.selection = tab.selection
            editor.scroll_to(*tab.scroll, animate=False, immediate=True)
        else:
            cursor = self.session.cursors.get(str(tab.path))
            if cursor:
                row = min(cursor[0], editor.document.line_count - 1)
                editor.move_cursor((row, cursor[1]), center=True)
        self._save_session()
        self.error_jump = None
        editor.set_error_line(None)
        self.diags = []
        editor.set_diagnostics([])
        self.hide_popups()
        if not initial:
            self.detect_interpreter()
            self.schedule_lint(0.1)
            editor.focus()
        self.refresh_chrome()

    def _save_session(self) -> None:
        self.session.last_file = str(self.file_path) if self.file_path else None
        self.session.open_files = [str(t.path) for t in self.tabs]
        self.session.save()

    def action_close_tab(self, index: int | None = None) -> None:
        index = self.active if index is None else index
        if not (0 <= index < len(self.tabs)):
            return
        if index == self.active:
            self.save()
            self.remember_cursor()
        tab = self.tabs[index]
        text = self.editor.text if index == self.active else tab.text
        if tab.path.parent == scratch_dir().resolve() and not text.strip():
            tab.path.unlink(missing_ok=True)  # an empty scratch file isn't worth keeping
        if len(self.tabs) == 1:
            self.tabs.clear()
            self.active = -1
            self.open_file(new_scratch_path())
            return
        del self.tabs[index]
        if index == self.active:
            self.active = -1  # nothing to stash: the closed tab is gone
            self._activate(min(index, len(self.tabs) - 1), initial=False)
        else:
            if index < self.active:
                self.active -= 1
            self._save_session()
            self._render_tabline()

    def action_next_tab(self) -> None:
        if len(self.tabs) > 1:
            self._activate((self.active + 1) % len(self.tabs))

    def action_prev_tab(self) -> None:
        if len(self.tabs) > 1:
            self._activate((self.active - 1) % len(self.tabs))

    def action_goto_tab(self, index: int) -> None:
        if index < len(self.tabs):
            self._activate(index)

    @on(TabBar.Clicked)
    def _tab_clicked(self, event: TabBar.Clicked) -> None:
        if event.close:
            self.action_close_tab(event.index)
        else:
            self._activate(event.index)

    def remember_cursor(self) -> None:
        if self.file_path:
            self.session.cursors[str(self.file_path)] = list(self.editor.cursor_location)
            self.session.save()

    @property
    def dirty(self) -> bool:
        return self.editor.text != self.saved_text

    def save(self) -> bool:
        if not self.file_path or not self.dirty:
            return True
        text = self.editor.text
        try:
            atomic_write(self.file_path, text)
        except OSError as exc:
            self.notify(f"Couldn't save: {exc}", severity="error")
            return False
        self.saved_text = text
        self.refresh_chrome()
        return True

    def action_save(self) -> None:
        if self.cfg.format_on_save:
            self.run_worker(self._format_then_save(), exclusive=True, group="format")
        else:
            self.save()

    async def _format_then_save(self) -> None:
        await self._format()
        self.save()

    def action_new_scratch(self) -> None:
        self.open_file(new_scratch_path())

    def action_open(self) -> None:
        if not CommandPalette.is_open(self):
            self.push_screen(_palette([FileProvider], "Open a file…"))

    # ── chrome: tab line, run header, status bar ─────────────────────────────

    def refresh_chrome(self) -> None:
        self._render_tabline()
        self._render_runhead()
        self._render_status()

    def _render_tabline(self) -> None:
        bar = self.query_one(TabBar)
        width = max(20, bar.size.width or self.size.width // 2)
        scratch = scratch_dir().resolve()
        cells: list[tuple[Text, int, int]] = []  # (text, tab index, close offset or -1)
        for i, tab in enumerate(self.tabs):
            active = i == self.active
            dirty = self.dirty if active else tab.text != tab.saved_text
            bg = C.base if active else C.mantle
            t = Text()
            t.append("  ", style=Style(bgcolor=bg))
            name = tab.path.name if len(tab.path.name) <= 28 else tab.path.name[:27] + "…"
            t.append(name, style=Style(color=C.text if active else C.muted, bgcolor=bg, bold=active))
            if tab.path.parent == scratch:
                t.append(" scratch", style=Style(color=C.faint, bgcolor=bg))
            close_at = -1
            if dirty:
                t.append(f" {G.dot}", style=Style(color=C.accent if active else C.muted, bgcolor=bg))
            elif active and len(self.tabs) > 1:
                close_at = t.cell_len + 1
                t.append(f" {G.cross}", style=Style(color=C.faint, bgcolor=bg))
            t.append("  ", style=Style(bgcolor=bg))
            cells.append((t, i, close_at))
        # keep the active tab visible: widen a window around it until the bar is full
        lo = hi = max(0, self.active)
        used = cells[lo][0].cell_len if cells else 0
        while True:
            grown = False
            for cand in (hi + 1, lo - 1):
                if 0 <= cand < len(cells) and (cand > hi or cand < lo):
                    w = cells[cand][0].cell_len
                    if used + w <= width - 6:
                        used += w
                        lo, hi = min(lo, cand), max(hi, cand)
                        grown = True
            if not grown:
                break
        line = Text(no_wrap=True, overflow="crop")
        hits: list[tuple[int, int, int, bool]] = []
        if lo > 0:
            line.append(f" ‹{lo} ", style=C.faint)
        for t, i, close_at in cells[lo : hi + 1]:
            x0 = line.cell_len
            line.append_text(t)
            if close_at >= 0:
                hits.append((x0 + close_at, x0 + close_at + 1, i, True))
            hits.append((x0, line.cell_len, i, False))
        if hi < len(cells) - 1:
            line.append(f" {len(cells) - 1 - hi}› ", style=C.faint)
        bar.hits = hits
        bar.update(line)

    def _render_runhead(self) -> None:
        t = Text(no_wrap=True, overflow="ellipsis")
        run = self.current
        if run and not run.finished:
            frame = G.spinner[int(time.monotonic() * 8) % len(G.spinner)]
            t.append(f"{frame} ", style=C.accent)
            t.append(self._activity or "running", style=C.text)
            t.append(f"   {run.elapsed:5.1f}s", style=C.muted)
            t.append("     ^C stop", style=C.faint)
        elif self.query_one(TraceView).has_class("show") and self.query_one(TraceView).trace:
            view = self.query_one(TraceView)
            total = len(view.trace.steps)
            t.append(f"{G.run} ", style=C.accent)
            t.append("watch it run", style=C.text)
            t.append("   step ", style=C.muted)
            t.append(str(view.index + 1), style=C.text)
            t.append(f" of {total}", style=C.muted)
            t.append("     ← → step   Esc done", style=C.faint)
        elif self._note is not None:
            t.append_text(self._note)
        elif self.last_run:
            code, seconds = self.last_run
            t.append(f"{G.run} ", style=C.accent)
            t.append(f"run {self.run_count}", style=C.text)
            t.append(f"   {_fmt_seconds(seconds)}", style=C.muted)
            if self._stopped:
                t.append("   stopped", style=C.muted)
            else:
                t.append("   exit ", style=C.muted)
                t.append(str(code), style=C.ok if code == 0 else C.error)
        else:
            t.append("output", style=C.muted)
            t.append("   ^R to run", style=C.faint)
        self.query_one("#runhead", Static).update(t)

    def _render_status(self) -> None:
        editor = self.editor
        row, col = editor.cursor_location
        width = self.size.width - 4
        left = Text(no_wrap=True, overflow="ellipsis")
        if self.file_path:
            left.append(short_path(self.file_path), style=C.text)
        if self.interp:
            label = f"py {self.py_version}" if self.py_version else "py"
            venv = self.interp.source if self.interp.source in (".venv", "venv", "env") else None
            left.append(f"   {label}", style=C.muted)
            if venv:
                left.append(f" {G.sep} {venv}", style=C.muted)
        diag = editor.diagnostics.get(row)
        mid = Text(no_wrap=True, overflow="ellipsis")
        if diag:
            mid.append(f"{diag.code} ", style=C.error if diag.error else C.warn)
            mid.append(diag.message, style=C.text)
        elif self.diags:
            n = len(self.diags)
            errors = sum(d.error for d in self.diags)
            mid.append(f"{G.dot} ", style=C.error if errors else C.warn)
            mid.append(f"{n} problem{'s' if n != 1 else ''}", style=C.muted)
        else:
            mid.append(f"{G.dot} ", style=C.ok)
            mid.append("ruff", style=C.muted)
        right = Text(no_wrap=True)
        right.append(f"Ln {row + 1:<4} Col {col + 1:<3}", style=C.muted)
        hints = Text(no_wrap=True)
        for key, label in (("^R", "run"), ("^P", "open"), ("^K", "menu")):
            hints.append("   ")
            hints.append(key, style=C.text)
            hints.append(f" {label}", style=C.muted)
        if width > 110:
            right.append_text(hints)
        gap = 3
        room = width - right.cell_len - gap
        left.truncate(max(10, min(left.cell_len, room // 2)), overflow="ellipsis")
        room_mid = max(0, room - left.cell_len - gap)
        mid.truncate(room_mid, overflow="ellipsis")
        pad = max(1, width - left.cell_len - mid.cell_len - right.cell_len - gap)
        line = Text(no_wrap=True)
        line.append_text(left)
        line.append(" " * gap)
        line.append_text(mid)
        line.append(" " * pad)
        line.append_text(right)
        self.query_one("#status", Static).update(line)

    # ── editor events ────────────────────────────────────────────────────────

    @on(TextArea.Changed, "#editor")
    def _on_edit(self) -> None:
        self.stats.touch()
        if self.query_one(TraceView).has_class("show"):
            self.close_trace()
        self._render_tabline()
        if self.editor.error_line is not None:
            self.editor.set_error_line(None)
        if self.cfg.autosave:
            self._debounce("autosave", 1.0, self.save)
        self.schedule_lint(0.5)

    @on(TextArea.SelectionChanged, "#editor")
    def _on_cursor(self) -> None:
        self._render_status()
        start = self._comp_start
        if start is not None:
            row, col = self.editor.cursor_location
            if row != start[0] or col < start[1]:
                self.hide_popups()
        sig = self.query_one("#sig")
        if sig.has_class("show") and self.editor.cursor_location[0] != getattr(self, "_sig_row", -1):
            sig.remove_class("show")

    @on(CodeEditor.Typed)
    def _on_typed(self, event: CodeEditor.Typed) -> None:
        char = event.char
        if char in "(,":
            self._debounce("sig", 0.05, self.request_signature)
        elif char == ")":
            self.query_one("#sig").remove_class("show")
        word, _ = self.editor.current_word()
        if char == ".":
            self.request_completion()
        elif char.isalnum() or char == "_":
            if self._comp_items and self._comp_start is not None:
                self._filter_completion()
                if not self._comp_view:
                    self.hide_completion()
            if len(word) >= 2 and not self._comp_view:
                self._debounce("complete", 0.06, self.request_completion)
        else:
            self.hide_completion()

    @on(CodeEditor.PopupKey)
    def _on_popup_key(self, event: CodeEditor.PopupKey) -> None:
        key = event.key
        menu_open = self.query_one("#popup").has_class("show")
        if key == "escape" or not menu_open:
            self.hide_popups()
            return
        if key in ("down", "up", "pagedown", "pageup"):
            step = {"down": 1, "up": -1, "pagedown": 8, "pageup": -8}[key]
            self._comp_sel = (self._comp_sel + step) % max(1, len(self._comp_view))
            self._render_menu()
            self._debounce("doc", 0.12, self.request_doc)
        elif key in ("tab", "enter"):
            self.accept_completion()

    # ── completion ───────────────────────────────────────────────────────────

    @work(group="interp", exclusive=True)
    @ignore_after_exit
    async def detect_interpreter(self) -> None:
        interp = await asyncio.to_thread(find_interpreter, self.file_path, self.python_override)
        changed = interp != self.interp
        self.interp = interp
        if changed or not self.py_version:
            self.py_version = await asyncio.to_thread(interpreter_version, interp.executable)
            self._render_status()
        if changed or not self.completion.alive:
            try:
                await self.completion.start(interp.executable)
                await self.completion.request(
                    "warm", source=self.editor.text, path=str(self.file_path), timeout=30
                )
            except OSError:
                pass

    def request_completion(self) -> None:
        self._comp_gen += 1
        gen = self._comp_gen
        editor = self.editor
        row, col = editor.cursor_location
        _, start = editor.current_word()
        self._comp_start = start
        self._fetch_completion(gen, editor.text, row + 1, col, start)

    @work(group="complete")
    @ignore_after_exit
    async def _fetch_completion(
        self, gen: int, source: str, line: int, col: int, start: tuple[int, int]
    ) -> None:
        items = await self.completion.request(
            "complete", source=source, line=line, col=col, path=str(self.file_path), timeout=8
        )
        if gen != self._comp_gen or not items:
            if gen == self._comp_gen:
                self.hide_completion()
            return
        self._comp_items = items
        self._comp_start = start
        self._filter_completion()

    def _filter_completion(self) -> None:
        word, start = self.editor.current_word()
        if self._comp_start != start:
            self._comp_start = start
        lw = word.lower()
        if lw:
            prefix = [i for i in self._comp_items if i["name"].lower().startswith(lw)]
            contains = [i for i in self._comp_items if lw in i["name"].lower() and i not in prefix]
            view = prefix + contains
        else:
            view = [i for i in self._comp_items if not i["name"].startswith("_")] or self._comp_items
        if len(view) == 1 and view[0]["name"] == word:
            view = []
        self._comp_view = view[:100]
        self._comp_sel = 0
        if self._comp_view:
            self._render_menu()
            self._debounce("doc", 0.12, self.request_doc)
        else:
            self.hide_completion()

    def _render_menu(self) -> None:
        view = self._comp_view
        rows = 8
        top = max(0, min(self._comp_sel - rows + 1, len(view) - rows)) if self._comp_sel >= rows else 0
        shown = view[top : top + rows]
        width = min(40, max(14, max(len(i["name"]) for i in shown) + 4))
        t = Text(no_wrap=True)
        for idx, item in enumerate(shown, start=top):
            selected = idx == self._comp_sel
            bg = C.overlay if selected else C.surface
            t.append("▌" if selected else " ", style=Style(color=C.accent, bgcolor=bg))
            name = item["name"]
            if len(name) > width - 4:
                name = name[: width - 5] + "…"
            t.append(f"{name:<{width - 4}}", style=Style(color=C.text, bgcolor=bg, bold=selected))
            t.append(f" {item['kind']} ", style=Style(color=C.muted, bgcolor=bg))
            if idx != top + len(shown) - 1:
                t.append("\n")
        self.query_one("#menu", Static).update(t)
        popup = self.query_one("#popup")
        popup.add_class("show")
        self.editor.popup_open = True
        self._position_popup(width, len(shown))

    def _position_popup(self, width: int, height: int) -> None:
        editor = self.editor
        cursor = editor.cursor_screen_offset
        word, _ = editor.current_word()
        x = max(0, cursor.x - len(word) - 1)
        y = cursor.y + 1
        if y + height >= self.size.height - 1:
            y = max(0, cursor.y - height)
        x = min(x, max(0, self.size.width - width - 1))
        self.query_one("#popup").styles.offset = (x, y)

    def request_doc(self) -> None:
        if not self._comp_view:
            return
        self._doc_gen += 1
        self._fetch_doc(self._doc_gen, self._comp_view[self._comp_sel]["name"])

    @work(group="doc")
    @ignore_after_exit
    async def _fetch_doc(self, gen: int, name: str) -> None:
        info = await self.completion.request("doc", name=name, timeout=5)
        doc = self.query_one("#doc", Static)
        if gen != self._doc_gen or not self.query_one("#popup").has_class("show"):
            return
        if not info or not (info.get("signatures") or info.get("doc")):
            doc.remove_class("show")
            return
        t = Text()
        for sig in info.get("signatures", []):
            t.append(sig + "\n", style=C.callable)
        if info.get("doc"):
            if info.get("signatures"):
                t.append("\n")
            t.append(info["doc"], style=C.muted)
        t.rstrip()
        popup = self.query_one("#popup")
        menu_width = self.query_one("#menu").size.width
        room = self.size.width - int(popup.styles.offset.x.value) - menu_width - 6
        if room < 30:
            doc.remove_class("show")
            return
        doc.styles.max_width = min(64, room)
        doc.styles.max_height = max(4, self.size.height - int(popup.styles.offset.y.value) - 2)
        doc.update(t)
        doc.add_class("show")

    def accept_completion(self) -> None:
        if not self._comp_view:
            self.hide_completion()
            return
        name = self._comp_view[self._comp_sel]["name"]
        editor = self.editor
        _, start = editor.current_word()
        end = editor.cursor_location
        editor.replace(name, start, end)
        editor.move_cursor((start[0], start[1] + len(name)))
        self.hide_completion()

    def hide_completion(self) -> None:
        self._comp_gen += 1
        self._comp_items = []
        self._comp_view = []
        self._comp_start = None
        self.query_one("#popup").remove_class("show")
        self.query_one("#doc").remove_class("show")
        self.editor.popup_open = False

    def hide_popups(self) -> None:
        self.hide_completion()
        self.query_one("#sig").remove_class("show")

    def request_signature(self) -> None:
        editor = self.editor
        row, col = editor.cursor_location
        self._fetch_signature(editor.text, row + 1, col, row)

    @work(group="sig", exclusive=True)
    @ignore_after_exit
    async def _fetch_signature(self, source: str, line: int, col: int, row: int) -> None:
        sig = await self.completion.request(
            "signature", source=source, line=line, col=col, path=str(self.file_path), timeout=5
        )
        box = self.query_one("#sig", Static)
        if not sig or self.editor.cursor_location[0] != row:
            box.remove_class("show")
            return
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append(sig["name"], style=C.callable)
        t.append("(", style=C.muted)
        for i, p in enumerate(sig["params"]):
            if i:
                t.append(", ", style=C.muted)
            t.append(p, style=Style(color=C.accent, bold=True) if i == sig.get("index") else C.muted)
        t.append(")", style=C.muted)
        cursor = self.editor.cursor_screen_offset
        width = min(t.cell_len + 2, 84, self.size.width - 2)
        box.styles.max_width = width
        x = min(max(0, cursor.x - 4), self.size.width - width - 1)
        y = cursor.y - 1 if cursor.y > 1 else cursor.y + 1
        box.update(t)
        box.styles.offset = (x, y)
        self._sig_row = row
        box.add_class("show")

    # ── lint and format ──────────────────────────────────────────────────────

    def schedule_lint(self, delay: float) -> None:
        self._debounce("lint", delay, self._lint)

    def _lint(self) -> None:
        if self.file_path:
            self._run_lint(self.editor.text, self.file_path)

    @work(group="lint", exclusive=True)
    @ignore_after_exit
    async def _run_lint(self, source: str, path: Path) -> None:
        diags = await lint.check(source, path)
        if source != self.editor.text:
            return
        self.diags = diags
        self.editor.set_diagnostics(diags)
        self._render_status()

    def action_format(self) -> None:
        self.run_worker(self._format(), exclusive=True, group="format")

    async def _format(self) -> None:
        if not self.file_path:
            return
        source = self.editor.text
        formatted = await lint.format_source(source, self.file_path)
        if formatted is None:
            self.notify("Can't format: fix the syntax error first.", severity="warning")
            return
        if formatted != source and self.editor.text == source:
            row, col = self.editor.cursor_location
            self.editor.replace(formatted, (0, 0), self.editor.document.end)
            row = min(row, self.editor.document.line_count - 1)
            self.editor.move_cursor((row, col))

    # ── running ──────────────────────────────────────────────────────────────

    def action_run(self) -> None:
        self._launch("run")

    def action_trace(self) -> None:
        self._launch("trace")

    def action_run_tests(self) -> None:
        self._launch("tests")

    def _launch(self, mode: str) -> None:
        self.hide_popups()
        if not self.save() or not self.file_path:
            return
        self.run_worker(self._start_run(mode), exclusive=True, group="run")

    async def _start_run(self, mode: str = "run") -> None:
        if self.current and not self.current.finished:
            await self.current.stop(grace=0.5)
        if not self.interp:
            self.interp = await asyncio.to_thread(find_interpreter, self.file_path, self.python_override)
        assert self.file_path
        self.close_trace()
        self.output.clear()
        self.error_jump = None
        self.last_error = None
        self.editor.set_error_line(None)
        self._stderr_buffer = None
        self.mode = mode
        argv = None
        self._result_path = None
        if mode in ("trace", "tests"):
            helper = (
                Path(__file__).parent
                / "helpers"
                / ("trace_runner.py" if mode == "trace" else "test_runner.py")
            )
            tmp = data_dir() / "tmp"
            tmp.mkdir(parents=True, exist_ok=True)
            self._result_path = tmp / f"{mode}-{os.getpid()}.json"
            self._result_path.unlink(missing_ok=True)
            argv = [self.interp.executable, "-u", str(helper), str(self._result_path), str(self.file_path)]
        if mode != "tests":
            self.run_count += 1
        self.current = Run(
            self.interp.executable, self.file_path, self._on_run_output, self._on_run_exit, argv=argv
        )
        stdin = self.query_one("#stdin", Input)
        stdin.value = ""
        stdin.add_class("show")
        stdin.focus()  # typing goes to the program while it runs; Esc returns to the editor
        self._stopped = False
        self._note = None
        self._activity = {"run": None, "trace": "recording steps", "tests": "running tests"}[mode]
        self._debouncers["tick"] = self.set_interval(1 / 8, self._render_runhead)
        await self.current.start()
        self._render_runhead()

    def _on_run_output(self, text: str, stream: str) -> None:
        if stream == "stderr":
            if self._stderr_buffer is not None:
                self._stderr_buffer.append(text)
                return
            first = text.lstrip("\n").split("\n", 1)[0]
            if tracebacks.looks_like_error_start(first):
                self._stderr_buffer = [text]
                return
            self.output.write(text, Style(color=C.error, dim=True))
        else:
            self.output.write(text, "")

    def _on_run_exit(self, code: int, seconds: float) -> None:
        if self.mode != "tests":
            self.last_run = (code, seconds)
        timer = self._debouncers.pop("tick", None)
        if timer:
            timer.stop()
        stdin = self.query_one("#stdin", Input)
        if stdin.has_focus:
            self.editor.focus()
        stdin.remove_class("show")
        if self._stopped:
            self._stderr_buffer = None
            self.output.ensure_newline()
            self.output.add_line(Text(f"{G.cross} stopped", style=C.muted))
        elif self._stderr_buffer is not None:
            self._show_error("".join(self._stderr_buffer))
            self._stderr_buffer = None
        elif code not in (0, -1):
            self.output.ensure_newline()
        self._activity = None
        if not self._stopped and self.file_path:
            error_type, concept = self.last_error or (None, None)
            self.stats.record_run(str(self.file_path), error_type, concept)
        if self.mode == "tests" and not self._stopped:
            self._show_tests()
        elif self.mode == "trace" and not self._stopped:
            self._open_trace()
        self._render_runhead()

    # ── tests ────────────────────────────────────────────────────────────────

    def _read_result(self) -> dict | None:
        path = self._result_path
        if not path or not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        finally:
            path.unlink(missing_ok=True)

    def _show_tests(self) -> None:
        data = self._read_result()
        if data is None:
            return  # the file itself failed to load; the error is already shown and explained
        out = self.output
        tests = data.get("tests", [])
        out.ensure_newline()
        if out.has_content:
            out.add_line(Text(""))
        if not tests:
            note = Text()
            note.append(f"{G.dot} ", style=C.muted)
            note.append("no tests", style=C.text)
            self._note = note
            out.add_line(Text("No tests in this file yet.", style=C.text))
            out.add_line(Text(""))
            out.add_line(
                Text("A test is a function whose name starts with test_ and that uses assert:", style=C.muted)
            )
            out.add_line(Text(""))
            for code in ("def test_double():", "    assert double(2) == 4"):
                out.add_line(Text("  " + code, style=C.text))
            out.add_line(Text(""))
            out.add_line(
                Text(
                    'Put code that should only run normally under  if __name__ == "__main__":', style=C.faint
                )
            )
            return
        passed = sum(t["status"] == "pass" for t in tests)
        failed = len(tests) - passed
        note = Text()
        note.append(f"{G.dot if not failed else G.cross} ", style=C.ok if not failed else C.error)
        note.append("tests", style=C.text)
        note.append(f"   {passed} passed", style=C.muted)
        if failed:
            note.append(f" · {failed} failed", style=C.error)
        note.append(f"   {data.get('seconds', 0):.2f}s", style=C.muted)
        self._note = note
        bar_w = max(10, out.scrollable_content_region.width - 3)
        filled = round(bar_w * passed / len(tests))
        bar = Text()
        bar.append("━" * filled, style=C.ok)
        bar.append("━" * (bar_w - filled), style=C.error if failed else C.surface)
        out.add_line(bar)
        out.add_line(Text(""))
        first_fail = None
        for t in tests:
            row = Text()
            ok = t["status"] == "pass"
            row.append(f"{G.dot} " if ok else f"{G.cross} ", style=C.ok if ok else C.error)
            row.append(t["name"], style=C.text if ok else Style(color=C.text, bold=True))
            out.add_line(row, jump=t.get("line"))
            if ok:
                continue
            first_fail = first_fail or t.get("line")
            if "expected" in t and t.get("op") == "Eq":
                for label, key, color in (("expected", "expected", C.ok), ("got", "got", C.error)):
                    line = Text(f"    {label:<9} ", style=C.muted)
                    line.append(t[key], style=color)
                    out.add_line(line)
            elif "expected" in t:
                line = Text("    ", style=C.muted)
                line.append(t["got"], style=C.error)
                line.append(f"  {t['op']}  ", style=C.faint)
                line.append(t["expected"], style=C.text)
                line.append("  was False", style=C.muted)
                out.add_line(line)
            elif t.get("message"):
                out.add_line(
                    Text("    " + t["message"], style=C.error if t["status"] == "error" else C.muted)
                )
            loc = Text("    ")
            loc.append(
                f"{self.file_path.name if self.file_path else ''}:{t.get('line')}",
                style=Style(color=C.accent, underline=True),
            )
            out.add_line(loc, jump=t.get("line"))
        if first_fail:
            self.error_jump = first_fail
            self.editor.set_error_line(first_fail - 1)

    # ── watch it run ─────────────────────────────────────────────────────────

    def _open_trace(self) -> None:
        data = self._read_result()
        if not data or not data.get("steps"):
            return
        trace = Trace.from_json(data, self.editor.text)
        view = self.query_one(TraceView)
        self.output.display = False
        view.add_class("show")
        view.load(trace, self.editor.text)
        view.focus()

    def close_trace(self) -> None:
        view = self.query_one(TraceView)
        if not view.has_class("show"):
            return
        view.remove_class("show")
        self.output.display = True
        self.editor.set_trace_line(None)
        if view.has_focus:
            self.editor.focus()
        self._render_runhead()

    @on(TraceView.Moved)
    def _trace_moved(self, event: TraceView.Moved) -> None:
        view = self.query_one(TraceView)
        if not view.trace:
            return
        row = view.trace.steps[event.index]["l"] - 1
        editor = self.editor
        editor.set_trace_line(row)
        row = max(0, min(row, editor.document.line_count - 1))
        text = editor.document[row]
        editor.move_cursor((row, len(text) - len(text.lstrip())), center=True)
        self._render_runhead()

    @on(TraceView.Closed)
    def _trace_closed(self) -> None:
        self.close_trace()

    def _show_error(self, raw: str) -> None:
        out = self.output
        assert self.file_path
        err = tracebacks.parse(raw)
        if err is None:
            out.write(raw, Style(color=C.error))
            return
        out.ensure_newline()
        if out.has_content:
            out.add_line(Text(""))
        exc = err.exception
        name, sep, msg = exc.partition(":")
        head = Text()
        head.append(f"{G.cross} ", style=C.error)
        head.append(name, style=Style(color=C.error, bold=True))
        if sep:
            head.append(":" + msg, style=C.text)
        out.add_line(head)
        for extra in err.message[1:]:
            out.add_line(Text("  " + extra, style=C.muted))
        out.add_line(Text(""))
        frames = err.frames
        user = [f for f in frames if tracebacks.is_user_frame(f, self.file_path)]
        hidden = len(frames) - len(user)
        for frame in user[-4:]:
            loc = Text()
            loc.append(f"{Path(frame.file).name}:{frame.line}", style=Style(color=C.accent, underline=True))
            if frame.func:
                loc.append(f"  in {frame.func}", style=C.muted)
            same_file = _same_file(frame.file, self.file_path)
            out.add_line(loc, jump=frame.line if same_file else None)
            for i, code_line in enumerate(frame.code):
                marker = i > 0 and set(code_line.strip()) <= set("^~ ")
                out.add_line(Text("  " + code_line, style=C.error if marker else C.text))
        if hidden:
            out.add_line(Text(f"+ {hidden} library frame{'s' if hidden != 1 else ''} hidden", style=C.faint))
        self.error_jump = tracebacks.jump_target(err, self.file_path)
        note = explain.explain(err, self.file_path, self.editor.text)
        self.last_error = (err.exception.partition(":")[0].rsplit(".", 1)[-1], note.review if note else "")
        if note:
            self._render_explanation(note)
        if self.error_jump:
            out.add_line(Text(""))
            hint = Text()
            hint.append("^E", style=C.text)
            hint.append(f"  jump to line {self.error_jump}", style=C.muted)
            out.add_line(hint, jump=self.error_jump)
            self.editor.set_error_line(self.error_jump - 1)

    def _render_explanation(self, note: explain.Explanation) -> None:
        out = self.output
        out.add_line(Text(""))
        out.add_line(Text("─" * 40, style=C.surface))
        out.add_line(Text("What it means", style=C.accent))
        out.add_line(Text(note.meaning, style=C.muted))
        if note.tries:
            out.add_line(Text(""))
            out.add_line(Text("Try", style=C.accent))
            width = max(len(code) for code, _ in note.tries)
            pane = max(20, out.scrollable_content_region.width - 2)
            side_by_side = all(width + 5 + len(hint) <= pane for _, hint in note.tries)
            for code, hint in note.tries:
                line = Text("  ")
                line.append(code, style=C.text)
                if hint and side_by_side:
                    line.append(" " * (width - len(code) + 3) + hint, style=C.faint)
                out.add_line(line)
                if hint and not side_by_side:
                    out.add_line(Text("    " + hint, style=C.faint))

    @on(Input.Submitted, "#stdin")
    def _send_input(self, event: Input.Submitted) -> None:
        if self.current and not self.current.finished:
            self.output.write(event.value + "\n", Style(color=C.accent))
            self.current.send_input(event.value + "\n")
        event.input.value = ""

    @on(OutputLog.Jump)
    def _jump(self, event: OutputLog.Jump) -> None:
        self._jump_to(event.line)

    def action_jump_error(self) -> None:
        if self.error_jump:
            self._jump_to(self.error_jump)

    def _jump_to(self, line: int) -> None:
        editor = self.editor
        row = max(0, min(line - 1, editor.document.line_count - 1))
        text = editor.document[row]
        editor.move_cursor((row, len(text) - len(text.lstrip())), center=True)
        editor.focus()

    def action_stop(self) -> None:
        if self.current and not self.current.finished:
            self._stopped = True
            self.run_worker(self.current.stop(), group="stop")

    def action_ctrl_c(self) -> None:
        running = self.current is not None and not self.current.finished
        focused = self.focused
        if isinstance(focused, CodeEditor) and not focused.selection.is_empty:
            focused.action_copy()
            return
        if running:
            self.action_stop()
        elif isinstance(focused, Input) and focused.selected_text:
            self.copy_to_clipboard(focused.selected_text)

    def action_clear_output(self) -> None:
        self.output.clear()

    def on_key(self, event) -> None:
        if event.key == "ctrl+d" and isinstance(self.focused, Input) and self.focused.id == "stdin":
            if self.current:
                self.current.close_input()
            event.stop()
        elif event.key == "escape" and isinstance(self.focused, Input):
            self.editor.focus()

    # ── commands ─────────────────────────────────────────────────────────────

    def action_command_palette(self) -> None:
        if not CommandPalette.is_open(self):
            self.push_screen(Palette(id="--command-palette", placeholder="Run a command…"))

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield SystemCommand("Run", "Save and run this file  (Ctrl+R)", self.action_run)
        yield SystemCommand("Watch it run", "Step through your code line by line  (F6)", self.action_trace)
        yield SystemCommand(
            "Run tests", "Run every test_ function in this file  (Ctrl+T)", self.action_run_tests
        )
        yield SystemCommand(
            "Your progress", "Streak, runs, time and common errors  (Ctrl+G)", self.action_progress
        )
        yield SystemCommand("Stop", "Stop the running program  (Ctrl+C)", self.action_stop)
        yield SystemCommand("Open file", "Open a file in this folder  (Ctrl+P)", self.action_open)
        yield SystemCommand("Close file", "Close the file in focus  (Ctrl+W)", self.action_close_tab)
        yield SystemCommand(
            "Next file", "Focus the next open file  (Ctrl+PgDn or Alt+→)", self.action_next_tab
        )
        yield SystemCommand(
            "Previous file", "Focus the previous open file  (Ctrl+PgUp or Alt+←)", self.action_prev_tab
        )
        yield SystemCommand(
            "New scratch file", "Start a fresh scratch file  (Ctrl+N)", self.action_new_scratch
        )
        yield SystemCommand(
            "Install a package",
            "pip install into this folder's .venv, e.g. requests",
            self.action_install_package,
        )
        yield SystemCommand(
            "How to install packages",
            "Show the steps, also for doing it in PowerShell",
            self.action_package_help,
        )
        yield SystemCommand("Format file", "Format with ruff  (Alt+F)", self.action_format)
        yield SystemCommand("Jump to error", "Cursor to the failing line  (Ctrl+E)", self.action_jump_error)
        yield SystemCommand("Clear output", "Empty the output pane  (Ctrl+L)", self.action_clear_output)
        yield SystemCommand(
            "Toggle layout", "Output beside or below the editor  (Ctrl+B)", self.action_toggle_layout
        )
        yield SystemCommand("Save", "Save now (autosave is on)  (Ctrl+S)", self.action_save)
        yield SystemCommand("Quit", "Save and quit  (Ctrl+Q)", self.action_quit)

    # ── packages ─────────────────────────────────────────────────────────────

    def action_install_package(self) -> None:
        self.push_screen(PackagePrompt(), self._on_package_names)

    def _on_package_names(self, text: str | None) -> None:
        if not text:
            return
        good, bad = packages.parse_packages(text)
        if bad:
            self.notify(f"Not a package name: {' '.join(bad)}", severity="warning")
        if good:
            self.run_worker(self._install(good), exclusive=True, group="run")

    async def _install(self, names: list[str]) -> None:
        if self.current and not self.current.finished:
            await self.current.stop(grace=0.5)
        if not self.file_path:
            return
        self.save()
        folder = self.file_path.parent
        interp = await asyncio.to_thread(find_interpreter, self.file_path, self.python_override)
        plan = packages.plan(folder, interp, names)
        out = self.output
        out.clear()
        label = " ".join(names)
        head = Text()
        head.append("Installing ", style=C.muted)
        head.append(label, style=C.text)
        head.append(f"  into {plan.where}", style=C.muted)
        out.add_line(head)
        if plan.creates_venv:
            out.add_line(
                Text(
                    f"Creating {folder.name}{os.sep}.venv first, so packages stay with this project.",
                    style=C.faint,
                )
            )
        out.add_line(Text(""))
        self._note = None
        self._stopped = False
        self._debouncers["tick"] = self.set_interval(1 / 8, self._render_runhead)
        code = 0
        for step in plan.steps:
            self._activity = f"installing {label}" if "install" in step else "creating .venv"
            code = await self._run_command(step, folder)
            if code != 0 or self._stopped:
                break
        timer = self._debouncers.pop("tick", None)
        if timer:
            timer.stop()
        self._activity = None
        note = Text()
        out.ensure_newline()
        out.add_line(Text(""))
        if self._stopped:
            note.append(f"{G.cross} install stopped", style=C.muted)
        elif code == 0:
            note.append(f"{G.dot} ", style=C.ok)
            note.append(f"installed {label}", style=C.text)
            done = Text()
            done.append(f"{G.dot} ", style=C.ok)
            done.append(f"{label} is ready to import.", style=C.text)
            out.add_line(done)
            # switch to the (possibly new) .venv: status bar and suggestions follow it
            self.interp = None
            self.py_version = None
            self.detect_interpreter()
        else:
            note.append(f"{G.cross} install failed", style=C.error)
            out.add_line(
                Text(
                    f"{G.cross} Install failed. Check the package name and your internet connection.",
                    style=C.error,
                )
            )
        self._note = note
        self._render_runhead()

    async def _run_command(self, argv: list[str], cwd: Path) -> int:
        loop = asyncio.get_running_loop()
        done: asyncio.Future[int] = loop.create_future()

        def on_output(text: str, stream: str) -> None:
            self.output.write(text, Style(color=C.muted))

        def on_exit(code: int, seconds: float) -> None:
            if not done.done():
                done.set_result(code)

        assert self.file_path
        self.current = Run(argv[0], self.file_path, on_output, on_exit, argv=argv, cwd=cwd)
        await self.current.start()
        return await done

    def action_package_help(self) -> None:
        out = self.output
        out.clear()
        folder = self.file_path.parent if self.file_path else Path.cwd()

        def line(*parts: tuple[str, str]) -> None:
            t = Text()
            for text, style in parts:
                t.append(text, style=style)
            out.add_line(t)

        line(("Installing packages", C.text))
        line(("", ""))
        line(("From pytobs", C.accent))
        line(("  Ctrl+K", C.text), ("  then  ", C.muted), ("Install a package", C.text))
        line(("  type a name like ", C.muted), ("requests", C.text), (" and press Enter", C.muted))
        line(("", ""))
        line(("From PowerShell, in your project folder", C.accent))
        line(("  cd ", C.muted), (str(folder), C.text))
        line(("  uv venv", C.text), ("              once per project", C.faint))
        line(("  uv pip install requests", C.text))
        line(("", ""))
        line(
            ("Either way the packages go into ", C.muted),
            (".venv", C.text),
            (" next to your files.", C.muted),
        )
        line(("pytobs uses that .venv automatically: see the status bar.", C.muted))
        self._note = None
        self._render_runhead()

    async def on_unmount(self) -> None:
        self.stats.save()
        await self.completion.close()

    def action_progress(self) -> None:
        self.stats.save()
        self.push_screen(ProgressScreen(self.stats))

    async def action_quit(self) -> None:
        self.stats.save()
        self.save()
        self.remember_cursor()
        if self.current and not self.current.finished:
            await self.current.stop(grace=0.3)
        await self.completion.close()
        self.exit()

    # ── utilities ────────────────────────────────────────────────────────────

    def _debounce(self, name: str, delay: float, callback) -> None:
        timer = self._debouncers.pop(name, None)
        if timer:
            timer.stop()
        self._debouncers[name] = self.set_timer(delay, callback)


HEAT_SHADES = ["#363646", "#3A4A6B", "#4E6699", "#6683BF", C.accent]


class ProgressScreen(ModalScreen[None]):
    """Streak, runs, coding time, an activity grid and the errors met most."""

    DEFAULT_CSS = f"""
    ProgressScreen {{ background: {C.base} 55%; align: center top; }}
    ProgressScreen > Static {{
        width: auto; max-width: 96%; height: auto; max-height: 96%; margin-top: 2;
        background: {C.surface}; padding: 1 3;
    }}
    """
    BINDINGS = [Binding("escape,q,ctrl+g", "dismiss", "Close", show=False)]

    def __init__(self, stats: Stats) -> None:
        super().__init__()
        self.stats = stats

    def compose(self) -> ComposeResult:
        yield Static(self._content())

    def _content(self) -> Text:
        s = self.stats.summary()
        out = Text()
        out.append("Your progress", style=Style(color=C.text, bold=True))
        out.append(f"    last {s.weeks} weeks\n\n", style=C.muted)
        numbers = [
            (str(s.streak), "day streak" if s.streak != 1 else "day streak"),
            (str(s.runs_week), "runs this week"),
            (fmt_duration(s.seconds_week), "coding this week"),
            (str(s.fixed_total), "errors fixed"),
        ]
        for value, _ in numbers:
            out.append(f"{value:<18}", style=Style(color=C.text, bold=True))
        out.append("\n")
        for _, label in numbers:
            out.append(f"{label:<18}", style=C.muted)
        out.append("\n\n")
        days = ["Mon", "   ", "Wed", "   ", "Fri", "   ", "Sun"]
        for d in range(7):
            out.append(f"{days[d]}  ", style=C.faint)
            for runs in s.heat[d]:
                out.append("■ ", style=Style(color=HEAT_SHADES[level(runs)]))
            out.append("\n")
        out.append("     less ", style=C.faint)
        for shade in HEAT_SHADES:
            out.append("■ ", style=Style(color=shade))
        out.append("more", style=C.faint)
        out.append("\n\n")
        out.append("Errors you meet most", style=Style(color=C.text, bold=True))
        if not s.top_errors:
            out.append("\n\n")
            out.append("None yet. Errors you hit will show here with the concept to review.", style=C.muted)
        else:
            out.append("    and what to review\n", style=C.muted)
            most = s.top_errors[0][1]
            for i, (name, count, concept) in enumerate(s.top_errors):
                bar = max(1, round(20 * count / most))
                out.append(f"\n{name[:18]:<20}", style=C.text)
                out.append("━" * bar, style=C.error if i == 0 else C.muted)
                out.append(" " * (21 - bar))
                out.append(f"{count:<5}", style=C.text)
                out.append(concept, style=C.faint)
        out.append("\n\n")
        out.append("Esc close   ", style=C.faint)
        out.append("Counted on this computer only.", style=C.faint)
        return out


class PackagePrompt(ModalScreen[str | None]):
    """Ask which packages to install."""

    DEFAULT_CSS = f"""
    PackagePrompt {{ background: {C.base} 55%; align-horizontal: center; }}
    PackagePrompt > Vertical {{
        width: 64; max-width: 92%; height: auto; margin-top: 3; background: {C.surface}; padding: 1 2;
    }}
    PackagePrompt #title {{ color: {C.text}; height: 1; }}
    PackagePrompt #hint {{ color: {C.muted}; height: 1; margin-bottom: 1; }}
    PackagePrompt Input, PackagePrompt Input:focus {{
        border: none; background: {C.overlay}; color: {C.text}; padding: 0 1; height: 1;
    }}
    PackagePrompt #keys {{ color: {C.faint}; height: 1; margin-top: 1; }}
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Install a package", id="title")
            yield Static("Goes into this folder's .venv. Separate names with spaces.", id="hint")
            yield Input(placeholder="requests", id="packages")
            yield Static("Enter install   Esc cancel", id="keys")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Palette(CommandPalette):
    """The command palette, restyled as a compact floating panel."""

    DEFAULT_CSS = f"""
    Palette {{ background: {C.base} 55%; }}
    Palette > Vertical {{ width: 76; max-width: 92%; margin-top: 3; }}
    Palette #--input {{ border: none; background: {C.surface}; padding: 0 1; height: 3; }}
    Palette #--input.--list-visible {{ border: none; }}
    Palette SearchIcon {{ color: {C.accent}; margin: 1 0 0 1; width: 2; }}
    Palette CommandInput, Palette CommandInput:focus {{
        border: none; background: {C.surface}; padding: 1 1 1 0; height: 3;
    }}
    Palette CommandList, Palette CommandList:focus {{
        border: none; background: {C.surface}; padding: 0 0 1 0; max-height: 18;
    }}
    Palette CommandList > .option-list--option {{ padding: 0 2; }}
    Palette CommandList > .option-list--option-highlighted {{ background: {C.overlay}; }}
    Palette > .command-palette--help-text {{ color: {C.muted}; text-style: not bold; }}
    Palette > .command-palette--highlight {{ color: {C.accent}; text-style: bold; }}
    """

    def on_mount(self) -> None:
        self.query_one(SearchIcon).icon = G.chevron


def _palette(providers, placeholder: str) -> Palette:
    return Palette(providers=providers, placeholder=placeholder)


def _same_file(a: str, b: Path) -> bool:
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return False


def _fmt_seconds(seconds: float) -> str:
    if seconds < 10:
        return f"{seconds:.2f}s"
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"
