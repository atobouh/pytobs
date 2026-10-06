# Spike: restrict TextArea's highlight query to the visible window (+margin)
import os
from textual.app import App
from textual.widgets import TextArea, Static
class VPTextArea(TextArea):
    def _build_highlight_map(self):
        self._line_cache.clear(); hl = self._highlights; hl.clear()
        if not self._highlight_query: return
        top = int(self.scroll_y); h = max(self.size.height, 50)
        lo, hi = max(0, top - h), top + 2 * h
        caps = self.document.query_syntax_tree(self._highlight_query, (lo, 0), (hi, 0))
        for name, nodes in caps.items():
            for n in nodes:
                (sr, sc), (er, ec) = n.start_point, n.end_point
                if sr == er: hl[sr].append((sc, ec, name))
                else:
                    hl[sr].append((sc, None, name))
                    for r in range(max(sr + 1, lo), min(er, hi)): hl[r].append((0, None, name))
                    hl[er].append((0, ec, name))
    def watch_scroll_y(self, old, new):
        super().watch_scroll_y(old, new) if hasattr(super(), "watch_scroll_y") else None
        self._build_highlight_map()
class A(App):
    def compose(self):
        yield VPTextArea.code_editor(open(os.environ["F"]).read(), language="python"); yield Static("out")
    def on_mount(self):
        ta=self.query_one(TextArea); ta.cursor_blink=False; ta.focus(); ta.move_cursor((min(1000, ta.document.line_count-1),0))
A().run()
