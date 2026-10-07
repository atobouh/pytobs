"""Drive the real app headless with Textual's pilot."""

import sys
from pathlib import Path

import pytest

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
