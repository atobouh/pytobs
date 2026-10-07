"""pytobs step recorder for "Watch it run". Runs inside the user's own Python, so it uses only
the standard library and syntax that works on Python 3.8+.

usage: python -u trace_runner.py TRACE.json SCRIPT.py

Runs SCRIPT normally (output and input work as usual) while recording, for every line executed in
SCRIPT itself, the line number, the function and the variables in scope. Library code is not
recorded. Recording stops after MAX_STEPS; the program keeps running.
"""

import json
import os
import reprlib
import sys
import traceback
import types

MAX_STEPS = 5000
MAX_VARS = 24
MAX_ITEMS = 10

_repr = reprlib.Repr()
_repr.maxstring = 60
_repr.maxother = 60
_repr.maxlist = 8
_repr.maxtuple = 8
_repr.maxset = 8
_repr.maxdict = 6
_repr.maxlevel = 2

HIDDEN_TYPES = (types.ModuleType, types.FunctionType, types.BuiltinFunctionType, type, types.MethodType)


def short(value, limit=80):
    try:
        text = _repr.repr(value)
    except Exception as exc:  # a broken __repr__ must not break the recording
        text = f"<{type(exc).__name__}>"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize(value):
    info = {"t": type(value).__name__, "r": short(value)}
    if isinstance(value, (list, tuple)) and len(value) <= MAX_ITEMS:
        info["items"] = [short(v, 24) for v in value]
        info["n"] = len(value)
    elif isinstance(value, dict) and len(value) <= MAX_ITEMS:
        info["map"] = [[short(k, 24), short(v, 32)] for k, v in list(value.items())[:MAX_ITEMS]]
        info["n"] = len(value)
    elif isinstance(value, (list, tuple, dict, set, str)):
        info["n"] = len(value)
    return info


def main():
    trace_path, script = sys.argv[1], os.path.abspath(sys.argv[2])
    target = os.path.normcase(script)
    sys.argv = [sys.argv[2]]
    sys.path.insert(0, os.path.dirname(script))

    steps = []
    output = []  # [step index, text]
    stack = []  # function names of the user frames currently running
    state = {"done": False, "truncated": False, "exception": None}

    def variables(frame):
        names = frame.f_locals if frame.f_code.co_name != "<module>" else frame.f_globals
        out = {}
        for name, value in list(names.items()):
            if name.startswith("__") or isinstance(value, HIDDEN_TYPES):
                continue
            out[name] = summarize(value)
            if len(out) >= MAX_VARS:
                break
        return out

    def record(frame, kind, extra=None):
        if len(steps) >= MAX_STEPS:
            state["truncated"] = True
            state["done"] = True
            sys.settrace(None)
            return
        step = {
            "k": kind,
            "l": frame.f_lineno,
            "f": frame.f_code.co_name,
            "s": list(stack),
            "v": variables(frame),
        }
        if extra:
            step.update(extra)
        steps.append(step)

    def local_trace(frame, event, arg):
        if state["done"]:
            return None
        if event == "line":
            record(frame, "line")
        elif event == "return":
            if frame.f_code.co_name != "<module>":
                record(frame, "return", {"ret": short(arg)})
            if stack:
                stack.pop()
        return local_trace

    def global_trace(frame, event, arg):
        if state["done"] or event != "call":
            return None
        if os.path.normcase(os.path.abspath(frame.f_code.co_filename)) != target:
            return None
        stack.append(frame.f_code.co_name)
        return local_trace

    class Tee:
        def __init__(self, real):
            self.real = real

        def write(self, text):
            output.append([len(steps), text])
            return self.real.write(text)

        def flush(self):
            self.real.flush()

        def __getattr__(self, name):
            return getattr(self.real, name)

    with open(script, encoding="utf-8-sig") as f:
        source = f.read()
    code = compile(source, script, "exec")
    namespace = {"__name__": "__main__", "__file__": script, "__builtins__": __builtins__}
    real_stdout = sys.stdout
    sys.stdout = Tee(real_stdout)
    exit_code = 0
    sys.settrace(global_trace)
    try:
        exec(code, namespace)
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 0
    except BaseException as exc:
        sys.settrace(None)
        state["exception"] = f"{type(exc).__name__}: {exc}"
        tb = exc.__traceback__.tb_next if exc.__traceback__ else None
        traceback.print_exception(type(exc), exc, tb)
        exit_code = 1
    finally:
        sys.settrace(None)
        sys.stdout = real_stdout
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "steps": steps,
                    "output": output,
                    "truncated": state["truncated"],
                    "exception": state["exception"],
                    "max_steps": MAX_STEPS,
                },
                f,
            )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
