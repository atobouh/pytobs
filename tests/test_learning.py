"""Watch it run, tests panel and progress stats."""

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pytobs.stats import Stats, level
from pytobs.trace_view import Trace, render_step

HELPERS = Path(__file__).resolve().parents[1] / "src" / "pytobs" / "helpers"

LOOPS = """friends = ["Ada", "Grace", "Linus"]
lengths = {}


def size(word):
    return len(word)


for name in friends:
    lengths[name] = size(name)

print(lengths)
"""


def _trace(tmp_path: Path, source: str) -> tuple[dict, subprocess.CompletedProcess]:
    script = tmp_path / "loops.py"
    script.write_text(source)
    out = tmp_path / "trace.json"
    proc = subprocess.run(
        [sys.executable, "-u", str(HELPERS / "trace_runner.py"), str(out), str(script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(out.read_text()), proc


def test_trace_records_lines_calls_and_output(tmp_path: Path) -> None:
    data, proc = _trace(tmp_path, LOOPS)
    assert proc.stdout == "{'Ada': 3, 'Grace': 5, 'Linus': 5}\n"
    steps = data["steps"]
    assert [s["l"] for s in steps[:5]] == [1, 2, 5, 9, 10]
    assert steps[5]["f"] == "size" and steps[5]["s"] == ["<module>", "size"]
    assert any(s["k"] == "return" and s["ret"] == "5" for s in steps)
    assert not any(s["k"] == "return" and s["f"] == "<module>" for s in steps)


def test_trace_view_points_at_loop_item(tmp_path: Path) -> None:
    data, _ = _trace(tmp_path, LOOPS)
    trace = Trace.from_json(data, LOOPS)
    # first time on line 10 with name == "Grace"
    i = next(k for k, s in enumerate(trace.steps) if s["l"] == 10 and s["v"]["name"]["r"] == "'Grace'")
    text = render_step(trace, i, LOOPS.split("\n"), 60).plain
    assert "line 10  lengths[name] = size(name)" in text
    assert "▲ name" in text
    lines = text.split("\n")
    idx_row = next(n for n, line in enumerate(lines) if "▲ name" in line) - 1
    assert lines[idx_row + 1].index("▲") == lines[idx_row].index("1")  # arrow under index 1


def test_trace_stops_recording_but_program_finishes(tmp_path: Path) -> None:
    data, proc = _trace(tmp_path, "total = 0\nfor i in range(20000):\n    total += i\nprint(total)\n")
    assert data["truncated"] and len(data["steps"]) == data["max_steps"]
    assert proc.stdout.strip() == str(sum(range(20000)))


def test_trace_reports_exception(tmp_path: Path) -> None:
    data, proc = _trace(tmp_path, "x = [1]\nprint(x[5])\n")
    assert data["exception"] == "IndexError: list index out of range"
    assert "IndexError" in proc.stderr and "trace_runner" not in proc.stderr


def test_test_runner(tmp_path: Path) -> None:
    script = tmp_path / "count.py"
    script.write_text(
        "def double(x):\n    return x * 2\n\n"
        "def test_ok():\n    assert double(2) == 4\n\n"
        "def test_bad():\n    assert double(2) == 5\n\n"
        "def test_crash():\n    [][1]\n\n"
        "if __name__ == '__main__':\n    raise SystemExit('main block must not run')\n"
    )
    out = tmp_path / "r.json"
    proc = subprocess.run(
        [sys.executable, "-u", str(HELPERS / "test_runner.py"), str(out), str(script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1
    tests = {t["name"]: t for t in json.loads(out.read_text())["tests"]}
    assert tests["test_ok"]["status"] == "pass"
    assert tests["test_bad"] | {} and tests["test_bad"]["status"] == "fail"
    assert (tests["test_bad"]["got"], tests["test_bad"]["expected"], tests["test_bad"]["line"]) == (
        "4",
        "5",
        8,
    )
    assert tests["test_crash"]["status"] == "error" and tests["test_crash"]["message"].startswith(
        "IndexError"
    )


def test_stats_streak_week_and_fixed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    stats = Stats()
    today = dt.date.today()
    for back in (1, 2):
        stats.days[(today - dt.timedelta(days=back)).isoformat()] = {
            "runs": 3,
            "errors": 0,
            "fixed": 0,
            "seconds": 60,
        }
    stats.record_run("a.py", "TypeError", "function arguments")
    stats.record_run("a.py", None)
    s = stats.summary()
    assert s.streak == 3
    assert s.fixed_total == 1
    assert s.top_errors == [("TypeError", 1, "function arguments")]
    assert s.heat[today.weekday()][-1] == 2
    stats.save()
    assert Stats.load().errors == {"TypeError": 1}
    assert [level(n) for n in (0, 1, 3, 7, 50)] == [0, 1, 2, 3, 4]
    stats._last_touch = 0.0  # independent of how long the machine has been up
    stats.touch(100.0)
    stats.touch(130.0)
    stats.touch(1000.0)  # idle gap is not counted
    assert stats.days[today.isoformat()]["seconds"] == 30
