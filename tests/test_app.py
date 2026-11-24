"""Drive the real app headless with Textual's pilot."""

import sys
from pathlib import Path

import pytest

from textual.widgets import Input

from pytobs.app import Pytobs


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    (tmp_path / "ruff.toml").write_text("")


async def _type(pilot, text: str) -> None:
    for ch in text:
        await pilot.press({"\n": "enter", " ": "space", "(": "left_parenthesis"}.get(ch, ch))


async def test_auto_indent_and_pairs(tmp_path: Path) -> None:
    app = Pytobs(path=tmp_path / "a.py", python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        await _type(pilot, "def f(x):\nreturn [x")
        assert app.editor.text == "def f(x):\n    return [x]"
        await pilot.press("]")  # types over the auto-inserted closer
        assert app.editor.text == "def f(x):\n    return [x]"
        await pilot.press("enter")
        assert app.editor.text.endswith("return [x]\n")  # dedent after return
        assert app.editor.cursor_location == (2, 0)


async def test_smart_backspace_and_comment(tmp_path: Path) -> None:
    app = Pytobs(path=tmp_path / "a.py", python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        await _type(pilot, "if True:\n")
        assert app.editor.text == "if True:\n    "
        await pilot.press("backspace")
        assert app.editor.text == "if True:\n"
        await _type(pilot, "x = 1")
        await pilot.press("ctrl+underscore")
        assert app.editor.text == "if True:\n# x = 1"
        await pilot.press("ctrl+underscore")
        assert app.editor.text == "if True:\nx = 1"


async def test_run_error_and_jump(tmp_path: Path) -> None:
    script = tmp_path / "people.py"
    script.write_text('people = [{"name": "Ada"}]\nfor p in people:\n    print(p["agee"])\n')
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("ctrl+r")
        for _ in range(100):
            await pilot.pause(0.05)
            if app.current and app.current.finished and app.last_run:
                break
        assert app.last_run and app.last_run[0] == 1
        lines = [t.plain for t in app.output.lines]
        assert "× KeyError: 'agee'" in lines
        assert app.error_jump == 3
        await pilot.press("ctrl+e")
        assert app.editor.cursor_location == (2, 4)


async def test_autosave_on_run(tmp_path: Path) -> None:
    script = tmp_path / "s.py"
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        await _type(pilot, 'print("hi")')
        await pilot.press("ctrl+r")
        for _ in range(100):
            await pilot.pause(0.05)
            if app.last_run:
                break
        assert script.read_text() == 'print("hi")'
        assert [t.plain for t in app.output.lines][0] == "hi"


async def _wait(app, pilot) -> None:
    for _ in range(200):
        await pilot.pause(0.05)
        if app.current and app.current.finished and app._activity is None:
            break
    await pilot.pause(0.2)


async def test_watch_it_run(tmp_path: Path) -> None:
    script = tmp_path / "loop.py"
    script.write_text("total = 0\nfor n in [1, 2, 3]:\n    total += n\nprint(total)\n")
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("f6")
        await _wait(app, pilot)
        view = app.query_one("TraceView")
        assert view.has_class("show") and view.trace and len(view.trace.steps) == 9
        assert app.editor.trace_line == 0
        await pilot.press("right", "right")
        assert app.editor.trace_line == 2 and view.index == 2
        await pilot.press("end")
        assert view.index == 8
        await pilot.press("escape")
        assert not view.has_class("show") and app.output.display
        assert app.editor.trace_line is None


async def test_tests_panel(tmp_path: Path) -> None:
    script = tmp_path / "t.py"
    script.write_text("def test_a():\n    assert 1 == 1\n\ndef test_b():\n    assert [1] == [2]\n")
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("ctrl+t")
        await _wait(app, pilot)
        lines = [t.plain for t in app.output.lines]
        assert "● test_a" in lines and "× test_b" in lines
        assert any("expected  [2]" in line for line in lines)
        assert app.error_jump == 5
        assert "1 passed" in app._note.plain


async def test_progress_screen_opens(tmp_path: Path) -> None:
    app = Pytobs(path=tmp_path / "p.py", python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("ctrl+g")
        await pilot.pause(0.2)
        assert type(app.screen).__name__ == "ProgressScreen"
        await pilot.press("escape")
        assert type(app.screen).__name__ != "ProgressScreen"


async def test_tabs_keep_their_own_text_cursor_and_undo(tmp_path: Path) -> None:
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("x = 1\n")
    b.write_text("y = 2\n")
    app = Pytobs(path=a, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        app.open_file(b)
        await pilot.pause()
        assert [t.path.name for t in app.tabs] == ["a.py", "b.py"] and app.active == 1
        app.editor.move_cursor((0, 5))
        await pilot.press("9")
        assert app.editor.text == "y = 29\n"
        await pilot.press("alt+left")
        assert app.file_path == a.resolve() and app.editor.text == "x = 1\n"
        assert b.read_text() == "y = 29\n"  # saved when switching away
        await pilot.press("alt+right")
        assert app.editor.text == "y = 29\n" and app.editor.cursor_location == (0, 6)
        await pilot.press("ctrl+z")
        assert app.editor.text == "y = 2\n"  # undo history survived the switch
        app.open_file(a)  # already open: just focuses it, no duplicate tab
        assert len(app.tabs) == 2 and app.active == 0


async def test_close_tab_and_click_tab(tmp_path: Path) -> None:
    files = [tmp_path / f"f{i}.py" for i in range(3)]
    for f in files:
        f.write_text(f"# {f.name}\n")
    app = Pytobs(path=files[0], python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        app.open_file(files[1])
        app.open_file(files[2])
        await pilot.pause()
        await pilot.press("alt+1")
        assert app.active == 0
        bar = app.query_one("TabBar")
        x0, _, index, _ = next(h for h in bar.hits if h[2] == 2 and not h[3])
        await pilot.click("#tabline", offset=(x0 + 2, 0))
        assert app.active == 2
        await pilot.press("ctrl+w")
        assert [t.path.name for t in app.tabs] == ["f0.py", "f1.py"] and app.active == 1
        await pilot.press("ctrl+w", "ctrl+w")
        assert len(app.tabs) == 1 and "scratch" in str(app.file_path)  # never zero tabs


async def test_open_tabs_come_back_next_time(tmp_path: Path) -> None:
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text("")
    b.write_text("")
    app = Pytobs(path=a, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        app.open_file(b)
        await pilot.press("alt+left")
    again = Pytobs(python=sys.executable)
    async with again.run_test(size=(120, 30)):
        assert [t.path.name for t in again.tabs] == ["a.py", "b.py"]
        assert again.file_path == a.resolve()


async def test_select_and_copy_output(tmp_path: Path) -> None:
    from textual.geometry import Offset
    from textual.selection import Selection

    script = tmp_path / "out.py"
    script.write_text('print("first line")\nprint("second " + "x" * 80)\nprint("third")\n')
    app = Pytobs(path=script, python=sys.executable)
    copied: list[str] = []
    app.copy_to_clipboard = copied.append  # type: ignore[method-assign]
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("ctrl+r")
        await _wait(app, pilot)
        out = app.output
        # select from the start of line 1 to the end of the wrapped second line
        last_piece = max(i for i, (logical, _) in enumerate(out._wrapped) if logical == 1)
        app.screen.selections = {
            out: Selection(Offset(0, 0), Offset(len(out._wrapped[last_piece][1]), last_piece))
        }
        assert app.screen.get_selected_text() == "first line\nsecond " + "x" * 80
        await pilot.press("ctrl+c")
        assert copied == ["first line\nsecond " + "x" * 80]
        app.action_copy_output()
        assert copied[-1] == "first line\nsecond " + "x" * 80 + "\nthird"


async def _settle(pilot, n: int = 3) -> None:
    for _ in range(n):
        await pilot.pause(0.05)


async def test_select_all_and_delete_many_lines(tmp_path: Path) -> None:
    script = tmp_path / "s.py"
    script.write_text("a = 1\nb = 2\nc = 3\nd = 4\n")
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        editor = app.editor
        editor.move_cursor((1, 2))
        await pilot.press("shift+down")  # selection touches lines 2 and 3
        await pilot.press("ctrl+shift+k")
        assert editor.text == "a = 1\nd = 4\n"
        await pilot.press("ctrl+a")
        assert editor.selected_text == editor.text
        await pilot.press("backspace")
        assert editor.text == ""


async def test_fold_hides_block_and_cursor_skips_it(tmp_path: Path) -> None:
    script = tmp_path / "f.py"
    script.write_text("x = 1\nif x:\n    y = 2\n    z = 3\nprint(x)\n")
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        editor = app.editor
        editor.move_cursor((2, 4))
        await pilot.press("f9")
        assert editor.folds == {1: 3} and editor.cursor_location[0] == 1
        assert editor.wrapped_document.height == 4  # rows 0, 1, 4 and the empty last line
        await pilot.press("down")
        assert editor.cursor_location[0] == 4  # jumped over the folded lines
        await pilot.press("up")
        assert editor.cursor_location[0] == 1
        await pilot.press("end", "space")  # typing on the header keeps the fold
        assert editor.folds == {1: 3}
        await pilot.press("f9")
        assert editor.folds == {} and editor.wrapped_document.height == 6
        editor.fold_all()
        assert editor.folds == {1: 3}
        editor.move_cursor((3, 0))  # jumping into a folded block opens it
        assert editor.folds == {}


async def test_snippet_and_tab_stops(tmp_path: Path) -> None:
    app = Pytobs(path=tmp_path / "s.py", python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        await _type(pilot, "for")
        await pilot.press("tab")
        editor = app.editor
        assert editor.text == "for item in items:\n    pass"
        assert editor.selected_text == "item"
        await _type(pilot, "n")
        await pilot.press("tab")
        assert editor.selected_text == "items"
        await _type(pilot, "nums")
        await pilot.press("tab")
        assert editor.selected_text == "pass"
        assert editor.text == "for n in nums:\n    pass"


async def test_move_lines(tmp_path: Path) -> None:
    script = tmp_path / "m.py"
    script.write_text("one\ntwo\nthree\n")
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        app.editor.move_cursor((0, 1))
        await pilot.press("alt+down")
        assert app.editor.text == "two\none\nthree\n" and app.editor.cursor_location == (1, 1)
        await pilot.press("alt+up")
        assert app.editor.text == "one\ntwo\nthree\n"


async def test_new_file_save_as_and_rename(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    a.write_text("")
    app = Pytobs(path=a, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("ctrl+n")
        await _settle(pilot)
        await _type(pilot, "week2/loops")
        await pilot.press("enter")
        await _settle(pilot)
        made = tmp_path / "week2" / "loops.py"
        assert made.is_file() and app.file_path == made.resolve()
        app.action_rename_file()
        await _settle(pilot)
        field = app.screen.query_one(Input)
        field.value = "for_loops.py"
        await pilot.press("enter")
        await _settle(pilot)
        assert not made.exists() and app.file_path == (tmp_path / "week2" / "for_loops.py").resolve()
        # a scratch file: Ctrl+S asks for a name and moves it next to your files
        app.action_new_scratch()
        await _settle(pilot)
        scratch = app.file_path
        await _type(pilot, "x = 1")
        await pilot.press("ctrl+s")
        await _settle(pilot)
        await _type(pilot, "keep")
        await pilot.press("enter")
        await _settle(pilot)
        kept = tmp_path / "week2" / "keep.py"
        assert kept.read_text() == "x = 1" and app.file_path == kept.resolve()
        assert not scratch.exists()


async def test_outline_and_go_to_line(tmp_path: Path) -> None:
    script = tmp_path / "o.py"
    script.write_text("def add(a, b):\n    return a + b\n\nclass Cat:\n    def meow(self):\n        pass\n")
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("ctrl+o")
        await _settle(pilot)
        await _type(pilot, "meow")
        await pilot.press("enter")
        await _settle(pilot)
        assert app.editor.cursor_location == (4, 4)
        await pilot.press("ctrl+o")
        await _settle(pilot)
        await _type(pilot, ":2")
        await pilot.press("enter")
        await _settle(pilot)
        assert app.editor.cursor_location == (1, 4)


async def test_find_and_replace(tmp_path: Path) -> None:
    script = tmp_path / "r.py"
    script.write_text("cat = 1\nprint(cat)\nconcat = cat\n")
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("ctrl+f")
        await _settle(pilot)
        await _type(pilot, "cat")
        await _settle(pilot)
        editor = app.editor
        assert len(editor.matches) == 4 and editor.selected_text == "cat"
        await pilot.press("enter")
        assert editor.match_index == 1 and editor.cursor_location == (1, 9)
        app.query_one("#replace", Input).value = "dog"
        app.action_replace_all()
        await _settle(pilot)
        assert editor.text == "dog = 1\nprint(dog)\ncondog = dog\n"
        await pilot.press("escape")
        assert not app.query_one("FindBar").has_class("show") and editor.has_focus


async def test_rename_variable_only_as_a_name(tmp_path: Path) -> None:
    script = tmp_path / "v.py"
    script.write_text('n = 1\nprint("n is", n)  # n\nnn = n + 1\n')
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        app.editor.move_cursor((0, 0))
        await pilot.press("f2")
        await _settle(pilot)
        app.screen.query_one(Input).value = "count"
        await pilot.press("enter")
        await _settle(pilot)
        assert app.editor.text == 'count = 1\nprint("n is", count)  # n\nnn = count + 1\n'


async def test_explain_word_and_go_to_definition(tmp_path: Path) -> None:
    script = tmp_path / "h.py"
    script.write_text("def double(x):\n    return x * 2\n\nprint(double(3))\n")
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        for _ in range(200):  # wait for the completion process
            await pilot.pause(0.05)
            if app.completion.alive and app.completion.python:
                break
        app.editor.move_cursor((3, 2))
        await pilot.press("f1")
        for _ in range(100):
            await pilot.pause(0.05)
            if type(app.screen).__name__ == "HelpCard":
                break
        assert type(app.screen).__name__ == "HelpCard"
        assert "Shows values" in app.screen.body.plain
        await pilot.press("escape")
        app.editor.move_cursor((3, 8))
        await pilot.press("f12")
        for _ in range(100):
            await pilot.pause(0.05)
            if app.editor.cursor_location[0] == 0:
                break
        assert app.editor.cursor_location == (0, 4)
        await pilot.press("shift+f12")
        assert app.editor.cursor_location == (3, 8)


async def test_files_sidebar(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    a.write_text("")
    (tmp_path / "b.py").write_text("print(2)\n")
    app = Pytobs(path=a, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.press("alt+e")
        await _settle(pilot, 6)
        tree = app.query_one("FileTree")
        assert tree.has_focus
        names = [n.label.plain for n in tree.root.children]
        assert "b.py" in names and "ruff.toml" in names


async def test_hide_output_and_running_brings_it_back(tmp_path: Path) -> None:
    script = tmp_path / "o.py"
    script.write_text('print("hi")\n')
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        col = app.query_one("#output-col")
        editor_width = app.query_one("#editor-col").size.width
        await pilot.press("ctrl+j")
        await _settle(pilot)
        assert not col.display and app.query_one("#editor-col").size.width > editor_width
        await pilot.press("ctrl+r")
        await _wait(app, pilot)
        assert col.display


async def test_room_below_code_and_go_to_missing_line(tmp_path: Path) -> None:
    script = tmp_path / "e.py"
    script.write_text("x = 1\n")
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        editor = app.editor
        await pilot.click("#editor", offset=(10, 12))  # empty space under the code
        assert editor.cursor_location == (12, 0) and editor.document.line_count == 13
        await _type(pilot, "y = 2")
        app.save()
        assert script.read_text() == "x = 1\n" + "\n" * 11 + "y = 2"
        await pilot.press("ctrl+z")
        app.save()
        assert script.read_text() == "x = 1\n"  # empty lines below the code are never written
        await pilot.press("ctrl+o")
        await _settle(pilot)
        await _type(pilot, ":40")
        await pilot.press("enter")
        await _settle(pilot)
        assert editor.cursor_location == (39, 0)


async def test_full_ruff_message_on_f1(tmp_path: Path) -> None:
    script = tmp_path / "w.py"
    script.write_text("import os\nprint(1)\n")
    app = Pytobs(path=script, python=sys.executable)
    async with app.run_test(size=(120, 30)) as pilot:
        for _ in range(100):
            await pilot.pause(0.05)
            if app.diags:
                break
        assert "F401" in [d.code for d in app.diags]
        app.editor.move_cursor((0, 3))
        await pilot.press("f1")
        for _ in range(100):
            await pilot.pause(0.05)
            if type(app.screen).__name__ == "HelpCard":
                break
        card = app.screen
        assert type(card).__name__ == "HelpCard"
        text = "".join(r.plain for r in card.body.renderables if hasattr(r, "plain"))
        assert "F401" in text and "`os` imported but unused" in text and "import os" in text
        assert any(type(r).__name__ == "Markdown" for r in card.body.renderables)  # ruff's own explanation
        await pilot.press("down")
        assert type(app.screen).__name__ == "HelpCard"  # arrows scroll, they don't close
        await pilot.press("escape")
        assert type(app.screen).__name__ != "HelpCard"
