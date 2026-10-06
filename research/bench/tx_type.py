import os
from textual.app import App
from textual.widgets import TextArea, Static
class A(App):
    def compose(self):
        t=TextArea.code_editor(open(os.environ["F"]).read(), language="python"); yield t; yield Static("out")
    def on_mount(self):
        ta=self.query_one(TextArea); ta.cursor_blink=False; ta.focus(); ta.move_cursor((min(1000, ta.document.line_count-1),0))
A().run()
