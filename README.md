# pytobs

A quiet, fast Python editor for the terminal. Write a script, press **Ctrl+R**, read the output, fix it.

Built for Windows Terminal, and it works anywhere Python 3.10+ runs.

## Install on Windows

Open **PowerShell** and paste:

```powershell
irm https://raw.githubusercontent.com/atobouh/pytobs/main/install.ps1 | iex
```

That installs [uv](https://docs.astral.sh/uv/) if you don't have it, installs pytobs, and runs `pytobs --setup`. Setup adds:

- **Geist Mono**, the font pytobs is designed around (per-user, no admin needed)
- a **pytobs** profile in Windows Terminal with the Sumi colours, padding and font
- **Edit with pytobs** on the right-click menu for `.py` files
- a **pytobs** entry in the Start menu

After that, `pytobs` works from any terminal:

```powershell
pytobs                # reopen your last file, or start a scratch file
pytobs hello.py       # open (or create) a file
pytobs .              # open in this folder; Alt+E shows its files
```

Until this work is merged into `main`, install from its branch:

```powershell
$env:PYTOBS_REF = "claude/tender-cerf-wakv7x"
irm https://raw.githubusercontent.com/atobouh/pytobs/claude/tender-cerf-wakv7x/install.ps1 | iex
```

Manual install, if you prefer:

```powershell
uv tool install --compile-bytecode git+https://github.com/atobouh/pytobs
pytobs --setup
```

To remove everything: `pytobs --uninstall` and then `uv tool uninstall pytobs`.

## Keys

**Run and learn**

| Key | Does |
|---|---|
| **Ctrl+R** or **F5** | Save and run |
| **F6** | Watch it run: step through your code line by line (← → to step, Esc to finish) |
| **Ctrl+T** | Run every `test_` function in this file |
| **F1** | Explain the word under the cursor in plain English (`print`, `.sort`, `for`, your own functions) · on a line with a ruff ● problem: the full message, the spot, and ruff's explanation of the rule (click the ● or the status bar too) |
| **Tab** after `for`, `if`, `def`, `class`, `try`, `main`, … | Write the whole block; Tab again jumps to the next blank (Ctrl+K → Snippets lists them all) |
| **Ctrl+G** | Your progress: streak, runs, coding time, errors you meet most |
| **Ctrl+E** | Jump to the line that raised the error |
| **Ctrl+C** | Copy selected text (drag over the output to select) · otherwise stop the running program |

**Files**

| Key | Does |
|---|---|
| **Ctrl+N** | New file: type a name like `loops.py` or `week2/loops.py` (empty = scratch file) |
| **Ctrl+S** | Save · on a scratch file it asks for a name first |
| **Alt+E** | Files sidebar: Enter opens · **n** new file · **f** new folder · **r** rename · **Delete** delete |
| **Ctrl+P** | Open a file in this folder (opens in a new tab) |
| **Alt+← / Alt+→** or **Ctrl+PgUp / Ctrl+PgDn** | Previous / next open file · **Alt+1 … Alt+9** jump to one |
| **Ctrl+W** | Close the file in focus (click × or middle-click a tab too) |
| **Ctrl+K → Save as / Rename file** | Name or rename the file in focus |

**Moving around**

| Key | Does |
|---|---|
| **Ctrl+O** | Outline: your functions and classes, type to filter · `:42` goes to line 42, adding empty lines if the file is shorter |
| **Click below the code** | Creates the lines down to where you clicked, no Enter-Enter-Enter (empty lines at the end are never saved to the file) |
| **Ctrl+F** | Find and replace · ↑ ↓ or Enter between matches · Tab to the replace box, Enter replaces one · **Alt+A** replaces all |
| **F9** | Fold or unfold the `if` / `for` / `def` / `class` the cursor is in (or click ▾ ▸ beside the line number) · Ctrl+K → Fold all |
| **F12** | Go to where a name is defined · **Shift+F12** back |

**Editing**

| Key | Does |
|---|---|
| **Ctrl+A** | Select everything |
| **Shift+↑ ↓**, then **Backspace** / **Ctrl+X** | Delete / cut every selected line |
| **Ctrl+Shift+K** | Delete the selected lines (whole lines, even if only partly selected) |
| **Alt+↑ / Alt+↓** | Move lines up / down |
| **F2** | Rename a variable or function everywhere in this file (strings and comments are left alone) |
| **Ctrl+/** | Comment or uncomment lines |
| **Ctrl+D** | Duplicate line (in the input box: end of input) |
| **Ctrl+Z / Ctrl+Y** | Undo / redo |
| **Alt+F** or **F8** | Format with ruff |

**Window**

| Key | Does |
|---|---|
| **Ctrl+K** | All commands, including Install a package |
| **Ctrl+J** | Hide the output panel so the code gets the full width · running (Ctrl+R, F6, Ctrl+T) brings it back |
| **Ctrl+B** | Output beside or below the editor |
| **Ctrl+L** | Clear output · **Ctrl+K → Copy all output** copies everything |
| **Tab / Enter** | Accept a suggestion · **Esc** closes it |
| **Ctrl+Q** | Save and quit |

Files save automatically one second after you stop typing.

## What it does

- **Runs your code in its own process** with your project's Python: the nearest `.venv`, then the `py` launcher, then `python` on PATH. The interpreter is shown in the status bar.
- **Several files open, one in focus.** Every file you open gets a tab along the top; the focused one
  blends into the editor and an accent dot marks unsaved changes. Each tab keeps its own cursor, scroll
  position and undo history, and your open tabs come back the next time you start pytobs.
- **Live output and input.** `input()` works: type in the box under the output.
- **Readable errors.** The exception first, then your line with Python's own markers. Library frames are hidden. Click the location or press Ctrl+E to jump there.
- **Suggestions as you type** (Jedi, in a separate process so typing never waits), with signature and docs beside the list.
- **ruff** checks while you pause. A dot in the margin marks the line; the message shows in the status bar when your cursor is on it.

## Learning tools

All four are plain, deterministic Python: no AI, no internet, the same input always gives the same result.

- **Explain this error.** Under every traceback, a short note on what the error means and, when it can be
  stated with certainty, a corrected line built from your code. About 45 rules cover the errors learners
  meet most (wrong argument counts, str + int, None from .sort(), index out of range, missing keys, typos,
  indentation, a file named random.py, …). Any other built-in error gets a one-line meaning.
- **Watch it run (F6).** Records every line your file executes and the variables at that moment, then lets
  you step through it. Changed values are highlighted, lists are drawn as boxes with the loop's position
  marked, dicts as key → value. Library internals are not recorded; recording stops after 5,000 steps
  while the program keeps running.
- **Tests (Ctrl+T).** Any function named `test_…` in the file is a test. You get a dot per test and, for
  `assert a == b`, the expected and actual values. Code under `if __name__ == "__main__":` doesn't run.
- **Your progress (Ctrl+G).** A 16-week activity grid, streak, runs and coding time this week, errors
  fixed, and your most frequent errors with the concept to review. Stored only on your computer.

## Packages

**Ctrl+K → Install a package**, type a name like `requests`, press Enter. pytobs creates a `.venv` in your
project folder the first time and installs into it; the status bar switches to it and suggestions include
the new package. **Ctrl+K → How to install packages** shows the steps again, including the PowerShell way:

```powershell
cd your-project
uv venv
uv pip install requests
```

## Settings

Optional. Create `%APPDATA%\pytobs\config.toml` (or `~/.config/pytobs/config.toml`):

```toml
python = "C:/path/to/python.exe"   # force an interpreter
format_on_save = false
autosave = true
```

Scratch files live in `%LOCALAPPDATA%\pytobs\scratch`.

## Develop

```sh
uv venv && uv pip install -e ".[dev]"
pytest
```

Design notes and benchmarks: `docs/PROPOSAL.md`, `docs/visual/index.html`, `research/`.

Geist Mono is © The Geist Project Authors, under the SIL Open Font License (`src/pytobs/assets/fonts/OFL.txt`).
