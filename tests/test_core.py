import asyncio
import sys
from pathlib import Path

import pytest

from pytobs import env, lint, tracebacks
from pytobs.runner import Run


def test_parse_key_error(tmp_path: Path) -> None:
    script = tmp_path / "people.py"
    raw = (
        "Traceback (most recent call last):\n"
        f'  File "{script}", line 13, in <module>\n'
        '    print(person["name"], person["agee"])\n'
        "                          ~~~~~~^^^^^^^^\n"
        "KeyError: 'agee'\n"
    )
    err = tracebacks.parse(raw)
    assert err is not None
    assert err.exception == "KeyError: 'agee'"
    assert err.frames[0].line == 13
    assert err.frames[0].code[1].strip().startswith("~")
    script.write_text("x")
    assert tracebacks.jump_target(err, script) == 13


def test_parse_syntax_error(tmp_path: Path) -> None:
    script = tmp_path / "a.py"
    raw = f'  File "{script}", line 3\n    print("hi"\n         ^\nSyntaxError: \'(\' was never closed\n'
    err = tracebacks.parse(raw)
    assert err is not None
    assert err.exception.startswith("SyntaxError")
    assert err.frames[0].line == 3 and err.frames[0].func is None


def test_parse_chained_keeps_last(tmp_path: Path) -> None:
    raw = (
        "Traceback (most recent call last):\n"
        '  File "a.py", line 1, in <module>\n'
        "KeyError: 'x'\n\n"
        "During handling of the above exception, another exception occurred:\n\n"
        "Traceback (most recent call last):\n"
        '  File "a.py", line 4, in <module>\n'
        "ValueError: boom\n"
    )
    err = tracebacks.parse(raw)
    assert err and err.exception == "ValueError: boom" and err.frames[-1].line == 4


def test_library_frames_are_not_user_frames(tmp_path: Path) -> None:
    script = tmp_path / "main.py"
    script.write_text("")
    user = tracebacks.Frame(str(script), 1, "<module>")
    lib = tracebacks.Frame("/x/site-packages/requests/api.py", 10, "get")
    assert tracebacks.is_user_frame(user, script)
    assert not tracebacks.is_user_frame(lib, script)


def test_finds_nearest_venv(tmp_path: Path) -> None:
    venv_python = tmp_path / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("")
    sub = tmp_path / "pkg"
    sub.mkdir()
    found = env.find_interpreter(sub / "main.py")
    assert found.source == ".venv" and Path(found.executable) == venv_python


def test_override_wins(tmp_path: Path) -> None:
    assert env.find_interpreter(tmp_path / "a.py", "/custom/python").source == "config"


async def _run(script: Path, stdin: str | None = None, stop_after: float | None = None):
    chunks: list[tuple[str, str]] = []
    done: asyncio.Future = asyncio.get_running_loop().create_future()
    run = Run(
        sys.executable, script, lambda t, s: chunks.append((t, s)), lambda c, sec: done.set_result((c, sec))
    )
    await run.start()
    if stdin is not None:
        await asyncio.sleep(0.3)
        run.send_input(stdin)
    if stop_after is not None:
        await asyncio.sleep(stop_after)
        await run.stop()
    code, _ = await asyncio.wait_for(done, 15)
    out = "".join(t for t, s in chunks if s == "stdout")
    err = "".join(t for t, s in chunks if s == "stderr")
    return code, out, err


async def test_run_streams_output_and_input(tmp_path: Path) -> None:
    script = tmp_path / "hello.py"
    script.write_text('name = input("your name: ")\nprint(f"hello, {name}")\n')
    code, out, _ = await _run(script, stdin="Ada\n")
    assert code == 0
    assert out == "your name: hello, Ada\n"


async def test_run_reports_errors(tmp_path: Path) -> None:
    script = tmp_path / "bad.py"
    script.write_text("x = {}\nprint(x['nope'])\n")
    code, _, err = await _run(script)
    assert code == 1
    parsed = tracebacks.parse(err)
    assert parsed and parsed.exception == "KeyError: 'nope'"
    assert tracebacks.jump_target(parsed, script) == 2


async def test_stop_ends_a_busy_program(tmp_path: Path) -> None:
    script = tmp_path / "loop.py"
    script.write_text("import time\nwhile True:\n    time.sleep(0.05)\n")
    code, _, _ = await _run(script, stop_after=0.5)
    assert code != 0


async def test_lint_reports_undefined_name(tmp_path: Path) -> None:
    (tmp_path / "ruff.toml").write_text("")  # isolate from any user-level ruff config
    diags = await lint.check("print(undefined_thing)\n", tmp_path / "a.py")
    assert [(d.row, d.code, d.error) for d in diags] == [(0, "F821", True)]


async def test_format(tmp_path: Path) -> None:
    (tmp_path / "ruff.toml").write_text("")
    assert await lint.format_source("x=1\n", tmp_path / "a.py") == "x = 1\n"
    assert await lint.format_source("def (:\n", tmp_path / "a.py") is None


@pytest.mark.parametrize("source", ["import os\nos.path.joi", "import json\njson.lo"])
async def test_completion_worker(source: str, tmp_path: Path) -> None:
    from pytobs.completion.client import CompletionClient

    client = CompletionClient()
    await client.start(sys.executable)
    try:
        lines = source.split("\n")
        items = await client.request(
            "complete",
            source=source,
            line=len(lines),
            col=len(lines[-1]),
            path=str(tmp_path / "a.py"),
            timeout=60,
        )
        names = [i["name"] for i in items]
        assert names and all(n.startswith(lines[-1].split(".")[-1]) for n in names[:2])
        doc = await client.request("doc", name=names[0], timeout=30)
        assert doc and (doc["signatures"] or doc["doc"])
    finally:
        await client.close()
