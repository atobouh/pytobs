import os
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, VSplit
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.key_binding import KeyBindings
from pygments.lexers.python import PythonLexer
txt=open(os.environ["F"]).read()
ed=TextArea(text=txt, lexer=PygmentsLexer(PythonLexer), line_numbers=True)
ed.buffer.cursor_position=len("\n".join(txt.split("\n")[:1000]))
kb=KeyBindings()
@kb.add("c-q")
def _(e): e.app.exit()
app=Application(layout=Layout(VSplit([ed, TextArea(text="out")]), focused_element=ed), key_bindings=kb, full_screen=True)
app.run()
