# pytobs: proposal for a lightweight, premium terminal Python tool

Status: **for review. No product code until this is confirmed.**
Working name: `pytobs` (the repo name). Brief: `research-brief.md` (goal, non-goals, deliverables).

**Update (Oct 6):** target OS is **Windows** (Windows Terminal). One direction chosen for speed and reliability: **A "Sumi"** with Textual, Jedi in a worker process, and ruff. The visual version of this proposal, with screens rendered by Textual in the chosen theme, is in `docs/visual/index.html`; the mockup script is `research/mockup/mock.py`. Windows notes: interpreter lookup is `.venv\Scripts\python.exe`, then the `py` launcher; stop uses `CTRL_BREAK_EVENT` to the process group, then ends the process tree; Windows Terminal supports truecolor and OSC 52, and the legacy console gets the 256-colour theme.

---

## 0. TL;DR

| Decision | Recommendation | Why (short) |
|---|---|---|
| Product shape | **Editor + run pane**, not a REPL | Matches the "write → run → fix" loop; files persist, and no hidden state accumulates between runs |
| UI framework | **Textual** (Rich renders the output) | Only option with a real layout/CSS/theme system, which matters because the look is the main focus. Costs about 80–100 ms more startup than prompt_toolkit |
| Editor widget | **Subclass Textual `TextArea`** | Undo/redo, selection, bracket matching and tree-sitter are built in. We add auto-indent, auto-close and **viewport-limited highlighting** (measured: 153 → 46 ms per key on a 6.3k-line file) |
| Highlighting | **tree-sitter** (bundled via TextArea) | About 10× faster than Pygments on full parses, incremental, and the viewport query costs 0.4 ms |
| Completion | **Jedi in a separate worker process**, behind a small backend interface; **ty** as an optional backend now and a candidate default at 1.0 | Jedi is pure Python, mature, and gives good signatures and docstrings. A worker process is required because Jedi in a thread stalls the UI by up to 66 ms (GIL) |
| Run | `asyncio` subprocess with pipes, `-u`, its own process group, SIGINT then SIGKILL | Isolated, streams live, stop always works |
| Lint/format | `ruff` subprocess over stdin, debounced | 16–24 ms per call, so it can run on idle, not only on save |
| Look | 3 directions below; recommend **A "Sumi"**: borderless, separated by tone, one accent | Restrained and calm, and it survives the 256-colour fallback best |
| Packaging | `uv tool install pytobs` (bytecode precompiled) / `pipx` | One command |

**Main risk:** the 150 ms startup target. On the reference VM, Textual reaches first paint in about 260–320 ms. Section 9 proposes a revised budget and mitigations, and I need a decision from you there.

---

## 1. Product shape

### Editor + run pane vs upgraded REPL + scratch buffer

| | Editor + run pane | REPL + scratch buffer (ptpython/bpython style) |
|---|---|---|
| Mental model | A file you run, like PyCharm | A live session you poke |
| State | Fresh process each run, so results are reproducible | Accumulates hidden state (stale variables, re-imports), which confuses learners |
| Multi-line programs | Natural | Awkward beyond ~20 lines |
| Output | Separate pane with history and timing | Interleaved with input |
| Exploration | Weaker (rerun everything) | Strong |
| PyCharm replacement for small scripts | Yes | Partial |

**Recommendation: editor + run pane.** For later (post-v1): "run, then drop into an inspect prompt" (`python -i` semantics) in the output pane, which brings back the REPL's main advantage without making it the core model.

### Core loop and keystroke count

```
edit ──Ctrl+R──▶ (auto-save + run) ──▶ output streams in
  ▲                                         │
  └──── fix ◀──Ctrl+E (jump to error line)──┘   (Ctrl+R again kills the old run and reruns)
```

- **1 chord per iteration** when there's no error (Ctrl+R), **2** with an error (Ctrl+E, fix, Ctrl+R). PyCharm's equivalent is Shift+F10, plus a mouse click to reach the traceback line.
- `F5` is an alias for Ctrl+R. Ctrl+Enter is *not* the primary key: most terminals can't distinguish it without the kitty keyboard protocol.

### Smallest feature set that makes PyCharm unnecessary for small scripts

1. Open/create/save `.py` files; fuzzy file switcher scoped to the current folder (not a project system).
2. Editing: auto-indent, bracket auto-close and match, undo/redo, selection, clipboard, comment toggle.
3. Syntax highlighting.
4. Completion popup with signature hint and docstring preview.
5. Run: live output, stdin, stop, elapsed time, exit code, readable traceback with jump-to-line.
6. Interpreter/virtualenv detection with a visible indicator.
7. Ruff diagnostics in the gutter and format-on-demand.
8. Session restore and an always-available scratch file.

Explicitly out (per brief): projects, plugins, git, debugger, other languages.

---

## 2. TUI framework

### Measured (reference VM, see §11 for setup)

Startup is the time from launch until the process exits right after its first paint, under a 120×40 pty: median of 7 runs, bytecode precompiled.

| Stack (editor + output pane) | Launch → exit after first paint | Max RSS | Idle CPU / RSS, empty | Idle CPU / RSS, 6.3k-line file |
|---|---|---|---|---|
| `python -c pass` (floor) | 19 ms | n/a | n/a | n/a |
| Rich only (print highlighted code, no UI) | 113 ms | 17 MB | n/a | n/a |
| prompt_toolkit (TextArea + PygmentsLexer) | 222–235 ms | 32 MB | 0.3 % / 32 MB | 12.3 % / 45 MB* |
| Textual (TextArea + tree-sitter) | 580 ms (incl. ~180 ms teardown) | 36 MB | 0.7 % / 37 MB | 3.3 % / 58 MB |

\* prompt_toolkit keeps re-lexing in the background after opening a large file.

Textual startup by phase (ms since process start, 3 runs):

| Variant | `import textual.app` | Compose | Mount | **First paint** |
|---|---|---|---|---|
| Static text only | 135–180 | 155–209 | 156–211 | **182–239** |
| TextArea, no language | 171–191 | 196–223 | 203–233 | **248–293** |
| TextArea + tree-sitter Python | 150–182 | 170–205 | 221–273 | **262–321** |

About half of the Textual import is `asyncio` (53 ms on this VM) plus the CSS/layout engine. Any async framework pays the `asyncio` part, prompt_toolkit included.

**Keystroke latency** (pty: key written → terminal output complete, median / p95, 60 keys, cursor at line 1000 or at the end of the file):

| File size | Textual (stock) | Textual, viewport highlighting (spike) | prompt_toolkit |
|---|---|---|---|
| 365 lines | 17.9 / 28.8 ms | n/a | 16.1 / 23.9 ms |
| 300 lines | 21.1 / 50.0 ms | n/a | n/a |
| 1,000 lines | 31.2 / 57.7 ms | **20.9 / 32.2 ms** | n/a |
| 2,500 lines | 76.6 / 115.2 ms | n/a | n/a |
| 6,357 lines | 157.9 / 216.3 ms | **50.5 / 82.9 ms** | 40.2 / 391 ms, and 14 of 60 keys took >400 ms |
| 6,357 lines, no highlighting | 32.1 / 66.5 ms | n/a | n/a |

Root cause of the stock Textual slowdown: `TextArea._build_highlight_map()` re-queries the **whole** syntax tree and rebuilds a per-line map on every edit, with no point range. A 25-line subclass that queries only the visible window ±1 screen (`tx_type_vp.py`) removes most of the cost. The remaining cost at 6k lines is document wrapping and the incremental reparse.

### Comparison

| | Textual | prompt_toolkit | Rich alone |
|---|---|---|---|
| Startup to first paint (measured) | ~260–320 ms | ~200 ms | ~110 ms (no interactivity) |
| Idle memory (measured) | 37–58 MB | 32–45 MB | 17 MB |
| Editor widget | `TextArea`: undo/redo, selection, soft wrap, line numbers, bracket match, tree-sitter, themes. No auto-indent or auto-close (small additions) | `Buffer`/`TextArea`: excellent editing heritage (ptpython, IPython), vi/emacs modes built in | None |
| Layout | CSS-like (padding, margin, borders, `fr` units, docking, layers), so a custom look is cheap | `HSplit`/`VSplit`/`Float`; no padding/border model beyond `Frame`, so a premium look means hand-drawing | Static renderables only |
| Theming | Theme objects with semantic variables (`$primary`, `$surface`, …) and `TextAreaTheme` for syntax | Style strings / Pygments styles | Styles |
| Resize | Automatic re-layout | Automatic | n/a |
| Truecolor + fallback | Yes; auto-downgrades via Rich | Yes | Yes |
| Popups/overlays | Layers, `ModalScreen`, built-in command palette | `Float` + `CompletionsMenu` (built in) | No |
| Testing | Pilot + SVG snapshot tests | Manual | n/a |
| Cross-platform | Linux, macOS, Windows Terminal | Same | Same |

**Recommendation: Textual, with Rich for output and traceback rendering.** prompt_toolkit wins on raw startup and has a superior editing core (vi mode, completion menu), but "premium, restrained, polished" is the main goal, and doing that in prompt_toolkit means rebuilding a layout and styling system that Textual already has. Textual's editor gaps are small and well understood, as shown above. The startup cost is the price, and §9 deals with it.

---

## 3. Autocomplete

### Measured

"Cold" is the first request for that module in a fresh process; "warm" is a repeat (typing within the same expression).

| Backend | Init | `os.path.` cold / warm | `json.` | Local class attr | `textual.app.App.` (420 items) | Server RSS |
|---|---|---|---|---|---|---|
| **Jedi** (in-process, 0.20.0) | import 105 ms | 1,710 / 27 ms† | 25 / 3 ms | 34 / 17 ms | 688 / 54 ms | 73 MB |
| python-lsp-server 1.15 (Jedi + plugins) | 196 ms | 494 / 56 ms | 428 / 68 ms | 460 / 93 ms | 246 / 67 ms | 118 MB |
| pyright 1.1.414 (Node) | 431 ms | 692 / 16 ms | 13 / 7 ms | 32 / 19 ms | 1,095 / 140 ms | 237 MB |
| **ty 0.0.84** (Rust, beta) | **5 ms** | 64 / 2 ms | 5 / 1 ms | 1 / 1 ms | 261 / 13 ms | 83 MB |

† The first-ever Jedi call loads builtins and typeshed stubs. That is a one-time cost per process, so we pay it with a background warm-up right after launch, never on the first keystroke.

Jedi extras: `get_signatures` 2 ms, `docstring()` 4 ms (warm).

**Threads are not enough.** Running a cold Jedi completion in a thread made the main event loop's 1 ms ticks stall by up to **66 ms** (p99 13 ms), because of the GIL. Completion must run in a **separate process**.

### Recommendation

- **v1: Jedi in a dedicated worker process.** The worker runs in pytobs's own environment but points Jedi at the *user's* interpreter (`jedi.create_environment(venv)`), so completions match the code being run. Protocol: newline-delimited JSON over the worker's stdin/stdout: `complete`, `signatures`, `docstring`, `cancel`.
- **Backend interface** shaped like LSP (`complete(text, line, col) → items`, `signature(...)`, `doc(item)`) so **ty** can be a drop-in backend. ty is already the fastest and lightest here, but it is still 0.0.x/beta. Re-evaluate making it the default at ty 1.0.
- pylsp: no advantage over Jedi directly (it *is* Jedi plus overhead). pyright: heaviest (Node, 237 MB) and slowest to start. Both rejected for v1.

### Async rules (typing must never wait)

1. Every keystroke updates the buffer and paints first. Completion requests are fire-and-forget with a generation counter.
2. Debounce: trigger immediately on `.`, otherwise after 60 ms of idle while typing an identifier. Never request on whitespace.
3. Responses with a stale generation (the user kept typing) are dropped. Cancel the in-flight request if possible.
4. While a request is pending, filter the previous result set client-side (prefix/fuzzy match), so the menu updates instantly as you type.
5. The worker is spawned **after first paint** and warmed with `import builtins`, the file's own imports, and `os`/`json`/`pathlib`.

### Menu UX

- **Placement:** anchored at the start of the word being completed (not at the cursor), below the line; flips above when there's no room. Max 8 rows, width fits the longest label up to 40 cols.
- **Row:** `label` + muted kind glyph on the right (`ƒ` function, `c` class, `m` module, `·` other; plain letters, no Nerd Font needed).
- **Docstring preview:** a side panel to the right of the menu (Helix-style) showing the signature and the first ~8 lines of the docstring, fetched lazily for the highlighted item only.
- **Signature hint:** inside `(`, a one-line hint *above* the cursor line with the current parameter in the accent colour; it disappears on `)` or Esc.
- Keys: Tab/Enter accept, Esc dismiss, Ctrl+Space force-open, ↑↓ / Ctrl+N/P navigate.

---

## 4. Editing core

Build on `TextArea` with a subclass `CodeEditor`. Built in and kept: undo/redo (Ctrl+Z / Ctrl+Y), selection (Shift+arrows, Ctrl+Shift+arrows, select line, select all), word delete, bracket matching highlight, line numbers, soft wrap, tab→indent, paste.

To add (all small and local):

| Feature | Behaviour |
|---|---|
| Auto-indent | Enter keeps the current indent; adds +4 after a trailing `:`; dedents after `return`/`pass`/`break`/`continue`/`raise` |
| Smart backspace | In leading whitespace, deletes back to the previous indent stop |
| Auto-close | `( [ { ' "` insert pairs; typing the closer skips over it; no auto-close inside strings or before identifier characters |
| Comment toggle | Ctrl+/ (also Ctrl+_, since many terminals send that for Ctrl+/) on the line or selection |
| Viewport highlighting | Override `_build_highlight_map` to query the visible range ±1 screen, and rebuild on scroll |
| Clipboard | `App.copy_to_clipboard` (OSC 52) with a fallback to `pbcopy`/`wl-copy`/`xclip`, because OSC 52 doesn't work in macOS Terminal.app or GNOME Terminal |
| Diagnostics layer | Per-line gutter markers and an optional underline style range |

**Keybindings:** modern defaults (Ctrl+S/Z/Y/C/X/V/F, Ctrl+P files, Ctrl+K command palette, Ctrl+R run, Ctrl+E jump to error, Ctrl+Q quit). Keymap is a data table in config, so vim/emacs layers can be added later without touching widgets. Note: Ctrl+Shift+letter and Ctrl+Enter aren't reliably distinguishable in terminals, so no default binding depends on them.

**Custom buffer?** No. Writing our own buffer means owning undo, wrapping, selection, IME/wide characters and rendering, which is weeks of work for nothing visible. The one risk is that `_build_highlight_map` is a private method, so we pin Textual's minor version, cover it with a snapshot test, and offer the change upstream.

---

## 5. Syntax highlighting

| File | Pygments, full lex | Pygments, 60-line view | tree-sitter full parse | Incremental reparse after 1-char edit | Full highlight query | Viewport query (60 lines) |
|---|---|---|---|---|---|---|
| argparse.py (2,690 lines) | 134 ms | 2.7 ms | 15.9 ms | 2.8 ms | 23.7 ms | 0.45 ms |
| typing.py (3,846) | 173 ms | 2.0 ms | 18.8 ms | 2.0 ms | 17.7 ms | 0.40 ms |
| _pydecimal.py (6,357) | 209 ms | 1.3 ms | 20.2 ms | 5.7 ms | 26.4 ms | 0.33 ms |

**tree-sitter**, because it's what TextArea uses, about 10× faster on full parses, incremental, and it gives a real syntax tree, which helps with auto-indent decisions and "inside a string?" checks for auto-close. Pygments stays for one thing: highlighting code snippets in tracebacks and docstrings via Rich, where inputs are small.

Install only `tree-sitter-python`, not `textual[syntax]`, which pulls about 15 grammars we don't need.

**Mapping onto tokens:** tree-sitter capture names (`keyword`, `string`, `comment`, `function`, `type`, `number`, `constant.builtin`, …) map to a small set of **syntax roles** in the theme (§8.6), and the roles map to colours. Restraint rule: **at most 4 syntax hues** plus text and muted text. Keywords, strings, functions/types and numbers/constants each get one hue. Comments are muted and italic where supported. Everything else (variables, operators, punctuation) uses the plain text colour. Most "rainbow" themes fail this test, and it's a large part of what reads as calm.

---

## 6. Running code

- **Subprocess, never in-process.** `asyncio.create_subprocess_exec(python, "-u", file)` with `PYTHONUNBUFFERED=1`, `PYTHONIOENCODING=utf-8`, cwd = the file's folder. Spawn overhead measured at 18–24 ms.
- **Streaming:** stdout and stderr are read concurrently and appended as lines in arrival order, tagged so stderr renders in a muted error tint. The output pane is a virtualised log (Textual `Log`/`RichLog`), capped at 10k lines with a "… N earlier lines" marker.
- **stdin:** while a run is active, the output pane's last line is an inline input field. Enter sends the line to the process's stdin and echoes it. Ctrl+D sends EOF.
- **Stop:** the process starts in its own process group/session. Stop sends SIGINT (so the user sees a normal `KeyboardInterrupt`), then SIGKILL to the group after 1 s. On Windows: `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT`, then `TerminateProcess`. Rerunning implies stop.
- **Timeouts:** off by default, with a live elapsed timer in the pane header. An optional `run.timeout_s` in config.
- **pipes vs pty:** v1 uses pipes (portable, simple). The cost is that the child sees no TTY, so `isatty()` is false, colours are off and progress bars degrade. Post-v1: an optional pty mode on POSIX.
- **Tracebacks:** parse stderr with the stable CPython format (`File "…", line N, in …`, plus 3.11+ `^^^^` caret lines). Render with Rich: frames in the user's own file at full contrast with the source line highlighted; library/stdlib frames dimmed and collapsed to one line ("+ 4 library frames"). The final `Error: message` line uses the error colour. Each user frame is clickable, and Ctrl+E jumps to the deepest user frame. No code is injected into the child process.
- **Virtualenv detection order** (first hit wins, always shown in the status bar, switchable from the palette):
  1. CLI flag / config `python = …`
  2. `$VIRTUAL_ENV`
  3. `.venv/` or `venv/` in the file's folder, then each parent up to `$HOME`
  4. `python3` on `PATH` (never pytobs's own isolated interpreter, which won't have the user's packages)
- **Run history:** every run records start time, duration (monotonic, spawn → exit), exit code, interpreter, and a hash of the file contents. The header shows `run 7 · 0.41 s · exit 0`. Ctrl+H opens the last 20 runs; selecting one shows its captured output. In memory only for v1.

---

## 7. Lint and format

- `ruff check --output-format=json --stdin-filename <path> -`, fed the **unsaved buffer** over stdin. Measured 16–19 ms, about 18 MB transient. Runs after 400 ms of typing idle and on save; the previous request is cancelled if a newer one starts.
- `ruff format -` on demand (palette or Alt+F) and optionally on save (config, default off for learners). Measured 19–24 ms.
- Respects the user's `pyproject.toml`/`ruff.toml` if present; otherwise pytobs's defaults (`E`, `F`, `W`, `I`, `B`; no pedantic rules).
- **Low-clutter diagnostics:**
  - A gutter dot only (`●` in warning/error colour, at reduced intensity), no inline text by default.
  - A faint underline on the exact range if the terminal supports styled underlines; otherwise nothing.
  - The message for the cursor's line appears in the status bar, e.g. `F841 local variable 'x' is assigned to but never used`.
  - A counter in the status bar (`ruff 2`) opens the full list.
  - Optional "virtual text" mode (message at end of line, muted) for people who want it.

---

## 8. Visual design

### 8.1 What makes premium TUIs feel premium

Observations from the reference apps:

| App | What it gets right | What we take |
|---|---|---|
| **Helix** | Almost no chrome; one statusline; popups with a docs panel to the side; themes defined as *palette + roles* | Docs-beside-menu completion; palette/role theme split |
| **lazygit** | Titled panels, the focused panel's border changes colour, a key-hint bar at the bottom | Focus shown by *one* accent change; contextual key hints |
| **Zellij** | Rounded frames, a contextual keybinding bar that changes with mode | Hints that change with context (running vs editing) |
| **btop** | Rounded boxes with titles in the border, braille graphs, gradients | Titles-in-borders (direction C); otherwise too loud |
| **Posting** (Textual) | Semantic theme variables, command palette, jump mode, consistent 1-cell padding | Textual theme variables, palette-first discoverability |
| **Harlequin** (Textual) | IDE layout in a terminal: editor + results, polished TextArea | Proof that Textual can carry an editor + results product |
| **Frogmouth** (Textual) | Calm reading layout, generous margins | Margins around prose (docstrings, tracebacks) |
| **Charm / Bubble Tea / Lip Gloss** | Generous padding, adaptive light/dark colours, few boxes, careful alignment | Padding over borders; light/dark detection |

Rules for this tool:

1. **Hierarchy by tone, not lines.** Separate regions with background steps of a few % lightness; use lines only where tone can't do it.
2. **One accent colour**, used for focus, cursor, primary state (running) and the active parameter. Red/green/yellow are **state only** (error/ok/warn), never decoration.
3. **Spacing:** 1 cell horizontal padding in panes, 2 in popups, 1 blank row above section titles, nothing touching an edge.
4. **Type through weight and dimness:** bold only for titles and the active item; dim for secondary text; italics only for comments.
5. **Quiet by default:** cursor blink off (calmer, and it avoids a full redraw every 500 ms), no spinners except while a run is active, no toasts for routine events.
6. **Consistent glyph set** (§8.5). No emoji.

### 8.2 Palette research

WCAG contrast ratios computed from the official hex values (fg = default text, sub = secondary text, muted = comments/line numbers, accent = the colour we'd use as the single accent, panel = the darker background step).

| Palette | fg/bg | sub/bg | muted/bg | accent/bg | fg/panel | Character |
|---|---|---|---|---|---|---|
| Catppuccin Mocha | 11.3 | 7.4 | 3.4 | 8.1 (mauve) | 12.1 | Pastel, playful, popular |
| Rosé Pine | **13.4** | 5.5 | 3.4 | 10.5 (rose) | 12.5 | Soft, romantic, low saturation |
| Tokyo Night | 10.6 | 8.1 | **2.8** ⚠ | 6.8 (blue) | 11.1 | Cool, neon-leaning |
| Kanagawa Wave | 11.3 | 8.9 | 3.3 | 5.9 (crystal blue) | 12.4 | Warm ink-on-paper, muted |
| Everforest Dark | 7.4 | 5.1 | **3.8** | 6.2 (green) | 8.6 | Lowest contrast; very easy on the eyes |

- All pass AA (4.5) for body text by a wide margin. Very high contrast (>12) can feel harsh in long sessions; 7–11 is a comfortable range.
- The **muted** role (comments, line numbers) sits around 3.3 in most palettes. That's fine for incidental text (WCAG doesn't require it), but Tokyo Night's 2.8 is too faint. We lift muted to **≥ 3.5** in our tokens.
- **256-colour fallback test** (Rich's downgrade of the four background layers):
  - Rosé Pine, Tokyo Night and Catppuccin: bg and panel both collapse to **pure black `#000000`**, and the next layer becomes **navy `#00005f`**. That looks broken.
  - Kanagawa and Everforest (neutral/warm greys) keep **4 of 4** layers distinct on the grey ramp.
  - Conclusion: every theme ships a **hand-tuned 256-colour variant** (greys from the 232–255 ramp), not an automatic downgrade.
- Truecolor is now near-universal: iTerm2, kitty, WezTerm, Ghostty, Alacritty, Windows Terminal, and macOS Terminal.app from macOS 26 (Tahoe). Older Terminal.app is 256-colour only. Detect via `COLORTERM=truecolor|24bit`, otherwise use the 256 variant.

### 8.3 Visual directions

All three share the same layout grammar, keybindings and token system; only tokens and border style differ, so switching is a config change.

---

#### Direction A: "Sumi" (recommended)

Based on Kanagawa Wave, warm. **Borderless:** panes are separated by tone, not lines. **One accent: crystal blue.** Side-by-side layout.

| Token | Hex | Role |
|---|---|---|
| `base` | `#1F1F28` | editor background |
| `mantle` | `#1A1A22` | output pane, status bar (one step darker) |
| `surface` | `#2A2A37` | popups, cursor line, selection-inactive |
| `overlay` | `#363646` | selection, active menu row |
| `text` | `#DCD7BA` | body text (11.3:1) |
| `text_muted` | `#8A8980` | comments, line numbers, hints (4.7:1) |
| `accent` | `#7E9CD8` | focus, cursor, running state, active parameter |
| `error` / `warn` / `ok` | `#E46876` / `#E6C384` / `#98BB6C` | state only |
| syntax | keyword `#957FB8`, string `#98BB6C`, function/type `#7FB4CA`, number/const `#D27E99` | 4 hues |

```
 main.py                                         ┊ ▸ run 3 · 0.41 s · exit 0
                                                 ┊
   1  import json                                ┊   loading 3 records
   2  from pathlib import Path                   ┊   {'id': 1, 'name': 'ada'}
   3                                             ┊   {'id': 2, 'name': 'grace'}
   4  def load(path: Path) -> list[dict]:        ┊   {'id': 3, 'name': 'linus'}
   5      with path.open() as f:                 ┊
   6          return json.lo▏                    ┊
                         load    ƒ   load(fp, *, cls=None, …)
                         loads   ƒ                              ┊
                                     Deserialize fp (a .read()- ┊
                                     supporting file) to a      ┊
                                     Python object.             ┊
                                                 ┊
 ~/code/scratch · .venv 3.13 · ruff ✓ · Ln 6:26        ^R run  ^P files  ^K ⋯
```
Legend: `┊` is **not drawn**. It marks where the background steps from `base` to `mantle`. The completion menu and docs panel are `surface`-coloured blocks with no border. The only accent pixels on screen are the cursor, the active menu row's left edge and `▸ run`.

Why recommended: the calmest, closest to the "restrained" brief, survives 256-colour (warm greys), and has nothing decorative to maintain.

---

#### Direction B: "Dawn/Pine" (Rosé Pine)

**Hairline rules, stacked layout** (output below the editor, as a drawer that opens on first run). **Accent: rose.** Best for narrow terminals (<100 cols) and laptops. Ships with a light variant (Rosé Pine Dawn).

| Token | Hex (dark) | Hex (Dawn, light) |
|---|---|---|
| `base` | `#191724` | `#FAF4ED` |
| `mantle` | `#1F1D2E` | `#FFFAF3` |
| `surface` | `#26233A` | `#F2E9E1` |
| `rule` | `#403D52` | `#DFDAD9` |
| `text` | `#E0DEF4` | `#575279` |
| `text_muted` | `#908CAA` | `#797593` |
| `accent` | `#EBBCBA` | `#B4637A` (Dawn "love"; Dawn "rose" `#D7827E` is only 2.6:1 on `#FAF4ED`, too faint for a cursor) |
| syntax | keyword `#C4A7E7`, string `#F6C177`, function `#9CCFD8`, const `#EB6F92` | Dawn equivalents |

```
  main.py                                                      .venv · 3.13
  ─────────────────────────────────────────────────────────────────────────
     4  def load(path: Path) -> list[dict]:
     5      with path.open() as f:
     6          return json.load(f)
     7
     8  for row in load(Path("data.json")):
  ●  9      print(row["nmae"])
  ── output ──────────────────────────────────────── run 4 · 0.08 s · exit 1
     Traceback
     › main.py:9 in <module>
         print(row["nmae"])
               ~~~^^^^^^^^
       + 0 library frames
     KeyError: 'nmae'                                  ^E  jump to line 9
  ─────────────────────────────────────────────────────────────────────────
  ^R run  ^E error  ^P files  ^K commands                         Ln 9:18
```

---

#### Direction C: "Console" (Tokyo Night, muted lifted)

**Rounded panels with titles in the border** (lazygit/btop/Posting family). Focused panel border in the **accent (blue)**, unfocused in a faint grey. Denser, more "app-like"; the most familiar to people coming from GUI IDEs.

| Token | Hex |
|---|---|
| `base` | `#1A1B26` |
| `mantle` | `#16161E` |
| `surface` | `#292E42` |
| `border` / `border_focus` | `#3B4261` / `#7AA2F7` |
| `text` | `#C0CAF5` |
| `text_muted` | `#737AA2` (lifted from `#565F89`, 2.8 → 4.1) |
| `accent` | `#7AA2F7` |
| syntax | keyword `#BB9AF7`, string `#9ECE6A`, function `#7DCFFF`, const `#FF9E64` |

```
╭─ main.py ────────────────────────────────╮╭─ output · run 5 ────────────╮
│  1  import time                          ││ step 1/3                    │
│  2                                       ││ step 2/3                    │
│  3  for i in range(3):                   ││ step 3/3                    │
│  4      print(f"step {i+1}/3")           ││ enter name: ada▏            │
│  5      time.sleep(0.5)                  ││                             │
│  6  name = input("enter name: ")         ││                             │
│                                          ││                             │
╰──────────────────────────────────────────╯╰─ ⠋ running 1.6 s · ^C stop ─╯
 .venv 3.13 │ ruff ✓ │ Ln 6:1                           ^R run  ^P files  ?
```
(Here the output panel is focused for stdin, so its border is in the accent colour.)

---

### 8.4 Motion (subtle only)

| Effect | Possible in Textual? | Cost | Verdict |
|---|---|---|---|
| Smooth scroll (wheel/PageDown) | Yes (animated `scroll_to`) | A few frames of full-pane redraw | **On** for page jumps, **off** for line-by-line |
| Popup fade/slide | Yes (opacity/offset animation) | 3–6 extra frames per open | **Off by default.** It delays the menu, and completion must feel instant |
| Cursor blink | Yes | A redraw every 500 ms | **Off by default** (calmer) |
| Run indicator | Spinner via timer | ~10 small redraws/s, run-time only | Braille spinner in the run header only while running |
| Output auto-follow | Yes | Negligible | Smooth follow; pauses when you scroll up, with a "↓ new output" pill |

Rule: **nothing animates on the typing path.** Every animation must cost at most one frame (16 ms) of main-loop time, checked in the bench harness. Textual batches each frame into a single write, which avoids tearing; whether it also emits DEC 2026 synchronized-output markers on supporting terminals is to be verified in M0.

### 8.5 Fonts and icons

- **Default: plain Unicode only**, from a set that is single-width in common monospace fonts: `● ○ ▸ ▾ › · ✓ ✗ ┊ │ ─ ╭ ╮ ╰ ╯ ⠋…⠏`. Avoid `⏵ ⏹ ⚠` and emoji (ambiguous or double width, so alignment breaks).
- **Optional Nerd Font mode** (`icons = "nerd"`): swaps the glyph table for Nerd Font codepoints (file-type icon in the tab, git-less folder icon in the file picker). Never required.
- Text styles: bold + dim are universal; italic for comments only (degrades silently); undercurl for diagnostics only where supported.

### 8.6 Design-token theme system

One TOML file per theme. Everything visual reads from it.

```toml
# themes/sumi.toml
name = "sumi"
dark = true

[color]
base = "#1F1F28"; mantle = "#1A1A22"; surface = "#2A2A37"; overlay = "#363646"
text = "#DCD7BA"; text_muted = "#8A8980"; accent = "#7E9CD8"
error = "#E46876"; warn = "#E6C384"; ok = "#98BB6C"

[syntax]           # roles, not tree-sitter names (max 4 hues + text/muted)
keyword = "#957FB8"; string = "#98BB6C"; callable = "#7FB4CA"; constant = "#D27E99"
comment = { color = "text_muted", italic = true }

[space]
pane_x = 1; popup_x = 2; gutter = 1

[border]
style = "none"        # none | hairline | round
focus = "accent"

[color.ansi256]       # hand-tuned fallback, used when truecolor isn't available
base = 234; mantle = 233; surface = 236; overlay = 238; text = 187; text_muted = 245; accent = 110
```

One loader (`theme.py`) compiles this into:

1. a **Textual `Theme`** (`primary=accent`, `background=base`, `surface=mantle`, `panel=surface`, `foreground=text`, …), so all widget CSS uses `$variables` and never hex;
2. a **`TextAreaTheme`** (syntax roles → tree-sitter capture names → Rich styles, plus cursor/selection/gutter);
3. a **Rich `Theme`** for output and tracebacks (`tb.frame.user`, `tb.frame.lib`, `tb.error`, `run.stderr`, …).

Spacing and border tokens become Textual CSS variables. Changing one TOML value restyles everything; snapshot tests catch regressions.

---

## 9. Performance budget

| Metric | Brief | Measured today (ref VM) | **Proposed budget** | How measured |
|---|---|---|---|---|
| Launch → first useful paint | < 150 ms | 262–321 ms (Textual + tree-sitter, stock) | **≤ 250 ms on ref VM; target ≤ 150 ms on a 2022+ laptop** (to verify in M0) | `phases.py` mark at first `call_after_refresh`, median of 10 |
| Idle RSS, UI process, 1k-line file | "low" | 37–58 MB | **≤ 60 MB** | psutil after 3 s idle |
| Idle RSS, total incl. completion worker | n/a | +73 MB (Jedi) / +83 MB (ty) | **≤ 160 MB** (PyCharm idles around 1.5 GB per user reports) | Same, sum of the process tree |
| Idle CPU | n/a | 0.7 % | **< 1 %** with blink off | psutil over 3 s |
| Keystroke → frame, ≤ 1k lines | imperceptible | 18–31 ms stock, 21 ms with viewport highlighting | **p50 ≤ 25 ms, p95 ≤ 40 ms** | `typelat.py` (pty) |
| Keystroke → frame, 5k lines | n/a | 158 ms stock / 50 ms spike | **p50 ≤ 60 ms** (big files are out of scope, but must stay usable) | Same |
| Completion visible after `.` (warm) | n/a | 3–54 ms (Jedi) | **p95 ≤ 100 ms**; never blocks typing | Instrumented timestamps |
| Run: key → process started | n/a | spawn 18–24 ms | **≤ 50 ms** incl. save | Instrumented |
| Lint after idle | n/a | 16–19 ms | **≤ 50 ms** off the main thread | Instrumented |

**Ways to get first paint down**, to be tried in M0 in this order:

1. Precompiled bytecode at install (`uv tool install --compile-bytecode`). Without it the first launch after install is much slower.
2. First paint with `language=None`, then set the tree-sitter language on the next tick. Plain text paints first, and highlighting appears within one frame.
3. Spawn the Jedi worker, ruff and venv detection **after** first paint.
4. Keep the import graph minimal: no `textual[syntax]`, no `platformdirs` at import time (resolve paths lazily), no Pygments until a traceback needs it.
5. Profile with `python -X importtime` in CI and fail the build if `import pytobs.app` exceeds budget.

If (1)–(5) still can't reach the budget on your machine, the fallback is to accept about 200 ms. The alternative, prompt_toolkit, saves about 80–100 ms but costs most of the visual design work.

---

## 10. Persistence and packaging

- **Config:** `$XDG_CONFIG_HOME/pytobs/config.toml` (macOS: `~/Library/Application Support/pytobs/`, Windows: `%APPDATA%\pytobs\`). Contains theme, keymap overrides, interpreter, `format_on_save`, `run.timeout_s`, `icons`.
- **State:** `$XDG_STATE_HOME/pytobs/session.json` holds open files, cursor/scroll per file, layout split, last interpreter. Written on quit and every 30 s, using atomic write (temp file + rename).
- **Scratch:** `pytobs` with no arguments reopens the last session, or a scratch file if there is none. Scratch files live in `$XDG_DATA_HOME/pytobs/scratch/scratch-YYYYMMDD-HHMM.py`, are autosaved 1 s after typing stops, and are listed in the file picker under "Scratch". "Save as" moves one into a real folder.
- **Unsaved buffers** are also snapshotted to state, so a crash or `kill` never loses work.
- **Packaging:** `pyproject.toml` with entry point `pytobs = pytobs.__main__:main`. Dependencies: `textual` (pinned minor), `tree-sitter-python`, `jedi`, `ruff`. Optional extra `pytobs[ty]`.
  - Install: `uv tool install pytobs` (`UV_COMPILE_BYTECODE=1` documented) or `pipx install pytobs`.
  - Launch: `pytobs [file.py]`.

---

## 11. Architecture

```
┌──────────────────────────── UI process (Textual, asyncio) ────────────────────────────┐
│                                                                                       │
│  PytobsApp ── Screen: Workspace                                                       │
│   │            ├─ EditorPane ── CodeEditor(TextArea)  ◀── ThemeTokens (theme.py)      │
│   │            │                 ├─ CompletionMenu + DocPanel (overlay layer)         │
│   │            │                 └─ SignatureHint                                     │
│   │            ├─ OutputPane ── RunHeader · Log view · StdinLine · TracebackView      │
│   │            └─ StatusBar  ── path · interpreter · ruff · Ln:Col · key hints        │
│   │                                                                                   │
│   │  Services (plain async classes, owned by the App, talk via Textual Messages)      │
│   ├─ Runner ──────────── asyncio subprocess ───────────▶ [ user python -u file.py ]   │
│   │     emits RunStarted / OutputLine / RunExited(code, duration)                     │
│   ├─ CompletionClient ── JSON lines over pipes ────────▶ [ completion worker:     ]   │
│   │     generation ids, cancel, client-side filter       [  Jedi(env=user venv)   ]   │
│   │                                                      [  or ty server (LSP)    ]   │
│   ├─ Linter ──────────── ruff subprocess (stdin) ──────▶ [ ruff check / format    ]   │
│   │     emits Diagnostics(list)                                                       │
│   ├─ EnvResolver ── finds interpreter (CLI → $VIRTUAL_ENV → .venv walk → PATH)        │
│   ├─ Session ── load/save state, scratch files, atomic writes                         │
│   └─ Config/Theme ── TOML → Textual Theme + TextAreaTheme + Rich Theme                │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

**Flow of one iteration:**

1. Ctrl+R → `Session.save()` → `Runner.start(interpreter, path)`.
2. `OutputLine` messages → `OutputPane` appends.
3. On exit, `RunExited` → `TracebackView` parses stderr; if the file has a user frame, the editor gutter marks the line.
4. Ctrl+E → `CodeEditor.move_cursor(line)`.

Completion and lint run concurrently and post results back as messages. Nothing blocks the event loop; every service call is either `await`ed I/O or another process.

**Module layout (planned):** `app.py`, `editor.py`, `output.py`, `statusbar.py`, `completion/{client.py,worker.py,menu.py}`, `runner.py`, `traceback.py`, `lint.py`, `env.py`, `session.py`, `theme.py`, `config.py`, `themes/*.toml`.

---

## 12. Milestones (v1)

Each milestone ends in something usable and a bench run against §9.

| # | Milestone | Scope | Exit criteria |
|---|---|---|---|
| **M0** | Skeleton + bench harness | uv project, `pytobs` entry point, empty two-pane layout, theme loader with Sumi tokens, bench scripts wired into `make bench` | First paint and idle RSS measured **on your machine**; budget confirmed or revised |
| **M1** | Editor | Open/save, `CodeEditor` (viewport highlighting, auto-indent, auto-close, smart backspace, comment toggle), status bar, clipboard fallback, file picker | Typing p95 ≤ 40 ms at 1k lines; snapshot tests for the look |
| **M2** | Run loop | Runner, streaming output, stdin line, stop, elapsed/exit, traceback render + Ctrl+E, run history, venv detection | Full write→run→fix loop in ≤ 2 chords; stop always works, including for child processes |
| **M3** | Completion | Worker process, menu, doc panel, signature hint, warm-up, generation/cancel | Typing latency unchanged with completion on; warm completion p95 ≤ 100 ms |
| **M4** | Lint + format | Ruff over stdin, gutter dots, status message, format command/on-save | No visible lag; no inline clutter by default |
| **M5** | Polish + ship | Session restore, scratch files, config, directions B and C, 256-colour variants, Dawn light theme, packaging, README with screenshots | `uv tool install` → `pytobs` works on Linux and macOS (and Windows if in scope); all §9 budgets green |

Rough size: M0 ≈ 1–2 days, M1 ≈ 1 week, M2 ≈ 1 week, M3 ≈ 1 week, M4 ≈ 2–3 days, M5 ≈ 1 week.

---

## 13. Risks and open questions

### Open questions for you

1. **Which OS(es)?** The brief says to confirm first. The plan assumes macOS + Linux as primary. Windows affects stop/signals, pty mode and clipboard; it's supported by Textual in Windows Terminal but adds testing cost.
2. **Startup budget:** is "≤ 150 ms on your laptop, ≤ 250 ms on the slow reference VM" acceptable, or is 150 ms a hard requirement? A hard requirement points to prompt_toolkit and a much plainer look.
3. **Which visual direction:** A (recommended), B or C? Or A's layout with B's palette, since tokens and border style are independent.
4. **Light theme in v1?** (Rosé Pine Dawn is cheap to add.)
5. **Default format-on-save:** off (learners see their own code) or on?
6. **Completion default:** Jedi (stable) now, or ty (faster, beta) now with Jedi as fallback?
7. **Name:** keep `pytobs`?

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| First paint misses 150 ms | High | Medium | §9 mitigations; measure in M0 before building further |
| Override of private `TextArea._build_highlight_map` breaks on a Textual upgrade | Medium | Medium | Pin Textual minor version; snapshot and latency tests; upstream PR |
| Cold Jedi on heavy libraries (pandas, numpy: seconds) | High | Low | Background warm-up of the file's imports; menu shows "indexing…" instead of blocking |
| Terminal key limits (Ctrl+Enter, Ctrl+Shift+X, Ctrl+/ variants) | High | Low | Defaults avoid them; keymap configurable; kitty keyboard protocol where available |
| OSC 52 clipboard missing (Terminal.app, GNOME Terminal) | Certain on those | Medium | Fallback to `pbcopy` / `wl-copy` / `xclip` |
| 256-colour terminals (pre-Tahoe Terminal.app, some SSH) | Medium | Medium | Hand-tuned `ansi256` per theme |
| Programs that need a TTY (progress bars, `getpass`, curses) under pipes | Medium | Low | Document it; POSIX pty mode post-v1 |
| ty instability while still 0.x | Medium | Low | Optional only, behind the backend interface |
| Numbers measured on a cloud VM, not your machine | Certain | Low | M0 re-measures locally with the committed bench scripts |

---

## 14. Measurement setup and sources

**Reference VM:** Linux 6.18, Intel Xeon @ 2.1 GHz, 4 vCPU, 16 GB RAM, Python 3.13 (system), bytecode precompiled.
Library versions: Textual 8.2.8, Rich 15.0.0, prompt_toolkit 3.0.53, Jedi 0.20.0, python-lsp-server 1.15.0, pyright 1.1.414, ty 0.0.84, ruff 0.16.10, tree-sitter 0.26.0, tree-sitter-python 0.25.0, Pygments 2.21.0.

Expect a recent laptop to be roughly 1.5–2× faster on startup (`python -c pass` takes 19 ms here). Re-measure in M0.

Scripts: `research/bench/` (README explains each). Test files: CPython stdlib `json/__init__.py` (365 lines), `argparse.py`, `typing.py`, `_pydecimal.py` and its first 300/1000/2500 lines.

**Sources**

- Textual TextArea docs (tree-sitter highlighting, `TextAreaTheme`): https://textual.textualize.io/widgets/text_area
- "Things I learned while building Textual's TextArea" (incremental parsing, query-construction cost): https://textual.textualize.io/blog/2023/09/18/things-i-learned-while-building-textuals-textarea
- Textual lazy mounting (`textual.lazy`): https://textual.textualize.io/api/lazy
- Copy/paste in Textual, OSC 52 support table: https://darren.codes/posts/textual-copy-paste
- Terminal colour detection (`COLORTERM`, Terminal.app 256-colour): https://marvinh.dev/blog/terminal-colors
- Terminal.app 24-bit colour in macOS 26: https://www.macrumors.com/2025/06/16/apples-terminal-app-macos-tahoe
- prompt_toolkit vs Textual editing maturity (practitioner view): https://news.ycombinator.com/item?id=41510943
- ty language server features/status: https://pydevtools.com/handbook/explanation/ty-complete-guide, https://github.com/zed-industries/zed/discussions/45239
- Type checker speed/memory comparison (pyright vs ty vs pyrefly): https://pyrefly.org/blog/speed-and-memory-comparison
- Posting (Textual app design reference): https://github.com/darrenburns/posting
- Lip Gloss (Charm styling model): https://github.com/charmbracelet/lipgloss
- Palettes: Kanagawa https://github.com/rebelot/kanagawa.nvim, Everforest https://github.com/sainnhe/everforest/blob/master/palette.md, Rosé Pine https://rosepinetheme.com/palette/ingredients/, Catppuccin, Tokyo Night (published hex values)
- PyCharm memory settings: https://www.jetbrains.com/help/pycharm/increasing-memory-heap.html; idle usage report (anecdotal, ~1.5 GB): https://www.reddit.com/r/pycharm/comments/r69es2/how_much_memory_does_your_pycharm_use
- Synchronized output (DEC 2026) background: https://github.com/wavetermdev/waveterm/issues/2787
