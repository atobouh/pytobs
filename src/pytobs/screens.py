"""Small dialogs and panels: name prompts, the outline, help cards, find bar, file sidebar."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Input, OptionList, Static
from textual.widgets.option_list import Option

from .theme import C

SKIP_NAMES = {"__pycache__", "node_modules", "venv", "env", "site-packages", "dist", "build"}

_CARD = f"""
    background: {C.base} 55%; align-horizontal: center;
"""
_PANEL = f"""
    width: 64; max-width: 92%; height: auto; margin-top: 3; background: {C.surface}; padding: 1 2;
"""


class TextPrompt(ModalScreen[str | None]):
    """Ask for one line of text: a file name, a new variable name."""

    DEFAULT_CSS = f"""
    TextPrompt {{ {_CARD} }}
    TextPrompt > Vertical {{ {_PANEL} }}
    TextPrompt #title {{ color: {C.text}; height: 1; }}
    TextPrompt #hint {{ color: {C.muted}; height: auto; margin-bottom: 1; }}
    TextPrompt Input, TextPrompt Input:focus {{
        border: none; background: {C.overlay}; color: {C.text}; padding: 0 1; height: 1;
    }}
    TextPrompt #keys {{ color: {C.faint}; height: 1; margin-top: 1; }}
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, title: str, hint: str, value: str = "", placeholder: str = "", ok: str = "OK") -> None:
        super().__init__()
        self._title, self._hint, self._value, self._placeholder, self._ok = (
            title,
            hint,
            value,
            placeholder,
            ok,
        )

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._title, id="title")
            yield Static(self._hint, id="hint")
            yield Input(value=self._value, placeholder=self._placeholder, id="answer")
            yield Static(f"Enter {self._ok}   Esc cancel", id="keys")

    def on_mount(self) -> None:
        field = self.query_one(Input)
        stem = Path(self._value).stem if "." in self._value else self._value
        field.selection = (0, len(stem)) if stem else field.selection  # type over the name, keep .py

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmPrompt(ModalScreen[bool]):
    DEFAULT_CSS = f"""
    ConfirmPrompt {{ {_CARD} }}
    ConfirmPrompt > Vertical {{ {_PANEL} }}
    ConfirmPrompt #title {{ color: {C.text}; height: auto; }}
    ConfirmPrompt #keys {{ color: {C.faint}; height: 1; margin-top: 1; }}
    """
    BINDINGS = [
        Binding("enter,y", "answer(True)", show=False),
        Binding("escape,n", "answer(False)", show=False),
    ]

    def __init__(self, question: str, ok: str) -> None:
        super().__init__()
        self._question, self._ok = question, ok

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._question, id="title")
            yield Static(f"Enter {self._ok}   Esc keep it", id="keys")

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)


class OutlineScreen(ModalScreen[int | None]):
    """Functions and classes in this file. Type to filter, :42 to go to line 42."""

    DEFAULT_CSS = f"""
    OutlineScreen {{ {_CARD} }}
    OutlineScreen > Vertical {{ width: 72; max-width: 92%; height: auto; margin-top: 3; background: {C.surface}; padding: 1 2; }}
    OutlineScreen Input, OutlineScreen Input:focus {{
        border: none; background: {C.overlay}; color: {C.text}; padding: 0 1; height: 1; margin-bottom: 1;
    }}
    OutlineScreen OptionList, OutlineScreen OptionList:focus {{
        border: none; background: {C.surface}; max-height: 18; padding: 0;
    }}
    OutlineScreen OptionList > .option-list--option-highlighted {{ background: {C.overlay}; }}
    OutlineScreen #keys {{ color: {C.faint}; height: 1; margin-top: 1; }}
    """
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, items: list[tuple[int, int, str, str]], current_row: int, line_count: int) -> None:
        super().__init__()
        self.items = items
        self.current_row = current_row
        self.line_count = line_count
        self._rows: list[int] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Input(placeholder="filter functions and classes   ·   :42 goes to line 42")
            yield OptionList()
            yield Static("↑↓ choose   Enter jump   Esc close", id="keys")

    def on_mount(self) -> None:
        self._fill("")
        here = [i for i, row in enumerate(self._rows) if row <= self.current_row]
        if here:
            self.query_one(OptionList).highlighted = here[-1]

    def _fill(self, query: str) -> None:
        options = self.query_one(OptionList)
        options.clear_options()
        self._rows = []
        q = query.strip().lower()
        if q.startswith(":"):
            digits = q[1:].strip()
            if digits.isdigit():
                line = max(1, min(int(digits), self.line_count))
                options.add_option(Option(Text.assemble(("Go to line ", C.muted), (str(line), C.text))))
                self._rows.append(line - 1)
                options.highlighted = 0
            return
        for row, depth, kind, label in self.items:
            if q and q not in label.lower():
                continue
            t = Text("  " * depth)
            t.append("ƒ " if kind == "def" else "c ", style=C.accent if kind == "def" else C.keyword)
            t.append(label, style=C.text)
            t.append(f"   {row + 1}", style=C.faint)
            options.add_option(Option(t))
            self._rows.append(row)
        if not self._rows:
            hint = "No functions or classes yet." if not q else "Nothing matches."
            options.add_option(Option(Text(hint, style=C.muted), disabled=True))
        else:
            options.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        self._fill(event.value)

    def on_key(self, event: events.Key) -> None:
        options = self.query_one(OptionList)
        if event.key in ("up", "down", "pageup", "pagedown"):
            event.stop()
            {
                "up": options.action_cursor_up,
                "down": options.action_cursor_down,
                "pageup": options.action_page_up,
                "pagedown": options.action_page_down,
            }[event.key]()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        index = self.query_one(OptionList).highlighted
        self.dismiss(self._rows[index] if index is not None and index < len(self._rows) else None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_index < len(self._rows):
            self.dismiss(self._rows[event.option_index])

    def action_cancel(self) -> None:
        self.dismiss(None)


class HelpCard(ModalScreen[None]):
    """Plain-English help for the word under the cursor (F1)."""

    DEFAULT_CSS = f"""
    HelpCard {{ {_CARD} }}
    HelpCard > Vertical {{ width: 76; max-width: 92%; height: auto; max-height: 80%; margin-top: 3;
        background: {C.surface}; padding: 1 2; overflow-y: auto; }}
    """

    def __init__(self, body: Text) -> None:
        super().__init__()
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.body)

    def on_key(self, event: events.Key) -> None:
        event.stop()
        self.dismiss(None)

    def on_click(self) -> None:
        self.dismiss(None)


class FindBar(Horizontal):
    """Find and replace, under the editor."""

    DEFAULT_CSS = f"""
    FindBar {{ height: 1; display: none; background: {C.surface}; margin-top: 1; }}
    FindBar.show {{ display: block; }}
    FindBar Input, FindBar Input:focus {{
        border: none; height: 1; padding: 0 1; background: {C.overlay}; color: {C.text}; width: 1fr;
    }}
    FindBar .label {{ width: auto; color: {C.muted}; padding: 0 1; }}
    FindBar #findinfo {{ width: auto; min-width: 12; color: {C.muted}; padding: 0 1; }}
    """

    def compose(self) -> ComposeResult:
        yield Static("find", classes="label")
        yield Input(placeholder="text", id="find")
        yield Static("replace", classes="label")
        yield Input(placeholder="with", id="replace")
        yield Static("", id="findinfo")


class FileTree(DirectoryTree):
    """The files sidebar (Alt+E)."""

    ICON_NODE = "▸ "
    ICON_NODE_EXPANDED = "▾ "
    ICON_FILE = "  "

    DEFAULT_CSS = f"""
    FileTree {{ width: 30; background: {C.mantle}; color: {C.text}; padding: 1 1; scrollbar-size-vertical: 1; }}
    FileTree:focus .tree--cursor {{ background: {C.overlay}; }}
    FileTree .tree--cursor {{ background: {C.surface}; }}
    FileTree .directory-tree--folder {{ color: {C.accent}; text-style: none; }}
    FileTree .directory-tree--extension {{ color: {C.muted}; text-style: none; }}
    FileTree .directory-tree--hidden {{ color: {C.faint}; }}
    """
    BINDINGS = [
        Binding("n", "act('new')", "New file", show=False),
        Binding("f", "act('folder')", "New folder", show=False),
        Binding("r,f2", "act('rename')", "Rename", show=False),
        Binding("delete", "act('delete')", "Delete", show=False),
    ]

    class Act(Message):
        def __init__(self, what: str, path: Path) -> None:
            super().__init__()
            self.what = what
            self.path = path

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [
            p
            for p in paths
            if not p.name.startswith(".") and p.name not in SKIP_NAMES and not p.name.endswith(".pytobs-tmp")
        ]

    def selected_path(self) -> Path:
        node = self.cursor_node
        if node is None or node.data is None:
            return Path(self.path)
        return Path(node.data.path)

    def action_act(self, what: str) -> None:
        self.post_message(self.Act(what, self.selected_path()))
