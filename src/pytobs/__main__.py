"""Command line entry point: `pytobs [file.py]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="pytobs",
        description="A quiet, fast Python editor for the terminal. Write, Ctrl+R to run, fix.",
    )
    parser.add_argument("file", nargs="?", help="file to open (created if missing)")
    parser.add_argument("--python", help="interpreter that runs your code (default: nearest .venv)")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Windows: install the font, Windows Terminal profile and Explorer menu",
    )
    parser.add_argument("--uninstall", action="store_true", help="Windows: remove what --setup added")
    parser.add_argument("--version", action="version", version=f"pytobs {__version__}")
    args = parser.parse_args(argv)

    if args.setup or args.uninstall:
        from . import winsetup

        sys.exit(winsetup.uninstall() if args.uninstall else winsetup.setup())

    from .app import Pytobs

    path = Path(args.file) if args.file else None
    if path is not None and path.is_dir():
        import os

        os.chdir(path)
        path = None
    Pytobs(path=path, python=args.python).run()


if __name__ == "__main__":
    main()
