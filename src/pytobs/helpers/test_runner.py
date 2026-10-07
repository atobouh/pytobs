"""pytobs test runner. Runs inside the user's own Python, so it uses only the standard library
and syntax that works on Python 3.8+.

usage: python -u test_runner.py RESULTS.json SCRIPT.py

Imports SCRIPT (top-level code runs, `if __name__ == "__main__":` blocks don't), then calls every
function named test_* defined in it, in file order, and writes the results as JSON.
"""

import ast
import inspect
import json
import os
import runpy
import sys
import time
import traceback

MAX_REPR = 200


def short(value):
    try:
        text = repr(value)
    except Exception as exc:  # a broken __repr__ must not break the runner
        text = f"<repr failed: {type(exc).__name__}>"
    return text if len(text) <= MAX_REPR else text[: MAX_REPR - 1] + "…"


def script_frame(tb, script):
    """Deepest traceback entry inside the user's script."""
    found = None
    while tb is not None:
        if os.path.normcase(os.path.abspath(tb.tb_frame.f_code.co_filename)) == script:
            found = tb
        tb = tb.tb_next
    return found


def assert_details(tree, entry):
    """For `assert left <op> right`, evaluate both sides again to show expected vs got."""
    if tree is None or entry is None:
        return None
    line = entry.tb_lineno
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and node.lineno <= line <= getattr(node, "end_lineno", node.lineno):
            test = node.test
            if isinstance(test, ast.Compare) and len(test.ops) == 1:
                frame = entry.tb_frame
                try:
                    left = eval(
                        compile(ast.Expression(test.left), "<assert>", "eval"),
                        frame.f_globals,
                        frame.f_locals,
                    )
                    right = eval(
                        compile(ast.Expression(test.comparators[0]), "<assert>", "eval"),
                        frame.f_globals,
                        frame.f_locals,
                    )
                except Exception:
                    return None
                op = type(test.ops[0]).__name__
                return {"op": op, "got": short(left), "expected": short(right)}
            return None
    return None


def run_test(name, fn, script, tree):
    start = time.perf_counter()
    result = {"name": name, "line": fn.__code__.co_firstlineno}
    try:
        fn()
        result["status"] = "pass"
    except AssertionError as exc:
        entry = script_frame(exc.__traceback__, script)
        result["status"] = "fail"
        result["message"] = str(exc)
        if entry is not None:
            result["line"] = entry.tb_lineno
        details = assert_details(tree, entry)
        if details:
            result.update(details)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        entry = script_frame(exc.__traceback__, script)
        result["status"] = "error"
        result["message"] = f"{type(exc).__name__}: {exc}"
        if entry is not None:
            result["line"] = entry.tb_lineno
    result["seconds"] = time.perf_counter() - start
    return result


def collect(namespace, script):
    tests = []
    for name, obj in list(namespace.items()):
        if name.startswith("test") and inspect.isfunction(obj):
            code = obj.__code__
            if os.path.normcase(os.path.abspath(code.co_filename)) == script and code.co_argcount == 0:
                tests.append((code.co_firstlineno, name, obj))
        elif name.startswith("Test") and inspect.isclass(obj):
            try:
                instance = obj()
            except Exception:
                continue
            for attr in sorted(vars(obj)):
                method = getattr(instance, attr, None)
                if attr.startswith("test") and inspect.ismethod(method):
                    tests.append((method.__func__.__code__.co_firstlineno, f"{name}.{attr}", method))
    tests.sort(key=lambda t: t[0])
    return [(name, fn) for _, name, fn in tests]


def main():
    results_path, script = sys.argv[1], os.path.normcase(os.path.abspath(sys.argv[2]))
    sys.argv = [sys.argv[2]]
    sys.path.insert(0, os.path.dirname(script))
    try:
        with open(script, encoding="utf-8-sig") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError, ValueError):
        tree = None
    try:
        namespace = runpy.run_path(sys.argv[0], run_name="__pytobs_tests__")
    except SystemExit:
        namespace = {}
    except BaseException as exc:
        # Loading the file failed: show the normal traceback (pytobs explains it) and stop.
        tb = exc.__traceback__
        while tb is not None and os.path.normcase(os.path.abspath(tb.tb_frame.f_code.co_filename)) != script:
            tb = tb.tb_next
        traceback.print_exception(type(exc), exc, tb or exc.__traceback__)
        sys.exit(1)
    start = time.perf_counter()
    results = [run_test(name, fn, script, tree) for name, fn in collect(namespace, script)]
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({"tests": results, "seconds": time.perf_counter() - start}, f)
    sys.exit(0 if all(r["status"] == "pass" for r in results) else 1)


if __name__ == "__main__":
    main()
