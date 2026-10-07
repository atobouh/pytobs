"""Plain-English notes for Python errors. Rule-based and offline: same error in, same note out.

Each rule matches the exception type and message (and sometimes the failing line of code) and
returns what the error means plus, when it can be stated with certainty, a corrected line to try.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .tracebacks import ParsedError


@dataclass
class Explanation:
    meaning: str
    tries: list[tuple[str, str]] = field(default_factory=list)  # (code, note)
    review: str = ""  # concept to review, shown on the progress screen


@dataclass
class Context:
    exc_type: str
    message: str
    code: str  # the failing line, stripped ("" when unknown)
    source: str
    script: Path
    _defs: dict[str, ast.FunctionDef] | None = None

    @property
    def defs(self) -> dict[str, ast.FunctionDef]:
        if self._defs is None:
            self._defs = {}
            try:
                for node in ast.walk(ast.parse(self.source)):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self._defs.setdefault(node.name, node)  # type: ignore[arg-type]
            except (SyntaxError, ValueError):
                pass
        return self._defs

    def signature(self, name: str) -> str | None:
        node = self.defs.get(name)
        if node is None:
            return None
        return f"{name}({ast.unparse(node.args)})"


# ── method reference used by argument-count rules ───────────────────────────
METHODS: dict[str, tuple[str, str]] = {
    "count": ("{r}.count(x)", "counts how many times x appears"),
    "index": ("{r}.index(x)", "finds the position of the first x"),
    "append": ("{r}.append(x)", "adds one item at the end"),
    "remove": ("{r}.remove(x)", "removes the first x"),
    "insert": ("{r}.insert(i, x)", "puts x at position i"),
    "extend": ("{r}.extend(other)", "adds every item of another list"),
    "pop": ("{r}.pop()", "removes and returns the last item (or {r}.pop(i))"),
    "split": ("{r}.split()", "splits on spaces (or {r}.split(',') on commas)"),
    "join": ('", ".join({r})', "joins a list of strings with a separator"),
    "replace": ("{r}.replace(old, new)", "swaps every old for new"),
    "startswith": ("{r}.startswith(prefix)", "True if the text begins with prefix"),
    "endswith": ("{r}.endswith(suffix)", "True if the text ends with suffix"),
    "get": ("{r}.get(key, default)", "value for key, or default when missing"),
    "setdefault": ("{r}.setdefault(key, default)", "value for key, adding it if missing"),
    "update": ("{r}.update(other)", "copies every key from another dict"),
    "add": ("{r}.add(x)", "adds x to the set"),
    "find": ("{r}.find(sub)", "position of sub, or -1"),
    "format": ('"{{}} {{}}".format(a, b)', "fills each {{}} with a value; f-strings are simpler"),
}

COMMON_MODULES = {
    "math",
    "random",
    "os",
    "sys",
    "json",
    "time",
    "datetime",
    "re",
    "string",
    "csv",
    "pathlib",
    "collections",
    "itertools",
    "statistics",
    "turtle",
    "copy",
    "functools",
}

BUILTIN_NAMES = {
    "list",
    "dict",
    "str",
    "int",
    "float",
    "set",
    "tuple",
    "len",
    "sum",
    "max",
    "min",
    "input",
    "print",
    "type",
    "range",
    "sorted",
    "id",
    "map",
    "filter",
    "open",
}

WRONG_METHOD = {
    ("list", "push"): ("append", "Python lists use .append(x), not .push(x)."),
    ("list", "add"): ("append", "Lists use .append(x). .add(x) is for sets."),
    ("list", "length"): (None, "Use len(items) to get the size of a list."),
    ("list", "size"): (None, "Use len(items) to get the size of a list."),
    ("list", "lower"): (None, "A list has no .lower(); lower each string, e.g. [s.lower() for s in items]."),
    ("list", "split"): (None, "Only strings have .split(). Did you mean one item, like items[0].split()?"),
    ("list", "join"): (None, 'join belongs to the separator string: ", ".join(items).'),
    ("str", "append"): (None, "Strings can't change. Build a new one: text = text + more."),
    ("str", "push"): (None, "Strings can't change. Build a new one: text = text + more."),
    ("str", "length"): (None, "Use len(text) to get the length of a string."),
    ("str", "contains"): (None, 'Use the in operator: "a" in text.'),
    ("dict", "append"): (None, "Dicts don't append. Set a key instead: d[key] = value."),
    ("dict", "add"): (None, "Dicts don't add. Set a key instead: d[key] = value."),
    ("dict", "has_key"): (None, "Use the in operator: key in d."),
    ("int", "append"): (None, "This name holds a number, not a list."),
    ("tuple", "append"): (None, "Tuples can't change. Use a list [...] if you need to add items."),
}

GENERIC = {
    "TypeError": "An operation got a value of the wrong type.",
    "ValueError": "The type is right but the value isn't acceptable here.",
    "NameError": "Python doesn't know this name.",
    "AttributeError": "This value doesn't have that attribute or method.",
    "IndexError": "That position doesn't exist.",
    "KeyError": "That key isn't in the dictionary.",
    "ZeroDivisionError": "You divided by zero.",
    "FileNotFoundError": "No file exists at that path.",
    "PermissionError": "The operating system refused access to that file or folder.",
    "IsADirectoryError": "That path is a folder, not a file.",
    "ImportError": "Python found the module but not the name you asked for.",
    "ModuleNotFoundError": "Python can't find a module with that name.",
    "RecursionError": "A function called itself too many times.",
    "StopIteration": "next() was called on an iterator that has no items left.",
    "OverflowError": "A number got too big to represent.",
    "MemoryError": "The program ran out of memory.",
    "UnicodeDecodeError": "The file's bytes aren't valid in the encoding used to read it.",
    "UnicodeEncodeError": "This text can't be written in the target encoding.",
    "AssertionError": "An assert statement's condition was False.",
    "NotImplementedError": "This part of the code was left as a placeholder.",
    "RuntimeError": "Something went wrong that doesn't fit another error type.",
    "EOFError": "input() expected text but the input ended.",
    "UnboundLocalError": "A variable was used inside a function before it got a value there.",
    "SyntaxError": "Python couldn't read this line as valid code.",
    "IndentationError": "The indentation (spaces at the start of lines) is wrong here.",
    "TabError": "Tabs and spaces are mixed in the indentation.",
    "OSError": "The operating system reported an error.",
    "TimeoutError": "An operation took too long.",
    "ConnectionError": "A network connection failed.",
}


Rule = Callable[[re.Match[str], Context], Explanation | None]
RULES: list[tuple[str, re.Pattern[str], Rule]] = []


def rule(types: str, pattern: str) -> Callable[[Rule], Rule]:
    def deco(fn: Rule) -> Rule:
        for t in types.split():
            RULES.append((t, re.compile(pattern), fn))
        return fn

    return deco


def _receiver(code: str, method: str) -> str:
    m = re.search(rf"([A-Za-z_][\w\.\[\]'\"]*)\.{method}\(", code)
    return m.group(1) if m else "items"


# ── argument counts ─────────────────────────────────────────────────────────


@rule(
    "TypeError",
    r"^(?:(?P<owner>\w+)\.)?(?P<fn>\w+)\(\) takes (?P<want>exactly one argument|no arguments) \((?P<given>\d+) given\)",
)
def _builtin_arg_count(m: re.Match[str], c: Context) -> Explanation:
    fn = m["fn"]
    tries: list[tuple[str, str]] = []
    if fn in METHODS:
        template, note = METHODS[fn]
        r = _receiver(c.code, fn)
        tries.append((template.format(r=r), note.format(r=r)))
        if fn == "count":
            tries.append((f"len({r})", "if you wanted the number of items"))
    what = f".{fn}()" if m["owner"] else f"{fn}()"
    want = "exactly one value" if m["want"].startswith("exactly") else "no values"
    return Explanation(
        f"{what} takes {want} inside its brackets, and this line gave it {m['given']}.",
        tries,
        "function arguments",
    )


@rule("TypeError", r"^(?P<fn>[\w\.]+)\(\) missing (?P<n>\d+) required positional arguments?: (?P<names>.+)$")
def _missing_args(m: re.Match[str], c: Context) -> Explanation:
    name = m["fn"].split(".")[-1]
    sig = c.signature(name)
    names = m["names"].replace("'", "")
    tries = [(sig, "its parameters: pass one value for each")] if sig else []
    return Explanation(
        f"{name}() needs a value for {names}, but the call didn't give one.", tries, "function arguments"
    )


@rule(
    "TypeError",
    r"^(?P<fn>[\w\.]+)\(\) takes (?P<want>\d+) positional arguments? but (?P<got>\d+) (?:was|were) given",
)
def _too_many_args(m: re.Match[str], c: Context) -> Explanation:
    full, name = m["fn"], m["fn"].split(".")[-1]
    want, got = int(m["want"]), int(m["got"])
    node = c.defs.get(name)
    if "." in full and node is not None and (not node.args.args or node.args.args[0].arg != "self"):
        return Explanation(
            "Methods receive the object itself as their first value. This method's definition is missing self.",
            [
                (
                    f"def {name}(self{', ' if node.args.args else ''}{ast.unparse(node.args)}):",
                    "add self first",
                )
            ],
            "classes and self",
        )
    sig = c.signature(name)
    return Explanation(
        f"{name}() accepts {want} value{'s' if want != 1 else ''}, but the call passed {got}.",
        [(sig, "its parameters")] if sig else [],
        "function arguments",
    )


@rule("TypeError", r"^(?P<fn>[\w\.]+)\(\) got an unexpected keyword argument '(?P<kw>\w+)'")
def _bad_keyword(m: re.Match[str], c: Context) -> Explanation:
    name = m["fn"].split(".")[-1]
    sig = c.signature(name)
    return Explanation(
        f"{name}() has no parameter called {m['kw']}. Keyword names must match the definition exactly.",
        [(sig, "the names it accepts")] if sig else [],
        "function arguments",
    )


# ── mixing types ────────────────────────────────────────────────────────────


@rule("TypeError", r'^can only concatenate str \(not "(?P<t>\w+)"\) to str')
def _concat_str(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        f"+ joins text only with other text, and one side is a {m['t']}. Convert it to text first.",
        [
            ('"Total: " + str(total)', "to build text"),
            ('f"Total: {total}"', "same, with an f-string"),
            ("int(text) + 1", "to do math with number text"),
        ],
        "types and conversion",
    )


@rule("TypeError", r"^unsupported operand type\(s\) for (?P<op>\S+): '(?P<a>\w+)' and '(?P<b>\w+)'")
def _operand(m: re.Match[str], c: Context) -> Explanation:
    a, b, op = m["a"], m["b"], m["op"]
    tries = []
    if "str" in (a, b) and {a, b} & {"int", "float"}:
        if "input(" in c.code or "input(" in c.source:
            tries.append(("age = int(input('Age: '))", "input() always returns text: convert it"))
        tries.append(("int(text)  float(text)  str(number)", "convert so both sides match"))
        meaning = f"{op} can't combine a {a} and a {b}. Text that looks like a number is still text."
    elif "NoneType" in (a, b):
        meaning = f"One side of {op} is None. A function probably returned nothing (no return statement)."
    else:
        meaning = f"{op} doesn't work between a {a} and a {b}."
    return Explanation(meaning, tries, "types and conversion")


@rule("TypeError", r"^'(?P<t>\w+)' object is not subscriptable")
def _not_subscriptable(m: re.Match[str], c: Context) -> Explanation:
    t = m["t"]
    if t == "NoneType":
        return Explanation(
            "You used [ ] on None. A function or method probably returned nothing, e.g. "
            "items = items.sort() sets items to None.",
            [
                ("items.sort()", "sort changes the list itself and returns None"),
                ("items = sorted(items)", "or"),
            ],
            "return values",
        )
    if t in ("builtin_function_or_method", "function", "method"):
        return Explanation(
            "You used [ ] on a function. Call functions with ( ).",
            [("len(items)", "round brackets")],
            "syntax",
        )
    return Explanation(
        f"A {t} can't be indexed with [ ]. Only sequences (list, str, tuple) and dicts can.",
        [],
        "types and conversion",
    )


@rule("TypeError", r"^'(?P<t>\w+)' object is not callable")
def _not_callable(m: re.Match[str], c: Context) -> Explanation:
    t = m["t"]
    shadow = re.search(rf"^\s*({'|'.join(sorted(BUILTIN_NAMES))})\s*=", c.source, re.M)
    if shadow:
        n = shadow.group(1)
        return Explanation(
            f"Your code assigns to {n}, which replaces Python's built-in {n}(). Calling it now calls your {t}.",
            [(f"my_{n} = ...", f"rename your variable so {n}() works again")],
            "names and scope",
        )
    return Explanation(
        f"You put ( ) after a {t}, as if it were a function. Use [ ] to index, or remove the brackets.",
        [],
        "syntax",
    )


@rule("TypeError", r"^'(?P<t>\w+)' object is not iterable")
def _not_iterable(m: re.Match[str], c: Context) -> Explanation:
    t = m["t"]
    if t == "int":
        return Explanation(
            "A for loop needs a sequence, not a number.",
            [("for i in range(n):", "counts 0, 1, … n-1")],
            "loops",
        )
    if t == "NoneType":
        return Explanation(
            "You looped over None. Something returned nothing instead of a list.", [], "return values"
        )
    return Explanation(f"A {t} can't be looped over.", [], "loops")


@rule("TypeError", r"^object of type '(?P<t>\w+)' has no len\(\)")
def _no_len(m: re.Match[str], c: Context) -> Explanation:
    t = m["t"]
    tip = [("len(str(number))", "digits in a number")] if t in ("int", "float") else []
    return Explanation(f"len() works on collections and text, not on a {t}.", tip, "types and conversion")


@rule("TypeError", r"^(?P<t>list|tuple|string) indices must be integers")
def _bad_index_type(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        f"Positions in a {m['t']} are whole numbers like 0, 1, 2. If you wanted to look things up by name, "
        "use a dict.",
        [("items[int(i)]", "convert text to a number first"), ('person = {"name": "Ada"}', "or use a dict")],
        "lists and dicts",
    )


@rule("TypeError", r"^'(?P<t>str|tuple)' object does not support item assignment")
def _immutable(m: re.Match[str], c: Context) -> Explanation:
    if m["t"] == "str":
        return Explanation(
            "Strings can't be changed in place. Build a new string instead.",
            [
                ('text = text[:i] + "x" + text[i+1:]', "rebuild it"),
                ('text = text.replace("a", "b")', "or replace"),
            ],
            "strings",
        )
    return Explanation(
        "Tuples can't be changed. Use a list if you need to modify it.",
        [("items = list(items)", "convert to a list")],
        "lists and dicts",
    )


# ── names ───────────────────────────────────────────────────────────────────


@rule("NameError", r"^name '(?P<n>\w+)' is not defined(?:\. Did you mean: '(?P<s>\w+)'\?)?")
def _name(m: re.Match[str], c: Context) -> Explanation:
    n, s = m["n"], m["s"]
    if n in COMMON_MODULES:
        return Explanation(
            f"{n} is a module. Import it before using it.",
            [(f"import {n}", "at the top of the file")],
            "imports",
        )
    if n in ("true", "false", "null", "none"):
        fixed = {"true": "True", "false": "False", "null": "None", "none": "None"}[n]
        return Explanation(f"Python spells it {fixed}, with a capital letter.", [(fixed, "")], "syntax")
    if s:
        return Explanation(
            f"Python has no {n}. It looks like a typo for {s}.", [(s, "the existing name")], "names and scope"
        )
    defined_later = re.search(rf"^\s*(def\s+{n}\b|{n}\s*=)", c.source, re.M)
    if defined_later:
        return Explanation(
            f"{n} is created further down the file, but this line runs before that. Python reads top to bottom.",
            [],
            "names and scope",
        )
    return Explanation(
        f"Nothing called {n} exists here. Check the spelling, or create it before this line. "
        "If it's text, it needs quotes.",
        [(f'"{n}"', "if you meant the text itself")],
        "names and scope",
    )


@rule("UnboundLocalError", r"^(?:cannot access local variable|local variable) '(?P<n>\w+)'")
def _unbound(m: re.Match[str], c: Context) -> Explanation:
    n = m["n"]
    return Explanation(
        f"Because this function assigns to {n}, Python treats {n} as a new local variable, which has no "
        "value yet on this line. Pass it in and return the result instead.",
        [(f"def update({n}):  ...  return {n}", "pass in, return out"), (f"{n} = update({n})", "")],
        "names and scope",
    )


# ── attributes ──────────────────────────────────────────────────────────────


@rule("AttributeError", r"^partially initialized module '(?P<mod>\w+)'")
def _circular(m: re.Match[str], c: Context) -> Explanation:
    mod = m["mod"]
    if c.script.stem == mod:
        return _shadowed_module(mod, c)
    return Explanation(
        f"Two files import each other, or a file in your folder is named {mod}.py.", [], "imports"
    )


def _shadowed_module(mod: str, c: Context) -> Explanation:
    return Explanation(
        f"Your file is named {mod}.py, so 'import {mod}' imports your own file instead of Python's {mod} module.",
        [(f"rename {c.script.name} → my_{mod}.py", "then run again")],
        "imports",
    )


@rule("AttributeError", r"^module '(?P<mod>\w+)' has no attribute '(?P<a>\w+)'")
def _module_attr(m: re.Match[str], c: Context) -> Explanation:
    mod = m["mod"]
    if c.script.stem == mod or (c.script.parent / f"{mod}.py").exists():
        return _shadowed_module(mod, c)
    return Explanation(f"The {mod} module has no {m['a']}. Check the spelling.", [], "imports")


@rule("AttributeError", r"^'(?P<t>\w+)' object has no attribute '(?P<a>\w+)'")
def _attr(m: re.Match[str], c: Context) -> Explanation:
    t, a = m["t"], m["a"]
    if t == "NoneType":
        mutator = re.search(r"(\w+)\s*=\s*\1\.(sort|append|reverse|extend|insert|remove|clear)\(", c.source)
        if mutator:
            v, meth = mutator.groups()
            return Explanation(
                f".{meth}() changes the list itself and returns None, so '{v} = {v}.{meth}(…)' sets {v} to None.",
                [(f"{v}.{meth}(…)", "without the assignment")],
                "return values",
            )
        return Explanation(
            f"This value is None, so it has no .{a}. Something before this line returned nothing.",
            [],
            "return values",
        )
    if (t, a) in WRONG_METHOD:
        right, note = WRONG_METHOD[(t, a)]
        r = _receiver(c.code, a)
        return Explanation(note, [(f"{r}.{right}(x)", "")] if right else [], "methods")
    return Explanation(f"A {t} has no .{a}. Type the name and a dot to see what it does have.", [], "methods")


# ── positions and keys ──────────────────────────────────────────────────────


@rule("IndexError", r"^(?P<t>list|string|tuple|range object) index out of range")
def _index(m: re.Match[str], c: Context) -> Explanation:
    t = m["t"].split()[0]
    return Explanation(
        f"Positions start at 0, so a {t} of 3 items has positions 0, 1 and 2. This line asked for one past the end.",
        [
            ("items[-1]", "the last item"),
            ("for item in items:", "loop without positions"),
            ("if i < len(items):", "check first"),
        ],
        "list positions",
    )


@rule("KeyError", r"^(?P<k>.+)$")
def _key(m: re.Match[str], c: Context) -> Explanation:
    k = m["k"]
    if len(k) >= 2 and k[0] == k[-1] and k[0] in "'\"":
        inner = re.escape(k[1:-1])
        literal = r"""(?P<q>['"])""" + inner + r"(?P=q)"
    else:
        literal = re.escape(k)
    found = re.search(r"(?P<d>[A-Za-z_]\w*)\[\s*(?P<lit>" + literal + r")\s*\]", c.code)
    d, lit = (found["d"], found["lit"]) if found else ("data", k)
    return Explanation(
        f"The dictionary has no key {k}. Keys must match exactly, including capitals and spaces.",
        [(f"{d}.get({lit})", "returns None instead of failing"), (f"if {lit} in {d}:", "check first")],
        "dicts",
    )


# ── values ──────────────────────────────────────────────────────────────────


@rule("ValueError", r"^invalid literal for int\(\) with base 10: (?P<v>.+)$")
def _int_literal(m: re.Match[str], c: Context) -> Explanation:
    v = m["v"]
    tries = [("float(text)", "for numbers with a decimal point")] if re.match(r"^'-?\d+\.\d*'$", v) else []
    tries.append(("if text.isdigit():", "check before converting"))
    return Explanation(
        f"int() can only convert whole-number text, and got {v}.", tries, "types and conversion"
    )


@rule("ValueError", r"^could not convert string to float: (?P<v>.+)$")
def _float_literal(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        f"float() can only convert number text, and got {m['v']}.",
        [('text.replace(",", ".")', "if it uses a comma as decimal point")],
        "types and conversion",
    )


@rule("ValueError", r"^(?:not enough|too many) values to unpack \(expected (?P<e>\d+)(?:, got (?P<g>\d+))?\)")
def _unpack(m: re.Match[str], c: Context) -> Explanation:
    got = f" but the value has {m['g']}" if m["g"] else ", and the value has more"
    return Explanation(
        f"The left side has {m['e']} names{got}. Both sides need the same count.",
        [("a, b = pair", "two names, two values")],
        "unpacking",
    )


@rule("ValueError", r"^(?:list\.(?:remove|index)\(x\): x not in list|(?P<v>.+) is not in list)$")
def _not_in_list(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "That value isn't in the list, so it can't be removed or found.",
        [("if x in items:", "check first")],
        "lists and dicts",
    )


@rule("ValueError", r"^math domain error")
def _math_domain(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "A math function got a value it can't handle, like the square root of a negative number.",
        [],
        "numbers",
    )


@rule("ZeroDivisionError", r".*")
def _zero(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "Dividing by zero has no answer. The divisor was 0 on this line.",
        [("if count != 0:", "check before dividing")],
        "numbers",
    )


# ── syntax and indentation ──────────────────────────────────────────────────


@rule("SyntaxError", r"^'(?P<b>[\(\[\{])' was never closed")
def _never_closed(m: re.Match[str], c: Context) -> Explanation:
    close = {"(": ")", "[": "]", "{": "}"}[m["b"]]
    return Explanation(
        f"A {m['b']} opens here but its {close} never comes. Add the closing bracket.", [], "syntax"
    )


@rule("SyntaxError", r"^unmatched '(?P<b>[\)\]\}])'")
def _unmatched(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(f"There's an extra {m['b']} with no opening bracket before it.", [], "syntax")


@rule("SyntaxError", r"^expected ':'")
def _colon(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "Lines that start a block (if, for, while, def, class, else) end with a colon.",
        [(c.code.rstrip() + ":" if c.code else "if x > 3:", "")],
        "syntax",
    )


@rule("SyntaxError", r"^unterminated (?:triple-quoted )?string literal")
def _unterminated(m: re.Match[str], c: Context) -> Explanation:
    return Explanation("A string starts with a quote but never ends. Add the matching quote.", [], "syntax")


@rule("SyntaxError", r"invalid syntax\. Maybe you meant '==' or ':=' instead of '='\?")
def _eq(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "= stores a value; == compares two values. Conditions need ==.", [("if age == 18:", "")], "syntax"
    )


@rule("SyntaxError", r"invalid syntax\. Perhaps you forgot a comma\?")
def _comma(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "Items in a list, tuple or function call are separated by commas.",
        [('["Ada", "Grace"]', "")],
        "syntax",
    )


@rule("SyntaxError", r"^Missing parentheses in call to 'print'")
def _print(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "In Python 3, print is a function and needs brackets.", [('print("hello")', "")], "syntax"
    )


@rule("SyntaxError", r"^'return' outside function")
def _return_outside(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "return only works inside a def. At the top level, use print() to show a value.", [], "functions"
    )


@rule("SyntaxError", r"^'(?:break|continue)' (?:outside loop|not properly in loop)")
def _break_outside(m: re.Match[str], c: Context) -> Explanation:
    return Explanation("break and continue only work inside a for or while loop.", [], "loops")


@rule(
    "IndentationError",
    r"^expected an indented block after '(?P<what>[^']+)' (?:statement )?on line (?P<l>\d+)",
)
def _expected_indent(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        f"The {m['what']} on line {m['l']} must be followed by at least one indented line (4 spaces).",
        [("    pass", "a placeholder if the block is empty for now")],
        "indentation",
    )


@rule("IndentationError", r"^unexpected indent")
def _unexpected_indent(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "This line is indented but isn't inside a block. Remove the spaces at the start.", [], "indentation"
    )


@rule("IndentationError", r"^unindent does not match any outer indentation level")
def _unindent(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "This line's indentation doesn't line up with any block above. Use multiples of 4 spaces.",
        [],
        "indentation",
    )


@rule("TabError", r".*")
def _tabs(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "Tabs and spaces are mixed. pytobs indents with spaces; retype the indentation.", [], "indentation"
    )


# ── modules and files ───────────────────────────────────────────────────────


@rule("ModuleNotFoundError", r"^No module named '(?P<mod>[\w\.]+)'")
def _no_module(m: re.Match[str], c: Context) -> Explanation:
    mod = m["mod"].split(".")[0]
    pip_names = {
        "cv2": "opencv-python",
        "PIL": "pillow",
        "sklearn": "scikit-learn",
        "bs4": "beautifulsoup4",
        "yaml": "pyyaml",
        "dotenv": "python-dotenv",
    }
    pkg = pip_names.get(mod, mod)
    return Explanation(
        f"{mod} isn't installed in this project's Python. Install it once and it stays in your .venv.",
        [("Ctrl+K  →  Install a package", f"type {pkg}")],
        "packages",
    )


@rule("ImportError", r"^cannot import name '(?P<n>\w+)' from '(?P<mod>[\w\.]+)'")
def _cannot_import(m: re.Match[str], c: Context) -> Explanation:
    mod = m["mod"].split(".")[0]
    if c.script.stem == mod or "circular import" in c.message:
        return (
            _shadowed_module(mod, c)
            if c.script.stem == mod
            else Explanation(
                "Two of your files import each other. Move the shared code into a third file.", [], "imports"
            )
        )
    return Explanation(
        f"{m['mod']} has nothing called {m['n']}. Check the spelling and capitals.", [], "imports"
    )


@rule("FileNotFoundError", r"No such file or directory: '(?P<p>[^']+)'")
def _no_file(m: re.Match[str], c: Context) -> Explanation:
    p = m["p"]
    where = c.script.parent / p
    return Explanation(
        f"pytobs runs your script from its own folder, so '{p}' means {where}. No file exists there.",
        [
            (f'Path(__file__).parent / "{Path(p).name}"', "a path that always works"),
            ("check the name and extension", "e.g. data.txt vs data.txt.txt"),
        ],
        "files and paths",
    )


@rule("RecursionError", r".*")
def _recursion(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "A function keeps calling itself and never stops. Every recursive function needs a case that "
        "returns without calling itself.",
        [("if n == 0: return 1", "a base case")],
        "recursion",
    )


@rule("EOFError", r".*")
def _eof(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "input() was waiting for text, but the input was closed (Ctrl+D ends input).", [], "input"
    )


@rule("AssertionError", r".*")
def _assert(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "An assert checks something you expect to be true. On this line it was False.",
        [("Ctrl+T", "run tests to see expected vs got")],
        "testing",
    )


@rule("StopIteration", r".*")
def _stopiter(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "next() was called after the last item. A for loop handles this for you.",
        [("for item in iterator:", "")],
        "loops",
    )


@rule("JSONDecodeError", r".*")
def _json(m: re.Match[str], c: Context) -> Explanation:
    return Explanation(
        "The text isn't valid JSON. Check quotes (JSON needs double quotes) and commas.",
        [],
        "files and paths",
    )


def explain(err: ParsedError, script: Path, source: str) -> Explanation | None:
    line = err.exception
    exc_type, _, message = line.partition(": ")
    exc_type = exc_type.strip().rsplit(".", 1)[-1]
    message = message.strip()
    code = ""
    for frame in reversed(err.frames):
        if frame.code:
            code = frame.code[0].strip()
            break
    ctx = Context(exc_type, message, code, source, script)
    for t, pattern, fn in RULES:
        if t != exc_type:
            continue
        m = pattern.search(message)
        if m:
            try:
                result = fn(m, ctx)
            except Exception:  # a rule must never break the error display
                result = None
            if result:
                return result
    if exc_type in GENERIC:
        return Explanation(GENERIC[exc_type], [], exc_type)
    return None
