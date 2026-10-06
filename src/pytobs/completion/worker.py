"""Completion worker: runs Jedi in its own process so the editor never waits on it.

Protocol: one JSON object per line on stdin, one JSON reply per line on stdout.
  {"id": 1, "op": "env", "python": "C:/.../python.exe"}
  {"id": 2, "op": "complete", "source": "...", "line": 3, "col": 7, "path": "..."}
  {"id": 3, "op": "doc", "name": "loads"}            (from the last completion list)
  {"id": 4, "op": "signature", "source": ..., "line": ..., "col": ..., "path": ...}
  {"id": 5, "op": "warm", "source": ..., "path": ...}
"""

from __future__ import annotations

import json
import sys
from typing import Any

import jedi

KIND = {
    "function": "ƒ",
    "class": "c",
    "module": "m",
    "instance": "·",
    "statement": "·",
    "param": "p",
    "keyword": "k",
    "property": "·",
    "path": "/",
}

_env: Any = None
_last: dict[str, Any] = {}


def _script(msg: dict[str, Any]) -> jedi.Script:
    return jedi.Script(msg["source"], path=msg.get("path"), environment=_env)


def _first_paragraphs(doc: str, limit: int = 12) -> str:
    """Reflow hard-wrapped docstring paragraphs; keep indented (code) lines as they are."""
    out: list[str] = []
    para: list[str] = []
    for raw in doc.replace("``", "`").strip().splitlines():
        line = raw.rstrip()
        if not line.strip() or line.startswith((" ", "\t", ">>>")):
            if para:
                out.append(" ".join(para))
                para = []
            out.append(line)
        else:
            para.append(line.strip())
    if para:
        out.append(" ".join(para))
    cleaned: list[str] = []
    for line in out:
        if line or (cleaned and cleaned[-1]):
            cleaned.append(line)
    return "\n".join(cleaned[:limit]).rstrip() + ("\n…" if len(cleaned) > limit else "")


def _param(p: Any) -> str:
    """`name`, `name=default`, `*args` or `**kwargs`: no type annotations, they drown learners."""
    kind = str(getattr(p, "kind", ""))
    name = p.name
    if "VAR_POSITIONAL" in kind:
        return "*" + name
    if "VAR_KEYWORD" in kind:
        return "**" + name
    text = p.to_string()
    if "=" in text:
        default = text.rsplit("=", 1)[1].strip()
        if len(default) > 14:
            default = "…"
        return f"{name}={default}"
    return name


def _params(sig: Any) -> list[str]:
    out: list[str] = []
    star_done = False
    for p in sig.params:
        kind = str(getattr(p, "kind", ""))
        if "VAR_POSITIONAL" in kind:
            star_done = True
        if "KEYWORD_ONLY" in kind and not star_done:
            out.append("*")
            star_done = True
        out.append(_param(p))
    return out


def _compact(sig: Any) -> str:
    return f"{sig.name}({', '.join(_params(sig))})"


def handle(msg: dict[str, Any]) -> Any:
    global _env, _last
    op = msg["op"]
    if op == "env":
        try:
            _env = jedi.create_environment(msg["python"], safe=False)
            _env.get_sys_path()  # fails early if the interpreter cannot start
        except Exception:
            _env = jedi.InterpreterEnvironment()
        return {"ok": True}
    if op == "complete":
        comps = _script(msg).complete(msg["line"], msg["col"])
        _last = {c.name: c for c in comps[:400]}
        return [
            {"name": c.name, "kind": KIND.get(c.type, "·"), "prefix": len(c.name) - len(c.complete or "")}
            for c in comps[:400]
            if not c.name.startswith("__") or msg.get("dunder")
        ]
    if op == "doc":
        comp = _last.get(msg["name"])
        if comp is None:
            return None
        sigs = []
        try:
            sigs = [_compact(s) for s in comp.get_signatures()[:2]]
        except Exception:
            pass
        try:
            doc = comp.docstring(raw=True)
        except Exception:
            doc = ""
        return {"signatures": sigs, "doc": _first_paragraphs(doc) if doc else ""}
    if op == "signature":
        sigs = _script(msg).get_signatures(msg["line"], msg["col"])
        if not sigs:
            return None
        sig = sigs[0]
        params = _params(sig)
        index = sig.index
        if index is not None and "*" in params:
            # the bare "*" marker isn't a real parameter; shift the highlight past it
            star = params.index("*")
            if index >= star:
                index += 1
        return {"name": sig.name, "params": params, "index": index}
    if op == "warm":
        script = _script({"source": msg.get("source", "import os, json, pathlib\n"), "path": msg.get("path")})
        script.complete(1, 0)
        for name in ("os.", "json.", "pathlib.Path."):
            jedi.Script(f"import os, json, pathlib\n{name}", environment=_env).complete(2, len(name))
        return {"ok": True}
    raise ValueError(f"unknown op {op}")


def main() -> None:
    out = sys.stdout
    for raw in sys.stdin:
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        try:
            reply = {"id": msg.get("id"), "result": handle(msg)}
        except Exception as exc:  # never die on a bad request
            reply = {"id": msg.get("id"), "error": f"{type(exc).__name__}: {exc}"}
        out.write(json.dumps(reply) + "\n")
        out.flush()


if __name__ == "__main__":
    main()
