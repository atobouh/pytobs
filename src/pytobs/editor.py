"""The code editor: Textual's TextArea with Python-aware editing and fast highlighting."""

from __future__ import annotations

import re
from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.strip import Strip
from textual.widgets import TextArea

from .lint import Diagnostic
from .theme import EDITOR_THEME, C, G

PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
CLOSERS = {")", "]", "}"}
DEDENT_RE = re.compile(r"^\s*(return|pass|break|continue|raise)\b")
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
INDENT = 4


class CodeEditor(TextArea):
    """TextArea plus auto-indent, bracket pairs, comment toggle, diagnostics markers
    and highlighting limited to the visible window (keeps typing fast in long files)."""

    BINDINGS = [
        Binding("ctrl+slash,ctrl+underscore", "toggle_comment", "Comment", show=False),
        Binding("shift+tab", "dedent", "Dedent", show=False),
        Binding("ctrl+d", "duplicate_line", "Duplicate line", show=False),
    ]

    class Typed(Message):
        """A printable character was inserted (drives completion)."""

        def __init__(self, editor: CodeEditor, char: str) -> None:
            super().__init__()
            self.editor = editor
            self.char = char

    class PopupKey(Message):
        """A navigation key pressed while a popup is open."""

        def __init__(self, key: str) -> None:
            super().__init__()
            self.key = key

    def __init__(self, text: str = "", **kwargs) -> None:
        # The language is attached after the first paint (see enable_highlighting): preparing
        # the tree-sitter query is the slowest part of startup.
        super().__init__(
            text,
            language=None,
            soft_wrap=False,
            tab_behavior="indent",
            show_line_numbers=True,
            **kwargs,
        )
        self.register_theme(EDITOR_THEME)
        self.theme = "sumi"
        self.cursor_blink = False
        self.indent_width = INDENT
        self.diagnostics: dict[int, Diagnostic] = {}
        self.error_line: int | None = None  # 0-based line of the last run's error
        self.popup_open = False

    # ── rendering ────────────────────────────────────────────────────────────

    @property
    def gutter_width(self) -> int:
        # one extra column on the left for the diagnostic marker
        return super().gutter_width + 1 if self.show_line_numbers else 0

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        if not self.show_line_numbers:
            return strip
        row = y + int(self.scroll_offset.y)
        marker = None
        if row == self.error_line:
            marker = Style(color=C.error, bgcolor=C.base)
        elif row in self.diagnostics:
            diag = self.diagnostics[row]
            marker = Style(color=C.error if diag.error else C.warn, bgcolor=C.base)
        if marker is None:
            return strip
        rest = strip.crop(1, strip.cell_length)
        return Strip.join([Strip([Segment(G.dot, marker)], 1), rest])

    def _build_highlight_map(self) -> None:
        """Query tree-sitter only for the visible window plus one screen either side."""
        self._line_cache.clear()
        highlights = self._highlights
        highlights.clear()
        if not self._highlight_query:
            return
        top = int(self.scroll_offset.y)
        height = max(self.size.height, 40)
        lo, hi = max(0, top - height), top + 2 * height
        captures = self.document.query_syntax_tree(self._highlight_query, (lo, 0), (hi, 0))
        for name, nodes in captures.items():
            for node in nodes:
                (sr, sc), (er, ec) = node.start_point, node.end_point
                if sr == er:
                    highlights[sr].append((sc, ec, name))
                else:
                    highlights[sr].append((sc, None, name))
                    for row in range(max(sr + 1, lo), min(er, hi)):
                        highlights[row].append((0, None, name))
                    highlights[er].append((0, ec, name))

    def watch_scroll_y(self, old: float, new: float) -> None:
        super().watch_scroll_y(old, new)
        if int(old) != int(new):
            self._build_highlight_map()

    def enable_highlighting(self) -> None:
        if self.language == "python":
            return
        selection = self.selection
        scroll = self.scroll_offset
        self.language = "python"
        self.selection = selection
        self.scroll_to(scroll.x, scroll.y, animate=False, immediate=True)

    def set_diagnostics(self, diags: list[Diagnostic]) -> None:
        self.diagnostics = {}
        for d in diags:
            self.diagnostics.setdefault(d.row, d)
        self._line_cache.clear()
        self.refresh()

    def set_error_line(self, row: int | None) -> None:
        self.error_line = row
        self._line_cache.clear()
        self.refresh()

    # ── helpers ──────────────────────────────────────────────────────────────

    def current_word(self) -> tuple[str, tuple[int, int]]:
        row, col = self.cursor_location
        before = self.document[row][:col]
        m = WORD_RE.search(before)
        word = m.group(0) if m else ""
        return word, (row, col - len(word))

    def _in_string_or_comment(self) -> bool:
        row, col = self.cursor_location
        line = self.document[row][:col]
        quote = None
        for ch in line:
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "#":
                return True
        return quote is not None

    # ── keys ─────────────────────────────────────────────────────────────────

    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        if self.popup_open and key in ("up", "down", "tab", "enter", "escape", "pageup", "pagedown"):
            event.stop()
            event.prevent_default()
            self.post_message(self.PopupKey(key))
            return
        if key == "escape":
            event.stop()
            event.prevent_default()
            self.post_message(self.PopupKey("escape"))
            return
        if self.read_only:
            return
        if key == "enter":
            event.stop()
            event.prevent_default()
            self._newline()
            return
        char = event.character
        if event.is_printable and char:
            if self._handle_pair(char):
                event.stop()
                event.prevent_default()
                self.post_message(self.Typed(self, char))
                return
            await super()._on_key(event)
            self.post_message(self.Typed(self, char))
            return
        await super()._on_key(event)

    def _newline(self) -> None:
        row, col = self.cursor_location
        line = self.document[row]
        before, after = line[:col], line[col:]
        indent = len(before) - len(before.lstrip(" "))
        indent = min(indent, len(before))
        stripped = before.rstrip()
        if stripped.endswith(":") and not self._in_string_or_comment():
            indent += INDENT
        elif stripped.endswith(("(", "[", "{")):
            indent += INDENT
        elif DEDENT_RE.match(before) and not after.strip():
            indent = max(0, indent - INDENT)
        text = "\n" + " " * indent
        start, end = self.selection
        # Between a bracket pair: put the closer on its own line.
        if stripped.endswith(("(", "[", "{")) and after[:1] in CLOSERS and self.selection.is_empty:
            closer_indent = " " * max(0, indent - INDENT)
            self._replace_via_keyboard(text + "\n" + closer_indent, start, end)
            self.move_cursor((row + 1, indent))
            return
        self._replace_via_keyboard(text, start, end)

    def _handle_pair(self, char: str) -> bool:
        """Auto-close brackets and quotes, and type over closers. True if handled."""
        if not self.selection.is_empty:
            if char in PAIRS:
                start, end = sorted(self.selection)
                selected = self.selected_text
                self._replace_via_keyboard(char + selected + PAIRS[char], start, end)
                return True
            return False
        row, col = self.cursor_location
        line = self.document[row]
        nxt = line[col : col + 1]
        prev = line[col - 1 : col] if col else ""
        if char in CLOSERS or char in "\"'":
            if nxt == char and (char in CLOSERS or self._in_string_or_comment()):
                self.move_cursor((row, col + 1))
                return True
        if char in PAIRS and not self._in_string_or_comment():
            if char in "\"'":
                # don't pair after a letter (prefixes like f" are fine) or inside words
                if prev.isalnum() and prev not in ("f", "r", "b", "u", "F", "R", "B", "U"):
                    return False
                if nxt and (nxt.isalnum() or nxt == "_"):
                    return False
            elif nxt and (nxt.isalnum() or nxt == "_"):
                return False
            self._replace_via_keyboard(char + PAIRS[char], (row, col), (row, col))
            self.move_cursor((row, col + 1))
            return True
        return False

    def action_delete_left(self) -> None:
        if self.read_only:
            return
        if self.selection.is_empty:
            row, col = self.cursor_location
            line = self.document[row]
            before = line[:col]
            # delete an empty pair in one go: (|)
            if col and line[col - 1 : col] in PAIRS and line[col : col + 1] == PAIRS[line[col - 1]]:
                self._delete_via_keyboard((row, col - 1), (row, col + 1))
                return
            # in leading whitespace, go back to the previous indent stop
            if before and not before.strip():
                stop = ((col - 1) // INDENT) * INDENT
                self._delete_via_keyboard((row, stop), (row, col))
                return
        super().action_delete_left()

    def _selected_rows(self) -> range:
        (r1, _), (r2, c2) = sorted(self.selection)
        if r2 > r1 and c2 == 0:
            r2 -= 1
        return range(r1, r2 + 1)

    def action_toggle_comment(self) -> None:
        rows = self._selected_rows()
        lines = [self.document[r] for r in rows]
        code = [line for line in lines if line.strip()]
        if not code:
            return
        indent = min(len(line) - len(line.lstrip()) for line in code)
        uncomment = all(line.lstrip().startswith("#") for line in code)
        new = []
        for line in lines:
            if not line.strip():
                new.append(line)
            elif uncomment:
                i = line.index("#")
                rest = line[i + 1 :]
                new.append(line[:i] + (rest[1:] if rest.startswith(" ") else rest))
            else:
                new.append(line[:indent] + "# " + line[indent:])
        self._replace_rows(rows, new)

    def action_dedent(self) -> None:
        rows = self._selected_rows()
        new = []
        for r in rows:
            line = self.document[r]
            strip = min(INDENT, len(line) - len(line.lstrip(" ")))
            new.append(line[strip:])
        self._replace_rows(rows, new)

    def action_duplicate_line(self) -> None:
        row, col = self.cursor_location
        line = self.document[row]
        self._replace_via_keyboard(line + "\n", (row, 0), (row, 0))
        self.move_cursor((row + 1, col))

    def _replace_rows(self, rows: range, new: list[str]) -> None:
        start = (rows.start, 0)
        end = (rows.stop - 1, len(self.document[rows.stop - 1]))
        row, col = self.cursor_location
        old_len = len(self.document[row]) if row in rows else 0
        self._replace_via_keyboard("\n".join(new), start, end)
        if row in rows:
            delta = len(new[row - rows.start]) - old_len
            self.move_cursor((row, max(0, col + delta)))
