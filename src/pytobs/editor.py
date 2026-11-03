"""The code editor: Textual's TextArea with Python-aware editing and fast highlighting."""

from __future__ import annotations

import re

from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.binding import Binding
from textual.document._document_navigator import DocumentNavigator
from textual.message import Message
from textual.strip import Strip
from textual.widgets import TextArea
from textual.widgets.text_area import Selection

from . import learn
from .editor_text import indent_of
from .folding import FoldedDocument, block_end
from .lint import Diagnostic
from .theme import EDITOR_THEME, C, G

PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
CLOSERS = {")", "]", "}"}
DEDENT_RE = re.compile(r"^\s*(return|pass|break|continue|raise)\b")
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
INDENT = 4
GUIDE = "#33333F"


def _overlay(strip: Strip, x: int, text: str, style: Style) -> Strip:
    """Draw `text` over blank cells at x, keeping their background (selection, cursor line)."""
    width = len(text)
    if x < 0 or x + width > strip.cell_length:
        return strip
    middle = list(strip.crop(x, x + width))
    if "".join(seg.text for seg in middle).strip():
        return strip
    base = middle[0].style if middle and middle[0].style else Style()
    return Strip.join([strip.crop(0, x), Strip([Segment(text, base + style)], width), strip.crop(x + width)])


class CodeEditor(TextArea):
    """TextArea plus auto-indent, bracket pairs, comment toggle, diagnostics markers
    and highlighting limited to the visible window (keeps typing fast in long files)."""

    BINDINGS = [
        Binding("ctrl+slash,ctrl+underscore", "toggle_comment", "Comment", show=False),
        Binding("shift+tab", "dedent", "Dedent", show=False),
        Binding("ctrl+d", "duplicate_line", "Duplicate line", show=False),
        Binding("ctrl+a", "select_all", "Select all", show=False),
        Binding("ctrl+shift+k", "delete_line", "Delete lines", show=False),
        Binding("alt+up", "move_lines(-1)", "Move up", show=False),
        Binding("alt+down", "move_lines(1)", "Move down", show=False),
        Binding("f9", "toggle_fold", "Fold", show=False),
    ]

    # set before TextArea.__init__ loads the first document
    folds: dict[int, int] = {}  # fold header row -> last hidden row
    matches: list[tuple[int, int, int]] = []  # find results: (row, start, end)
    match_index = -1

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
        self.trace_line: int | None = None  # 0-based line shown by "Watch it run"
        self.popup_open = False
        self._skipping = False  # moving the cursor over folded lines on purpose
        self._stops: list[tuple[int, str]] = []  # snippet stops still to visit
        self._stop_anchor: tuple[int, int] | None = None

    # ── rendering ────────────────────────────────────────────────────────────

    @property
    def gutter_width(self) -> int:
        # one extra column on the left for the diagnostic marker
        return super().gutter_width + 1 if self.show_line_numbers else 0

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        if not self.show_line_numbers:
            return strip
        info = self.wrapped_document._offset_to_line_info
        offset = y + int(self.scroll_offset.y)
        if offset >= len(info):
            return strip
        row = info[offset][0]
        strip = self._decorate(strip, row)
        marker = None
        glyph = G.dot
        if row == self.trace_line:
            marker = Style(color=C.accent, bgcolor=C.base)
            glyph = G.run
        elif row == self.error_line:
            marker = Style(color=C.error, bgcolor=C.base)
        elif row in self.diagnostics:
            diag = self.diagnostics[row]
            marker = Style(color=C.error if diag.error else C.warn, bgcolor=C.base)
        elif row in self.folds:
            marker, glyph = Style(color=C.accent, bgcolor=C.base), "▸"
        elif row == self.cursor_location[0] and block_end(self.document.lines, row) is not None:
            marker, glyph = Style(color=C.faint, bgcolor=C.base), "▾"
        if marker is None:
            return strip
        rest = strip.crop(1, strip.cell_length)
        return Strip.join([Strip([Segment(glyph, marker)], 1), rest])

    def _decorate(self, strip: Strip, row: int) -> Strip:
        """Indent guides in leading spaces, and a '⋯ n lines' note after a folded header."""
        line = self.document[row]
        left = self.gutter_width - int(self.scroll_offset.x)
        guide = Style(color=GUIDE)
        if line.strip():
            cursor = self.cursor_location
            for col in range(0, indent_of(line), INDENT):
                if (row, col) != cursor:
                    strip = _overlay(strip, left + col, "│", guide)
        if row in self.folds:
            hidden = self.folds[row] - row
            note = f"⋯ {hidden} line{'s' if hidden != 1 else ''}"
            strip = _overlay(strip, left + len(line) + 2, note, Style(color=C.faint))
        return strip

    def _build_highlight_map(self) -> None:
        """Query tree-sitter only for the visible window plus one screen either side."""
        self._line_cache.clear()
        highlights = self._highlights
        highlights.clear()
        top = int(self.scroll_offset.y)
        if self.folds:
            info = self.wrapped_document._offset_to_line_info
            top = info[min(top, len(info) - 1)][0] if info else 0
        height = max(self.size.height, 40)
        lo, hi = max(0, top - height), top + 2 * height + sum(e - h for h, e in self.folds.items())
        for i, (row, start, end) in enumerate(self.matches):
            if lo <= row < hi:
                text = self.document[row]
                name = "pytobs.match.current" if i == self.match_index else "pytobs.match"
                b0, b1 = len(text[:start].encode()), len(text[:end].encode())
                highlights[row].append((b0, b1, name))
        if not self._highlight_query:
            return
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
        # find results paint over syntax colours
        for row in highlights:
            highlights[row].sort(key=lambda h: h[2].startswith("pytobs."))

    def watch_scroll_y(self, old: float, new: float) -> None:
        super().watch_scroll_y(old, new)
        if int(old) != int(new):
            self._build_highlight_map()

    def enable_highlighting(self) -> None:
        if self.language == "python":
            return
        selection = self.selection
        scroll = self.scroll_offset
        folds = self.folds
        self.language = "python"  # rebuilds the document
        self._skipping = True
        self.selection = selection
        self._skipping = False
        if folds:
            self.folds = folds
            self._apply_folds()
        self.scroll_to(scroll.x, scroll.y, animate=False, immediate=True)

    def set_diagnostics(self, diags: list[Diagnostic]) -> None:
        self.diagnostics = {}
        for d in diags:
            self.diagnostics.setdefault(d.row, d)
        self._line_cache.clear()
        self.refresh()

    def set_trace_line(self, row: int | None) -> None:
        self.trace_line = row
        self._line_cache.clear()
        self.refresh()

    def set_error_line(self, row: int | None) -> None:
        self.error_line = row
        self._line_cache.clear()
        self.refresh()

    def set_matches(self, matches: list[tuple[int, int, int]], index: int = -1) -> None:
        self.matches = matches
        self.match_index = index
        self._build_highlight_map()
        self.refresh()

    # ── folding ──────────────────────────────────────────────────────────────

    def _set_document(self, text: str, language: str | None) -> None:
        super()._set_document(text, language)
        self.folds = {}
        self.matches = []
        self.wrapped_document = FoldedDocument(self.document, tab_width=self.indent_width)
        self.navigator = DocumentNavigator(self.wrapped_document)
        self._rewrap_and_refresh_virtual_size()

    def _apply_folds(self) -> None:
        hidden: set[int] = set()
        for header, end in self.folds.items():
            hidden.update(range(header + 1, end + 1))
        doc = self.wrapped_document
        if isinstance(doc, FoldedDocument):
            doc.hidden = hidden
        self._rewrap_and_refresh_virtual_size()
        self._build_highlight_map()
        self.scroll_cursor_visible()
        self.refresh()

    def _hidden(self, row: int) -> bool:
        doc = self.wrapped_document
        return isinstance(doc, FoldedDocument) and row in doc.hidden

    def action_toggle_fold(self, row: int | None = None) -> None:
        """Fold the block the cursor is in (or its header line); unfold if already folded."""
        row = self.cursor_location[0] if row is None else row
        if row in self.folds:
            del self.folds[row]
            self._apply_folds()
            return
        lines = self.document.lines
        for header in range(row, -1, -1):
            if header in self.folds:
                continue
            end = block_end(lines, header)
            if end is not None and end >= row:
                self.folds[header] = end
                if self.cursor_location[0] != header:
                    self._skipping = True
                    self.move_cursor((header, len(lines[header])))
                    self._skipping = False
                self._apply_folds()
                return
            if lines[header].strip() and indent_of(lines[header]) == 0 and header < row:
                break  # no block above at the top level
        self.app.notify("Nothing to fold here: put the cursor in an if, for, def, class …", timeout=2)

    def fold_all(self) -> None:
        lines = self.document.lines
        self.folds = {r: e for r in range(len(lines)) if (e := block_end(lines, r)) is not None}
        row = self.cursor_location[0]
        top = next((h for h, e in sorted(self.folds.items()) if h < row <= e), None)
        if top is not None:
            self._skipping = True
            self.move_cursor((top, len(lines[top])))
            self._skipping = False
        self._apply_folds()

    def unfold_all(self) -> None:
        if self.folds:
            self.folds = {}
            self._apply_folds()

    def _watch_selection(self, previous_selection: Selection, selection: Selection) -> None:
        if self.folds and not self._skipping:
            row = selection.end[0]
            opened = [h for h, e in self.folds.items() if h < row <= e]
            if opened:
                for header in opened:
                    del self.folds[header]
                self._apply_folds()  # a jump into a folded block opens it
        super()._watch_selection(previous_selection, selection)

    def on_click(self, event: events.Click) -> None:
        # a click on the ▾ / ▸ column folds or unfolds that block
        if event.x != 0 or not self.show_line_numbers:
            return
        row = self.wrapped_document.offset_to_location((0, event.y + int(self.scroll_offset.y)))[0]
        if row in self.folds or block_end(self.document.lines, row) is not None:
            self.action_toggle_fold(row)

    def _skip_hidden(self, direction: int, select: bool) -> None:
        row, col = self.cursor_location
        guard = 0
        while self._hidden(row) and guard < 1000:
            guard += 1
            header = max(h for h, e in self.folds.items() if h < row <= e)
            end = self.folds[header]
            target = header if direction < 0 else end + 1
            if target >= self.document.line_count:
                target = header
                direction = -1
            row = target
        if row != self.cursor_location[0]:
            self.move_cursor((row, min(col, len(self.document[row]))), select=select)

    def action_cursor_up(self, select: bool = False) -> None:
        self._skipping = True
        try:
            super().action_cursor_up(select)
            self._skip_hidden(-1, select)
        finally:
            self._skipping = False

    def action_cursor_down(self, select: bool = False) -> None:
        self._skipping = True
        try:
            super().action_cursor_down(select)
            self._skip_hidden(1, select)
        finally:
            self._skipping = False

    def action_select_all(self) -> None:
        self._skipping = True
        try:
            self.select_all()
        finally:
            self._skipping = False

    def edit(self, edit):
        result = super().edit(edit)
        if self.folds:
            top, bottom = edit.top[0], edit.bottom[0]
            delta = result.end_location[0] - bottom
            lines = self.document.lines
            kept: dict[int, int] = {}
            for header, end in self.folds.items():
                if end < top:
                    kept[header] = end
                    continue
                if header > bottom:
                    header += delta
                elif not (header == top == bottom and delta == 0):
                    continue  # the edit touched the folded block: open it
                new_end = block_end(lines, header)
                if new_end is not None:
                    kept[header] = new_end
            if kept != self.folds:
                self.folds = kept
                self._apply_folds()
        return result

    def undo(self) -> None:
        super().undo()
        self.unfold_all()

    def redo(self) -> None:
        super().redo()
        self.unfold_all()

    # ── moving lines ─────────────────────────────────────────────────────────

    def action_move_lines(self, direction: int) -> None:
        if self.read_only:
            return
        rows = self._selected_rows()
        lines = self.document.lines
        if (direction < 0 and rows.start == 0) or (direction > 0 and rows.stop >= len(lines)):
            return
        if direction < 0:
            span = range(rows.start - 1, rows.stop)
            block = lines[span.start : span.stop]
            new = block[1:] + block[:1]
        else:
            span = range(rows.start, rows.stop + 1)
            block = lines[span.start : span.stop]
            new = block[-1:] + block[:-1]
        (r1, c1), (r2, c2) = self.selection
        last = span.stop - 1
        self._replace_via_keyboard("\n".join(new), (span.start, 0), (last, len(lines[last])))
        self.selection = Selection((r1 + direction, c1), (r2 + direction, c2))

    # ── snippets ─────────────────────────────────────────────────────────────

    def _expand_snippet(self) -> bool:
        if not self.selection.is_empty:
            return False
        row, col = self.cursor_location
        line = self.document[row]
        word = line[:col].strip()
        if line[col:].strip() or word not in learn.SNIPPETS:
            return False
        start = col - len(word)
        text, stops = learn.expand(learn.SNIPPETS[word][1], " " * indent_of(line))
        self._replace_via_keyboard(text, (row, start), (row, col))
        self._stops = [(row + offset, stop) for offset, stop in stops]
        self._stop_anchor = (row, start)
        self._next_stop()
        return True

    def _next_stop(self) -> bool:
        cursor_row, cursor_col = self.cursor_location
        while self._stops:
            row, stop = self._stops.pop(0)
            if row >= self.document.line_count:
                break
            line = self.document[row]
            if self._stop_anchor is not None:
                frm = self._stop_anchor[1] if self._stop_anchor[0] == row else 0
                self._stop_anchor = None
            else:
                frm = cursor_col if cursor_row == row else 0
            at = line.find(stop, frm)
            if at >= 0:
                self.selection = Selection((row, at), (row, at + len(stop)))
                return True
        self._stops = []
        return False

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
        if key == "tab" and not self.read_only:
            if self._stops and self._next_stop():
                event.stop()
                event.prevent_default()
                return
            if self._expand_snippet():
                event.stop()
                event.prevent_default()
                return
        if key == "escape":
            self._stops = []
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
