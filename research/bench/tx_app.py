import os, sys, resource
from textual.app import App, ComposeResult
from textual.widgets import TextArea, Static
from textual.containers import Horizontal
SRC = open(sys.argv[1]).read() if len(sys.argv) > 1 else "print('hi')\n"
class A(App):
    CSS = "TextArea{width:2fr} Static{width:1fr}"
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield TextArea.code_editor(SRC, language="python")
            yield Static("output")
    def on_mount(self):
        self.call_after_refresh(self.done)
    def done(self):
        self.call_after_refresh(self.exit)
A().run()
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
os.write(2, f"MAXRSS_KB {rss}\n".encode())
