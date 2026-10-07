"""Run real snippets through real Python and check each error gets a specific explanation."""

import subprocess
import sys
from pathlib import Path

import pytest

from pytobs import explain, tracebacks

CASES = {
    "builtin_arg_count": (
        'friends = ["a"]\nprint(friends.count())\n',
        "takes exactly one value",
        "friends.count(x)",
    ),
    "missing_arg": ("def greet(name):\n    print(name)\ngreet()\n", "needs a value for name", "greet(name)"),
    "too_many": ("def greet(name):\n    pass\ngreet('a', 'b')\n", "accepts 1 value", None),
    "self_missing": ("class P:\n    def hi():\n        pass\nP().hi()\n", "missing self", None),
    "concat": ('n = 3\nprint("n=" + n)\n', "joins text only", "str(total)"),
    "input_math": ("age = '3'\nprint(age + 1)\n", "joins text only", "int(text)"),
    "str_plus_int": ("age = '3'\nprint(1 + age)\n", "Text that looks like a number", None),
    "none_subscript": ("x = [3, 1].sort()\nprint(x[0])\n", "returned nothing", None),
    "shadow_list": ("list = [1, 2]\nprint(list((3,)))\n", "replaces Python's built-in list", None),
    "int_iter": ("for i in 5:\n    pass\n", "needs a sequence", "range(n)"),
    "no_len": ("print(len(5))\n", "len() works on", None),
    "str_index": ('items = [1]\nprint(items["0"])\n', "whole numbers", None),
    "str_assign": ('t = "abc"\nt[0] = "x"\n', "can't be changed", None),
    "name_typo": ("counter = 1\nprint(countr)\n", "typo for counter", "counter"),
    "name_module": ("print(math.pi)\n", "Import it", "import math"),
    "name_true": ("x = true\n", "capital letter", "True"),
    "unbound": ("n = 0\ndef f():\n    n += 1\nf()\n", "local variable", None),
    "none_attr": ("x = [1]\nx = x.append(2)\nx.append(3)\n", "returns None", None),
    "push": ("x = []\nx.push(1)\n", ".append(x)", "x.append(x)"),
    "index": ("x = [1, 2, 3]\nprint(x[3])\n", "Positions start at 0", "items[-1]"),
    "key": ('person = {"name": "Ada"}\nprint(person["agee"])\n', "no key 'agee'", 'person.get("agee")'),
    "int_literal": ('int("3.5")\n', "whole-number text", "float(text)"),
    "unpack": ("a, b = [1, 2, 3]\n", "same count", None),
    "not_in_list": ("[1].remove(5)\n", "isn't in the list", None),
    "zero": ("print(1 / 0)\n", "divisor was 0", None),
    "never_closed": ('print("hi"\n', "never comes", None),
    "colon": ("if True\n    pass\n", "end with a colon", None),
    "unterminated": ('x = "abc\n', "never ends", None),
    "eq": ("if x = 3:\n    pass\n", "== compares", None),
    "indent": ("if True:\nprint(1)\n", "indented line", None),
    "unexpected_indent": ("x = 1\n    y = 2\n", "isn't inside a block", None),
    "module": ("import surely_not_a_module_xyz\n", "isn't installed", None),
    "file": ('open("missing-file.txt")\n', "runs your script from its own folder", None),
    "recursion": ("def f():\n    f()\nf()\n", "never stops", None),
    "assert": ("assert 1 == 2\n", "was False", None),
    "return_outside": ("return 5\n", "only works inside a def", None),
}


def _error(tmp_path: Path, name: str, code: str) -> tuple[tracebacks.ParsedError, Path]:
    script = tmp_path / f"{name}.py"
    script.write_text(code)
    out = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=tmp_path, timeout=30
    )
    err = tracebacks.parse(out.stderr)
    assert err is not None, out.stderr
    return err, script


@pytest.mark.parametrize("name", sorted(CASES))
def test_specific_explanation(name: str, tmp_path: Path) -> None:
    code, meaning_part, try_part = CASES[name]
    err, script = _error(tmp_path, name, code)
    note = explain.explain(err, script, code)
    assert note is not None, err.exception
    assert meaning_part in note.meaning, (err.exception, note.meaning)
    if try_part:
        assert any(try_part in t for t, _ in note.tries), (err.exception, note.tries)


def test_file_named_like_module(tmp_path: Path) -> None:
    code = "import random\nprint(random.randint(1, 3))\n"
    err, script = _error(tmp_path, "random", code)
    note = explain.explain(err, script, code)
    assert note and "Your file is named random.py" in note.meaning


def test_unknown_error_type_gets_nothing(tmp_path: Path) -> None:
    code = "class Oops(Exception):\n    pass\nraise Oops('x')\n"
    err, script = _error(tmp_path, "custom", code)
    assert explain.explain(err, script, code) is None
