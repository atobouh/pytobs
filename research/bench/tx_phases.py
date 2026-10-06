import time, os, sys
T0 = time.perf_counter()
def mark(n): os.write(2, f"PH {n} {(time.perf_counter()-T0)*1000:.0f}\n".encode())
from textual.app import App
mark("import app")
from textual.widgets import TextArea, Static
mark("import widgets")
MODE = sys.argv[1]
class A(App):
    def compose(self):
        mark("compose")
        if MODE == "ts": yield TextArea.code_editor("x = 1\n"*50, language="python")
        elif MODE == "plain": yield TextArea.code_editor("x = 1\n"*50)
        else: yield Static("hello")
    def on_mount(self): mark("mount"); self.call_after_refresh(lambda: (mark("first paint"), self.exit()))
A().run()
mark("exit")
