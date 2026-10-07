"""Throwaway mockups of proposed learning features, rendered with pytobs's real editor and theme."""
import asyncio
from rich.style import Style
from rich.text import Text
from textual.app import App
from textual.containers import Horizontal, Vertical
from textual.widgets import Static
from pytobs.editor import CodeEditor
from pytobs.theme import APP_THEME, C, G

def T(*parts):
    t = Text()
    for p in parts:
        if isinstance(p, str): t.append(p)
        else: t.append(p[0], style=p[1] if isinstance(p[1], Style) else Style(color=p[1]) if p[1] else "")
    return t

def lines(*rows):
    out = Text()
    for i, r in enumerate(rows):
        if i: out.append("\n")
        out.append_text(r if isinstance(r, Text) else T(*r) if isinstance(r, tuple) else Text(r))
    return out

B = lambda c: Style(color=c, bold=True)
CODE = {
"trace": '''friends = ["Ada", "Grace", "Linus"]
lengths = {}

for name in friends:
    lengths[name] = len(name)

print(lengths)
''',
"explain": '''friends = ["hello", "Big", "Claude"]
print(len(friends))
print(friends[:2])
print(friends.count())
''',
"tests": '''def count_names(names):
    counts = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    return counts


def test_empty():
    assert count_names([]) == {}

def test_one():
    assert count_names(["Ada"]) == {"Ada": 1}

def test_repeats():
    assert count_names(["Ada", "Ada"]) == {"Ada": 2}

def test_ignores_case():
    assert count_names(["Ada", "ada"]) == {"Ada": 2}
''',
"progress": '''friends = ["hello", "Big", "Claude"]
print(len(friends))
''',
}

def bar(frac, width=28):
    full = int(frac * width)
    return T(("━" * full, C.accent), ("━" * (width - full), C.surface))

def right(state):
    if state == "trace":
        return (T((f"{G.run} ", C.accent), ("trace", C.text), ("   step ", C.muted), ("7", C.text), (" of 12", C.muted), ("     ← → step", C.faint)),
            lines(
                bar(7/12, 38),
                "",
                T(("line 5  ", C.muted), ("lengths[name] = len(name)", C.text)),
                "",
                T(("variables", C.accent)),
                T(("  friends ", C.text), (" list ", C.faint), ('["Ada", "Grace", "Linus"]', C.muted)),
                T(("  name    ", C.text), (" str  ", C.faint), ('"Grace"', B(C.accent)), ("   changed", C.accent)),
                T(("  lengths ", C.text), (" dict ", C.faint), ('{"Ada": 3}', C.muted)),
                "",
                T(("friends", C.accent)),
                T(("  ╭───────┬─────────┬─────────╮", C.overlay)),
                T(("  │", C.overlay), (' "Ada" ', C.muted), ("│", C.overlay), (' "Grace" ', B(C.text)), ("│", C.overlay), (' "Linus" ', C.muted), ("│", C.overlay)),
                T(("  ╰───────┴─────────┴─────────╯", C.overlay)),
                T(("      0         ", C.faint), ("1", B(C.accent)), ("         2", C.faint)),
                T(("                ", ""), ("▲ name", C.accent)),
                "",
                T(("lengths", C.accent)),
                T(('  "Ada"', C.muted), ("  →  ", C.faint), ("3", C.constant)),
            ))
    if state == "explain":
        return (T((f"{G.run} ", C.accent), ("run 4", C.text), ("   0.36s   exit ", C.muted), ("1", C.error)),
            lines(
                T(("3", C.text)), T(("['hello', 'Big']", C.text)), "",
                T((f"{G.cross} ", C.error), ("TypeError", B(C.error)), (": list.count() takes exactly", C.text)),
                T(("  one argument (0 given)", C.text)), "",
                T(("test.py:4", Style(color=C.accent, underline=True)), ("  in <module>", C.muted)),
                T(("  print(friends.count())", C.text)), "",
                T(("─" * 40, C.surface)),
                T(("What it means", C.accent)),
                T((".count(x)", C.callable), (" counts how many times ", C.muted), ("x", C.text)),
                T(("appears in the list. It needs to know", C.muted)),
                T(("what to count, and got nothing.", C.muted)), "",
                T(("Try", C.accent)),
                T(('  friends.count("Big")', C.text), ("   → 1", C.faint)),
                T(("  len(friends)", C.text), ("           → 3", C.faint), ("  the size", C.faint)), "",
                T(("^E", C.text), ("  jump to line 4", C.muted)),
            ))
    if state == "tests":
        return (T((f"{G.dot} ", C.ok), ("tests", C.text), ("   3 passed ", C.muted), ("· 1 failed", C.error), ("   0.04s", C.muted)),
            lines(
                bar(3/4, 38).copy(),
                "",
                T((f"{G.dot} ", C.ok), ("test_empty", C.text)),
                T((f"{G.dot} ", C.ok), ("test_one", C.text)),
                T((f"{G.dot} ", C.ok), ("test_repeats", C.text)),
                T((f"{G.cross} ", C.error), ("test_ignores_case", B(C.text))),
                T(("    expected  ", C.muted), ('{"Ada": 2}', C.ok)),
                T(("    got       ", C.muted), ('{"Ada": 1, "ada": 1}', C.error)),
                T(("    ", ""), ("count.py:18", Style(color=C.accent, underline=True))),
                "",
                T(("─" * 40, C.surface)),
                T(("^T", C.text), ("  run tests   ", C.muted), ("^R", C.text), ("  run file", C.muted)),
                T(("Any function named test_… is a test.", C.faint)),
            ))
    return right("explain")

HEAT = "·░▒▓█"
def progress_panel():
    import random
    random.seed(7)
    rows = []
    days = ["Mon", "   ", "Wed", "   ", "Fri", "   ", "Sun"]
    weeks = 16
    grid = [[random.choice([0,0,1,1,2,2,3,4]) if w > 3 or random.random() > .6 else 0 for w in range(weeks)] for _ in range(7)]
    shades = ["#363646", "#3A4A6B", "#4E6699", "#6683BF", C.accent]
    out = Text()
    out.append("Your progress\n\n", style=B(C.text))
    stats = [("12", "day streak"), ("47", "runs this week"), ("6h 40m", "coding time"), ("31", "errors fixed")]
    for num, label in stats:
        out.append(f"{num:<9}", style=B(C.text))
    out.append("\n")
    for num, label in stats:
        out.append(f"{label:<9}"[:9] if len(label) < 9 else label[:8] + " ", style=C.muted)
    out = Text()
    out.append("Your progress", style=B(C.text)); out.append("    last 16 weeks\n\n", style=C.muted)
    # big numbers row
    nums = [("12", "day streak"), ("47", "runs this week"), ("6h40", "coding time"), ("31", "errors fixed")]
    for n, _ in nums: out.append(f"{n:<16}", style=B(C.text))
    out.append("\n")
    for _, l in nums: out.append(f"{l:<16}", style=C.muted)
    out.append("\n\n")
    for d in range(7):
        out.append(f"{days[d]}  ", style=C.faint)
        for w in range(weeks):
            v = grid[d][w]
            out.append("■ ", style=Style(color=shades[v]))
        out.append("\n")
    out.append("     less ", style=C.faint)
    for s in shades: out.append("■ ", style=Style(color=s))
    out.append("more\n\n", style=C.faint)
    out.append("Errors you meet most", style=B(C.text)); out.append("    and what to review\n", style=C.muted)
    for name, n, tip in [("TypeError", 9, "function arguments"), ("NameError", 6, "spelling, scope"), ("IndexError", 4, "list positions start at 0"), ("KeyError", 2, "dict.get()")]:
        out.append(f"\n{name:<12}", style=C.text)
        out.append("━" * (n * 2), style=C.error if name == "TypeError" else C.muted)
        out.append(" " * (20 - n * 2))
        out.append(f" {n:<3}", style=C.text)
        out.append(f"  {tip}", style=C.faint)
    return out

class Mock(App):
    def __init__(self, state):
        super().__init__(); self.state = state
        self.register_theme(APP_THEME); self.theme = "sumi"
    CSS = f"""
    Screen {{ background: {C.base}; layers: base top; }}
    #main {{ height: 1fr; }}
    #left {{ width: 3fr; }}
    #tab {{ height: 1; padding: 0 2; margin-bottom: 1; color: {C.text}; }}
    CodeEditor {{ border: none; padding: 0 1 0 0; height: 1fr; scrollbar-size-vertical: 0; scrollbar-size-horizontal: 0; }}
    #right {{ width: 2fr; background: {C.mantle}; padding: 0 0 0 2; }}
    #head {{ height: 1; margin-bottom: 1; }}
    #status {{ dock: bottom; height: 1; background: {C.mantle}; color: {C.muted}; padding: 0 2; }}
    #panel {{ layer: top; position: absolute; offset: 14 3; width: 80; height: auto; background: {C.surface}; padding: 1 3; }}
    """
    def compose(self):
        name = {"trace": "loops.py", "explain": "test.py", "tests": "count.py", "progress": "test.py"}[self.state]
        head, body = right(self.state)
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Static(name, id="tab")
                ed = CodeEditor(CODE[self.state]); ed.id = "ed"; yield ed
            with Vertical(id="right"):
                yield Static(head, id="head")
                yield Static(body, id="body")
        st = T(("~\\scrimba\\" + name, C.text), ("   py 3.13   ", C.muted), (f"{G.dot} ", C.ok), ("ruff", C.muted))
        yield Static(st, id="status")
        if self.state == "progress":
            yield Static(progress_panel(), id="panel")
    def on_mount(self):
        ed = self.query_one(CodeEditor); ed.enable_highlighting(); ed.focus()
        if self.state == "trace": ed.move_cursor((4, 4))
        if self.state == "explain": ed.move_cursor((3, 0)); ed.set_error_line(3)
        if self.state == "tests": ed.move_cursor((17, 4)); ed.set_error_line(17)
        if self.state == "progress": ed.move_cursor((1, 0))

async def shoot(state):
    app = Mock(state)
    async with app.run_test(size=(112, 28)) as pilot:
        await pilot.pause(0.5)
        open(f"{state}.svg", "w").write(app.export_screenshot(title="pytobs"))

for s in ["trace", "explain", "tests", "progress"]:
    asyncio.run(shoot(s))
print("ok")
