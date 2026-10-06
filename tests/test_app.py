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
