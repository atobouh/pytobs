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
pytobs .              # open in this folder and pick a file with Ctrl+P
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

| Key | Does |
|---|---|
| **Ctrl+R** or **F5** | Save and run |
| **Ctrl+C** | Stop the program (copies instead when text is selected) |
| **Ctrl+E** | Jump to the line that raised the error |
| **Ctrl+P** | Open a file in this folder |
| **Ctrl+N** | New scratch file |
| **Ctrl+K** | All commands, including Install a package |
| **Alt+F** or **F8** | Format with ruff |
| **Ctrl+/** | Comment or uncomment lines |
| **Ctrl+D** | Duplicate line (in the input box: end of input) |
| **Ctrl+B** | Output beside or below the editor |
| **Ctrl+L** | Clear output |
| **Tab / Enter** | Accept a suggestion · **Esc** closes it |
| **Ctrl+Q** | Save and quit |

Files save automatically one second after you stop typing.

## What it does

- **Runs your code in its own process** with your project's Python: the nearest `.venv`, then the `py` launcher, then `python` on PATH. The interpreter is shown in the status bar.
- **Live output and input.** `input()` works: type in the box under the output.
- **Readable errors.** The exception first, then your line with Python's own markers. Library frames are hidden. Click the location or press Ctrl+E to jump there.
- **Suggestions as you type** (Jedi, in a separate process so typing never waits), with signature and docs beside the list.
- **ruff** checks while you pause. A dot in the margin marks the line; the message shows in the status bar when your cursor is on it.

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
