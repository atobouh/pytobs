"""The output pane: a fast, wrapping, append-only log with clickable jump targets."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual import events
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.selection import Selection
from textual.strip import Strip

from .theme import C

MAX_LINES = 5000


class OutputLog(ScrollView, can_focus=True):
    DEFAULT_CSS = f"""
    OutputLog {{
        background: {C.mantle};
        color: {C.text};
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 0;
        overflow-x: hidden;
    }}
    """

    class Jump(Message):
        def __init__(self, line: int) -> None:
            super().__init__()
            self.line = line

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.lines: list[Text] = [Text()]
        self.jumps: dict[int, int] = {}  # logical line -> 1-based source line
        self._wrapped: list[tuple[int, Text]] = []  # (logical index, display text)
        self._wrap_width = 0
        self._dropped = 0
        self._pending_cr = False

    # ── content ──────────────────────────────────────────────────────────────

    def clear(self) -> None:
        self.lines = [Text()]
        self.jumps = {}
        self._dropped = 0
        self._pending_cr = False
        self._rewrap_all()

    def write(self, text: str, style: Style | str = "") -> None:
        """Append raw program output; handles partial lines and carriage returns."""
        follow = self._at_bottom()
        start = len(self.lines) - 1
        parts = text.split("\n")
        for i, part in enumerate(parts):
            if i:
                self.lines.append(Text())
            if "\r" in part:
                # progress bars: keep only what follows the last carriage return
                segments = part.split("\r")
                if any(segments[1:]):
                    self.lines[-1] = Text()
                part = next((s for s in reversed(segments) if s), "")
            if part:
                self.lines[-1].append(part, style)
        self._trim()
        self._rewrap_from(start)
        if follow:
            self.scroll_end(animate=False, immediate=True)

    def add_line(self, text: Text, jump: int | None = None) -> None:
        follow = self._at_bottom()
        if self.lines[-1].plain:
            self.lines.append(Text())
        self.lines[-1] = text
        if jump is not None:
            self.jumps[len(self.lines) - 1] = jump
        self.lines.append(Text())
        start = len(self.lines) - 2
        self._trim()
        self._rewrap_from(max(0, start))
        if follow:
            self.scroll_end(animate=False, immediate=True)

    @property
    def has_content(self) -> bool:
        return any(line.plain for line in self.lines)

    def ensure_newline(self) -> None:
        if not self.lines[-1].plain:
            return
        self.lines.append(Text())
        self._rewrap_from(len(self.lines) - 2)

    def _trim(self) -> None:
        extra = len(self.lines) - MAX_LINES
        if extra > 0:
            del self.lines[:extra]
            self.jumps = {k - extra: v for k, v in self.jumps.items() if k >= extra}
            self._dropped += extra
            self._rewrap_all()

    # ── wrapping and rendering ───────────────────────────────────────────────

    def _width(self) -> int:
        return max(10, self.scrollable_content_region.width - 1)

    def _wrap(self, index: int) -> list[tuple[int, Text]]:
        text = self.lines[index]
        if not text.plain:
            return [(index, Text())]
        width = self._wrap_width
        out = []
        for line in text.split("\n", allow_blank=True):
            if line.cell_len <= width:
                out.append((index, line))
            else:
                # wrap at word boundaries; words longer than the pane fold
                parts = line.wrap(self.app.console, width, overflow="fold", no_wrap=False)
                out.extend((index, part) for part in parts)
        return out

    def _rewrap_all(self) -> None:
        self._wrap_width = self._width()
        self._wrapped = []
        for i in range(len(self.lines)):
            self._wrapped.extend(self._wrap(i))
        self._update_size()

    def _rewrap_from(self, index: int) -> None:
        if self._wrap_width != self._width():
            self._rewrap_all()
            return
        while self._wrapped and self._wrapped[-1][0] >= index:
            self._wrapped.pop()
        for i in range(index, len(self.lines)):
            self._wrapped.extend(self._wrap(i))
        self._update_size()

    def _update_size(self) -> None:
        # drop the trailing empty line from the height so the view doesn't scroll past content
        count = len(self._wrapped)
        if count and not self._wrapped[-1][1].plain:
            count -= 1
        self.virtual_size = Size(self._wrap_width, max(count, 0))
        self.refresh()

    def _at_bottom(self) -> bool:
        return self.scroll_offset.y >= self.max_scroll_y - 1

    def on_resize(self, event: events.Resize) -> None:
        if self._width() != self._wrap_width:
            self._rewrap_all()

    def render_line(self, y: int) -> Strip:
        index = y + int(self.scroll_offset.y)
        width = self.scrollable_content_region.width
        base = Style(bgcolor=C.mantle, color=C.text)
        if index >= len(self._wrapped):
            return Strip.blank(width, base).apply_offsets(0, index)
        logical, text = self._wrapped[index]
        selection = self.text_selection
        if selection is not None and (span := selection.get_span(index)) is not None:
            start, end = span
            text = text.copy()
            text.stylize(Style(bgcolor=C.overlay, color=C.text), start, len(text) if end == -1 else end)
        segments = list(text.render(self.app.console))
        strip = Strip(segments, text.cell_len).apply_style(base)
        if logical in self.jumps:
            strip = strip.apply_style(Style(meta={"jump": self.jumps[logical]}))
        # offsets let Textual map mouse drags to (line, column) for text selection
        return strip.extend_cell_length(width, base).crop(0, width).apply_offsets(0, index)

    # ── selection and copying ────────────────────────────────────────────────

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Text under a mouse selection. Wrapped pieces of one output line are joined back together."""
        parts: list[str] = []
        previous = None
        for index, (logical, text) in enumerate(self._wrapped):
            span = selection.get_span(index)
            if span is None:
                continue
            start, end = span
            piece = text.plain[start:] if end == -1 else text.plain[start:end]
            if previous is not None and logical != previous:
                parts.append("\n")
            parts.append(piece)
            previous = logical
        return "".join(parts), "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        self.refresh()

    @property
    def plain_text(self) -> str:
        return "\n".join(line.plain for line in self.lines).rstrip("\n")

    def on_click(self, event: events.Click) -> None:
        index = event.y + int(self.scroll_offset.y)
        if 0 <= index < len(self._wrapped):
            logical = self._wrapped[index][0]
            if logical in self.jumps:
                self.post_message(self.Jump(self.jumps[logical]))
