# Benchmark scripts

Throwaway measurement scripts behind the numbers in `docs/PROPOSAL.md`. They are research tooling, not product code.

Setup (any machine):

```sh
uv venv bench && . bench/bin/activate
uv pip install textual prompt_toolkit rich jedi python-lsp-server pygments \
  tree-sitter tree-sitter-python ruff pyright ty psutil
python -m compileall -q bench/lib   # match an installed tool: bytecode precompiled
```

| Script | Measures |
|---|---|
| `runpty.py CMD...` | launch → first paint → exit under a 120×40 pty, median of 7, plus max RSS (`tx_app.py`, `ptk_app.py`, `rich_app.py`) |
| `phases.py python tx_phases.py {static,plain,ts}` | Textual startup broken into import / compose / mount / first paint |
| `F=file.py python typelat.py python tx_type.py label` | keystroke → terminal output latency under a pty (60 keys; also `ptk_type.py`, `tx_type2.py`, `tx_type_vp.py`) |
| `jedi_bench.py` | Jedi cold/warm completion, signature and docstring latency, RSS |
| `lsp_bench.py pylsp` / `pyright-langserver --stdio` / `ty server` | LSP init and completion latency, server RSS |
| `hl_bench.py FILE...` | Pygments vs tree-sitter (full parse, incremental edit, full and viewport query) |
