# Throwaway visual mockup of the proposed look, rendered by Textual itself.
import asyncio, sys
from rich.style import Style
from rich.text import Text
from textual.app import App
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, TextArea
from textual.widgets.text_area import TextAreaTheme

C = dict(base="#1F1F28", mantle="#1A1A22", surface="#2A2A37", overlay="#363646",
         text="#DCD7BA", muted="#8A8980", faint="#54546D", accent="#7E9CD8",
         error="#E46876", warn="#E6C384", ok="#98BB6C",
         kw="#957FB8", st="#98BB6C", fn="#7FB4CA", const="#D27E99")
S = lambda c, **k: Style(color=C[c], **k)
syntax = {}
for k in ["keyword", "include", "conditional", "repeat", "exception", "keyword.operator", "keyword.function", "keyword.return"]:
    syntax[k] = S("kw")
for k in ["string", "string.documentation", "escape"]:
    syntax[k] = S("st")
for k in ["function", "function.call", "method", "method.call", "type", "type.builtin", "class", "constructor", "function.builtin"]:
    syntax[k] = S("fn")
for k in ["number", "float", "boolean", "constant.builtin", "constant"]:
    syntax[k] = S("const")
syntax["comment"] = S("muted", italic=True)
THEME = TextAreaTheme(
    name="sumi", base_style=Style(color=C["text"], bgcolor=C["base"]),
    gutter_style=Style(color=C["faint"], bgcolor=C["base"]),
    cursor_style=Style(color=C["base"], bgcolor=C["accent"]),
    cursor_line_style=Style(bgcolor="#24242F"),
    cursor_line_gutter_style=Style(color=C["muted"], bgcolor="#24242F"),
    bracket_matching_style=Style(bgcolor=C["overlay"]),
    selection_style=Style(bgcolor=C["overlay"]),
    syntax_styles=syntax,
)

CODE_OK = '''import json
from pathlib import Path


def load(path: Path) -> list[dict]:
    """Read a list of people from a JSON file."""
    with path.open() as f:
        return json.lo


people = load(Path("people.json"))
for person in people:
    print(person["name"], person["age"])
'''
CODE_ERR = CODE_OK.replace("json.lo\n", "json.load(f)\n").replace('person["age"]', 'person["agee"]')
CODE_IN = '''import time

total = 0
for step in range(1, 4):
    print(f"step {step}/3")
    time.sleep(0.5)

name = input("your name: ")
print(f"hello, {name}")
'''

CSS = f"""
Screen {{ background: {C['base']}; layers: base overlay; }}
#main {{ height: 1fr; }}
#left {{ width: 5fr; background: {C['base']}; }}
#tab {{ height: 1; padding: 0 2; color: {C['muted']}; background: {C['base']}; }}
#gap {{ height: 1; background: {C['base']}; }}
TextArea {{ border: none; padding: 0 1; background: {C['base']}; height: 1fr; }}
TextArea:focus {{ border: none; }}
#right {{ width: 4fr; background: {C['mantle']}; padding: 0 2; }}
#runhead {{ height: 1; color: {C['muted']}; }}
#out {{ height: 1fr; padding-top: 1; }}
#status {{ height: 1; background: {C['mantle']}; color: {C['muted']}; padding: 0 2; }}
#menu {{ layer: overlay; width: auto; height: auto; background: {C['surface']}; padding: 0 0; }}
#dot {{ layer: overlay; width: 1; height: 1; background: {C['base']}; }}
#doc {{ layer: overlay; width: 46; height: auto; background: {C['surface']}; padding: 1 2; }}
"""

def status(left_extra="ruff ✓", pos="Ln 8, Col 23", hints="^R run   ^P files   ^K commands"):
    t = Text()
    t.append("~\\code\\scratch\\people.py", style=C["text"])
    t.append("   .venv 3.13   ", style=C["muted"])
    t.append(left_extra, style=C["ok"] if "✓" in left_extra else C["warn"])
    t.append("   " + pos, style=C["muted"])
    pad = 104 - len(t.plain) - len(hints)
    t.append(" " * max(pad, 2))
    for i, part in enumerate(hints.split("   ")):
        k, _, v = part.partition(" ")
        if i: t.append("   ")
        t.append(k, style=C["text"]); t.append(" " + v, style=C["muted"])
    return t

class Mock(App):
    CSS = CSS
    def __init__(self, state):
        super().__init__(); self.state = state
    def compose(self):
        st = self.state
        code = {"lint": CODE_IN, "complete": CODE_OK, "error": CODE_ERR, "input": CODE_IN, "done": CODE_ERR.replace('"agee"', '"age"')}[st]
        tabname = "people.py" if st not in ("input", "lint") else "steps.py"
        with Horizontal(id="main"):
            with Vertical(id="left"):
                tab = Text(); tab.append(tabname, style=C["text"])
                if st == "complete": tab.append("  ●", style=C["muted"])
                yield Static(tab, id="tab")
                yield Static("", id="gap")
                ta = TextArea(code, language="python", show_line_numbers=True, soft_wrap=False, id="ed")
                ta.register_theme(THEME); ta.theme = "sumi"; ta.cursor_blink = False
                yield ta
            with Vertical(id="right"):
                yield Static(self.runhead(), id="runhead")
                yield Static(self.output(), id="out")
        yield Static(self.statusline(), id="status")
        if st == "lint":
            yield Static(Text("●", style=C["warn"]), id="dot")
        if st == "complete":
            yield Static(self.menu(), id="menu")
            yield Static(self.doc(), id="doc")

    def runhead(self):
        t = Text()
        if self.state == "complete":
            t.append("output", style=C["muted"]); t.append("   no runs yet", style=C["faint"])
        elif self.state == "lint":
            t.append("▸ ", style=C["accent"]); t.append("run 2", style=C["text"])
            t.append("   1.58 s   ", style=C["muted"]); t.append("exit 0", style=C["ok"])
        elif self.state == "done":
            t.append("▸ ", style=C["accent"]); t.append("run 4", style=C["text"])
            t.append("   0.06 s   ", style=C["muted"]); t.append("exit 0", style=C["ok"])
        elif self.state == "error":
            t.append("▸ ", style=C["accent"]); t.append("run 3", style=C["text"])
            t.append("   0.05 s   ", style=C["muted"]); t.append("exit 1", style=C["error"])
        else:
            t.append("⠼ ", style=C["accent"]); t.append("running", style=C["text"])
            t.append("   1.6 s", style=C["muted"]); t.append("      Ctrl+C stop", style=C["faint"])
        return t

    def output(self):
        t = Text()
        if self.state == "complete":
            t.append("Press Ctrl+R to save and run.\n", style=C["muted"])
            t.append("Output streams here as it happens.", style=C["faint"])
        elif self.state == "lint":
            for s_ in (1, 2, 3): t.append(f"step {s_}/3\n", style=C["text"])
            t.append("your name: Ada\nhello, Ada\n", style=C["text"])
        elif self.state == "done":
            for n, a in [("Ada", 36), ("Grace", 45), ("Linus", 28), ("Guido", 41)]:
                t.append(f"{n} {a}\n", style=C["text"])
        elif self.state == "error":
            t.append("KeyError", style=Style(color=C["error"], bold=True)); t.append(": 'agee'\n\n", style=C["text"])
            t.append("people.py", style=C["accent"]); t.append(":13", style=C["accent"]); t.append("  in <module>\n", style=C["muted"])
            t.append('  print(person["name"], person["agee"])\n', style=C["text"])
            t.append("                        ^^^^^^^^^^^^^^\n\n", style=C["error"])
            t.append("Ctrl+E", style=C["text"]); t.append("  jump to line 13", style=C["muted"])
        else:
            for s in (1, 2, 3): t.append(f"step {s}/3\n", style=C["text"])
            t.append("your name: ", style=C["text"]); t.append("Ada", style=C["text"]); t.append(" ", style=Style(bgcolor=C["accent"]))
            t.append("\n\n"); t.append("Enter", style=C["text"]); t.append(" send   ", style=C["muted"])
            t.append("Ctrl+D", style=C["text"]); t.append(" end input", style=C["muted"])
        return t

    def statusline(self):
        if self.state == "complete": return status()
        if self.state == "error": return status("ruff ✓", "Ln 13, Col 32", "^E error   ^R run   ^P files")
        if self.state == "done": return status("ruff ✓", "Ln 13, Col 1")
        if self.state == "lint":
            t = Text()
            t.append("~\\code\\scratch\\steps.py", style=C["text"]); t.append("   .venv 3.13   ", style=C["muted"])
            t.append("ruff 1", style=C["warn"]); t.append("   F841 ", style=C["text"])
            t.append("`total` is assigned but never used", style=C["muted"])
            return t
        return status("ruff ✓", "Ln 8, Col 1", "^C stop   ^D end input")

    def menu(self):
        rows = [("load", "ƒ", True), ("loads", "ƒ", False), ("JSONDecodeError", "c", False), ("JSONDecoder", "c", False)]
        t = Text()
        for i, (label, kind, sel) in enumerate(rows):
            bg = C["overlay"] if sel else C["surface"]
            t.append("▌" if sel else " ", style=Style(color=C["accent"], bgcolor=bg))
            t.append(f"{label:<17}", style=Style(color=C["text"], bgcolor=bg, bold=sel))
            t.append(f"{kind} ", style=Style(color=C["muted"], bgcolor=bg))
            if i < len(rows) - 1: t.append("\n")
        return t

    def doc(self):
        t = Text()
        t.append("load", style=C["fn"]); t.append("(fp, *, cls=None, object_hook=None, …)\n\n", style=C["text"])
        t.append("Deserialize fp (a .read()-supporting\nfile containing a JSON document) to a\nPython object.", style=C["muted"])
        return t

    def on_mount(self):
        ta = self.query_one(TextArea)
        ta.focus()
        pos = {"lint": (2, 0), "complete": (7, 22), "error": (12, 31), "input": (7, 0), "done": (12, 0)}[self.state]
        ta.move_cursor(pos)
        if self.state == "lint":
            self.query_one("#dot").styles.offset = (0, 4)
        if self.state == "complete":
            self.query_one("#menu").styles.offset = (25, 10)
            self.query_one("#doc").styles.offset = (46, 6)

async def shoot(state):
    app = Mock(state)
    async with app.run_test(size=(108, 22)) as pilot:
        await pilot.pause(0.3)
        svg = app.export_screenshot(title="pytobs")
    open(f"{state}.svg", "w").write(svg)

for s in ["complete", "error", "input", "done", "lint"]:
    asyncio.run(shoot(s))
print("ok")
