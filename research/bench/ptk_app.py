import os, sys, resource
from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.widgets import TextArea, Frame
from prompt_toolkit.lexers import PygmentsLexer
from pygments.lexers.python import PythonLexer
SRC = open(sys.argv[1]).read() if len(sys.argv) > 1 else "print('hi')\n"
ed = TextArea(text=SRC, lexer=PygmentsLexer(PythonLexer), line_numbers=True, scrollbar=True)
out = TextArea(text="output")
app = Application(layout=Layout(VSplit([ed, out])), full_screen=True)
def pre(app_):
    app_.loop.call_later(0.0, lambda: app_.exit()) if False else None
async def main():
    import asyncio
    async def stop():
        await asyncio.sleep(0)
        app.invalidate()
        await asyncio.sleep(0.001)
        app.exit()
    asyncio.get_running_loop().create_task(stop())
    await app.run_async()
import asyncio; asyncio.run(main())
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
os.write(2, f"MAXRSS_KB {rss}\n".encode())
