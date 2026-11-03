"""Code folding: which blocks can fold, and a document view that hides folded lines."""

from __future__ import annotations

from textual._cells import cell_width_to_column_index
from textual.document._document import Location
from textual.document._wrapped_document import WrappedDocument
from textual.geometry import Offset

from .editor_text import code_part, indent_of


def block_end(lines: list[str], row: int) -> int | None:
    """Last row of the block opened by `row` (a line ending in ':'), or None if it can't fold."""
    if row >= len(lines) or not code_part(lines[row]).rstrip().endswith(":"):
        return None
    head = indent_of(lines[row])
    last = None
    for r in range(row + 1, len(lines)):
        line = lines[r]
        if not line.strip():
            continue
        if indent_of(line) <= head:
            break
        last = r
    return last


class FoldedDocument(WrappedDocument):
    """The editor's line layout with folded lines removed. pytobs never soft-wraps, so every
    visible document line is exactly one row on screen."""

    def __init__(self, document, width: int = 0, tab_width: int = 4) -> None:
        self.hidden: set[int] = set()
        self._patched = False
        super().__init__(document, width, tab_width)

    def wrap(self, width: int, tab_width: int | None = None) -> None:
        super().wrap(width, tab_width)
        self._patched = False
        if self.hidden:
            self._hide()

    def wrap_range(self, start: Location, old_end: Location, new_end: Location) -> None:
        if self.hidden or self._patched:
            self.wrap(self._width)  # the incremental path assumes one row per line
        else:
            super().wrap_range(start, old_end, new_end)

    def _hide(self) -> None:
        info: list[tuple[int, int]] = []
        offsets: list[list[int]] = []
        y = 0
        hidden = self.hidden
        for index, wraps in enumerate(self._wrap_offsets):
            if index in hidden:
                # a hidden line lives on its fold header's row
                offsets.append([max(0, y - 1)] * (len(wraps) + 1))
                continue
            row = []
            for section in range(len(wraps) + 1):
                info.append((index, section))
                row.append(y)
                y += 1
            offsets.append(row)
        self._offset_to_line_info = info
        self._line_index_to_offsets = offsets
        self._patched = True

    @property
    def height(self) -> int:
        return len(self._offset_to_line_info)

    def offset_to_location(self, offset: Offset) -> Location:
        if self._width or not self._patched:
            return super().offset_to_location(offset)
        x, y = offset
        info = self._offset_to_line_info
        if not info:
            return 0, 0
        line_index = info[min(max(0, y), len(info) - 1)][0]
        column = cell_width_to_column_index(self.document.get_line(line_index), max(0, x), self._tab_width)
        return line_index, column
