"""Snippets and plain-English help for the words learners meet first. Fixed text, no AI."""

from __future__ import annotations

import re

# Type the word at the start of a line, press Tab. ${...} marks a stop: Tab moves to the next one.
SNIPPETS: dict[str, tuple[str, str]] = {
    "for": ("loop over a list", "for ${item} in ${items}:\n    ${pass}"),
    "fori": ("loop n times", "for ${i} in range(${10}):\n    ${pass}"),
    "fore": ("loop with position", "for ${i}, ${item} in enumerate(${items}):\n    ${pass}"),
    "while": ("loop while true", "while ${condition}:\n    ${pass}"),
    "if": ("if", "if ${condition}:\n    ${pass}"),
    "ife": ("if / else", "if ${condition}:\n    ${pass}\nelse:\n    ${pass}"),
    "ifel": ("if / elif / else", "if ${a}:\n    ${pass}\nelif ${b}:\n    ${pass}\nelse:\n    ${pass}"),
    "def": ("function", "def ${name}(${args}):\n    ${pass}"),
    "defr": ("function that returns", "def ${name}(${args}):\n    return ${result}"),
    "class": ("class", "class ${Name}:\n    def __init__(self, ${value}):\n        self.${value} = ${value}"),
    "main": ("run only as a script", 'if __name__ == "__main__":\n    ${main()}'),
    "try": ("catch an error", "try:\n    ${pass}\nexcept ${ValueError} as e:\n    ${print(e)}"),
    "with": ("read a file", 'with open(${"data.txt"}) as f:\n    ${text = f.read()}'),
    "wwith": ("write a file", 'with open(${"out.txt"}, "w") as f:\n    ${f.write("hello")}'),
    "lc": ("list comprehension", "${squares} = [${x * x} for ${x} in ${numbers}]"),
    "dc": ("dict comprehension", "${lookup} = {${k}: ${v} for ${k}, ${v} in ${pairs}}"),
    "pr": ("print a value with its name", 'print(f"{${value}=}")'),
    "inp": ("ask for input", '${name} = input("${Your name: }")'),
    "inpi": ("ask for a number", '${age} = int(input("${Your age: }"))'),
    "test": ("a test (Ctrl+T)", "def test_${name}():\n    assert ${actual} == ${expected}"),
}

STOP_RE = re.compile(r"\$\{([^}]*)\}")


def expand(template: str, indent: str) -> tuple[str, list[tuple[int, str]]]:
    """Snippet text indented to match the line, plus its stops as (line offset, text)."""
    lines = template.split("\n")
    stops: list[tuple[int, str]] = []
    out = []
    for i, line in enumerate(lines):
        stops.extend((i, m.group(1)) for m in STOP_RE.finditer(line))
        plain = STOP_RE.sub(lambda m: m.group(1), line)
        out.append(plain if i == 0 else indent + plain)
    return "\n".join(out), stops


# name -> (what it is, example, tip)
HELP: dict[str, tuple[str, str, str]] = {
    "print": (
        "Shows values in the output pane.",
        'print("total:", 3 + 4)   # total: 7',
        "Separate values with commas; print(a, b, sep='-') changes the gap.",
    ),
    "input": (
        "Waits for the user to type a line and returns it as a str.",
        'name = input("Name? ")',
        "It is always text: wrap it in int(...) to get a number.",
    ),
    "len": (
        "How many items are in a list, str, dict, set or tuple.",
        "len([4, 5, 6])   # 3",
        "The last index of a list is len(x) - 1.",
    ),
    "range": (
        "A sequence of whole numbers, mostly used in for loops.",
        "for i in range(3):  # 0, 1, 2",
        "range(start, stop, step): stop itself is never included.",
    ),
    "int": (
        "Turns text or a float into a whole number.",
        'int("42") + 1   # 43',
        "int(3.9) is 3: it cuts, it doesn't round.",
    ),
    "float": ("Turns text or an int into a decimal number.", 'float("2.5") * 2   # 5.0', ""),
    "str": ("Turns any value into text.", '"age " + str(30)', 'f-strings do this for you: f"age {30}".'),
    "list": (
        "An ordered, changeable collection: [1, 2, 3].",
        "nums = list(range(3))   # [0, 1, 2]",
        "Lists change in place: methods like .sort() and .append() return None.",
    ),
    "dict": (
        "Pairs of key → value.",
        'ages = {"ada": 36}\nages["ada"]   # 36',
        "Use .get(key, default) when the key might be missing.",
    ),
    "set": ("A collection with no duplicates and no order.", "set([1, 1, 2])   # {1, 2}", ""),
    "tuple": ("Like a list, but can't be changed.", "point = (3, 4)\nx, y = point", ""),
    "bool": (
        "True or False.",
        "bool(0)   # False\nbool([1])   # True",
        "Empty things (0, '', [], {}, None) count as False.",
    ),
    "None": (
        "The value meaning 'nothing'. Functions without return give None.",
        "result = print('hi')   # result is None",
        "Compare with `is`: if x is None:",
    ),
    "sum": ("Adds up the numbers in a list.", "sum([1, 2, 3])   # 6", ""),
    "min": ("The smallest item.", "min([4, 2, 9])   # 2", "max(...) gives the largest."),
    "max": ("The largest item.", "max([4, 2, 9])   # 9", ""),
    "sorted": (
        "A new sorted list; the original stays as it was.",
        "sorted([3, 1, 2])   # [1, 2, 3]",
        "sorted(words, key=len) sorts by length; reverse=True flips it.",
    ),
    "sort": (
        "Sorts a list in place and returns None.",
        "nums.sort()\nprint(nums)",
        "Don't write nums = nums.sort(): that stores None. Use sorted(nums) for a copy.",
    ),
    "append": ("Adds one item to the end of a list. Returns None.", "nums.append(4)", ""),
    "extend": ("Adds every item of another list.", "nums.extend([5, 6])", ""),
    "insert": ("Puts an item at a position.", 'names.insert(0, "first")', ""),
    "pop": ("Removes and returns an item (the last one by default).", "last = nums.pop()", ""),
    "remove": (
        "Removes the first item equal to a value.",
        'names.remove("bob")',
        "Raises ValueError if the value isn't there.",
    ),
    "reverse": (
        "Reverses a list in place. Returns None.",
        "nums.reverse()",
        "nums[::-1] gives a reversed copy.",
    ),
    "index": ("Position of the first match.", '"hello".index("l")   # 2', ""),
    "count": ("How many times a value appears.", '"banana".count("a")   # 3', ""),
    "split": (
        "Cuts a str into a list of words.",
        '"a b c".split()   # ["a", "b", "c"]',
        'split(",") cuts at commas instead of spaces.',
    ),
    "join": (
        "Glues a list of str together.",
        '", ".join(["a", "b"])   # "a, b"',
        "Called on the separator, not the list.",
    ),
    "strip": ("Removes spaces (and newlines) from both ends.", '"  hi \\n".strip()   # "hi"', ""),
    "replace": (
        "A copy with one piece of text swapped for another.",
        '"cat".replace("c", "b")   # "bat"',
        "",
    ),
    "upper": ("A copy in CAPITALS.", '"hi".upper()   # "HI"', ".lower() and .title() too."),
    "lower": ("A copy in lowercase.", '"Hi".lower()   # "hi"', ""),
    "format": ("Fills {} slots in a str.", '"{} + {}".format(1, 2)', 'f-strings are shorter: f"{a} + {b}".'),
    "get": ("A dict value, or a default if the key is missing.", 'ages.get("bob", 0)', ""),
    "keys": ("All keys of a dict.", "for k in ages.keys():", ""),
    "values": ("All values of a dict.", "sum(prices.values())", ""),
    "items": ("Key and value pairs of a dict.", "for name, age in ages.items():", ""),
    "enumerate": ("Gives (position, item) pairs in a loop.", "for i, name in enumerate(names):", ""),
    "zip": ("Walks several lists side by side.", "for name, age in zip(names, ages):", ""),
    "open": (
        "Opens a file to read or write.",
        'with open("notes.txt") as f:\n    text = f.read()',
        '"w" overwrites, "a" appends. `with` closes the file for you.',
    ),
    "abs": ("Distance from zero.", "abs(-5)   # 5", ""),
    "round": ("Rounds a number.", "round(3.14159, 2)   # 3.14", ""),
    "type": ("What kind of value something is.", "type(3.0)   # <class 'float'>", ""),
    "isinstance": ("Checks a value's type.", "isinstance(x, int)", ""),
    "def": (
        "Defines a function: a named, reusable block of code.",
        "def area(w, h):\n    return w * h",
        "Without return, the function gives back None.",
    ),
    "return": ("Ends a function and hands a value back.", "return total", ""),
    "class": (
        "A blueprint for your own kind of object.",
        "class Dog:\n    def __init__(self, name):\n        self.name = name",
        "",
    ),
    "self": ("The object a method was called on.", "self.name = name", "Every method's first parameter."),
    "for": (
        "Repeats a block once per item.",
        "for n in [1, 2, 3]:\n    print(n)",
        "Press F6 to watch a loop run.",
    ),
    "while": (
        "Repeats a block as long as a condition is true.",
        "while n > 0:\n    n -= 1",
        "Make sure something changes, or it never stops (Ctrl+C stops it).",
    ),
    "if": ("Runs a block only when a condition is true.", "if age >= 18:\n    print('adult')", ""),
    "elif": ("Another condition, checked only if the ones before were false.", "elif age >= 13:", ""),
    "else": ("Runs when no condition above was true.", "else:", ""),
    "break": ("Leaves the loop now.", "if found:\n    break", ""),
    "continue": ("Skips to the next round of the loop.", "if n < 0:\n    continue", ""),
    "import": ("Loads a module so you can use it.", "import random\nrandom.randint(1, 6)", ""),
    "try": (
        "Runs code that might fail, and handles the error.",
        "try:\n    n = int(text)\nexcept ValueError:\n    n = 0",
        "",
    ),
    "lambda": ("A tiny one-line function.", "sorted(words, key=lambda w: len(w))", ""),
    "in": ("Checks membership, or loops over items.", '"a" in "cat"   # True', ""),
    "not": ("Flips True and False.", "if not done:", ""),
    "and": ("True only if both sides are true.", "if age > 12 and age < 20:", ""),
    "or": ("True if either side is true.", 'if day == "sat" or day == "sun":', ""),
    "is": (
        "Checks it's the very same object. Use it for None.",
        "if x is None:",
        "Use == to compare values.",
    ),
    "pass": ("Does nothing: a placeholder for code you'll write later.", "def todo():\n    pass", ""),
    "global": (
        "Lets a function change a variable defined outside it.",
        "global score",
        "Returning a value is usually clearer.",
    ),
    "randint": ("A random whole number, both ends included.", "random.randint(1, 6)", ""),
    "choice": ("A random item from a list.", "random.choice(names)", ""),
}
