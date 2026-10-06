"""One-time Windows integration, run with `pytobs --setup`.

Everything is per-user (no admin rights) and reversible with `pytobs --uninstall`:
  1. installs the Geist Mono font for the current user
  2. adds a "pytobs" profile and the Sumi colour scheme to Windows Terminal (a JSON fragment)
  3. adds "Edit with pytobs" to the right-click menu for .py files
  4. adds a pytobs shortcut to the Start menu
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

FONT_FILE = "GeistMono[wght].ttf"
FONT_NAME = "Geist Mono"
FONT_REG_NAME = "Geist Mono (TrueType)"
PROFILE_GUID = "{5b0f6a4e-3c1d-4f8e-9a2b-7d1e0c6f9a31}"
SCHEME = "pytobs Sumi"
MENU_KEY = r"Software\Classes\SystemFileAssociations\.py\shell\pytobs"


def _local() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def _fragment_path() -> Path:
    return _local() / "Microsoft" / "Windows Terminal" / "Fragments" / "pytobs" / "pytobs.json"


def _font_dest() -> Path:
    return _local() / "Microsoft" / "Windows" / "Fonts" / FONT_FILE


def _start_menu_link() -> Path:
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "pytobs.lnk"


def _exe() -> str:
    """Quoted command for the installed launcher (pytobs.exe from uv/pipx), or python -m pytobs."""
    found = shutil.which("pytobs")
    if found:
        return f'"{found}"'
    return f'"{sys.executable}" -m pytobs'


def _wt() -> str | None:
    return shutil.which("wt") or shutil.which("wt.exe")


def _scheme() -> dict:
    return {
        "name": SCHEME,
        "background": "#1F1F28",
        "foreground": "#DCD7BA",
        "cursorColor": "#7E9CD8",
        "selectionBackground": "#363646",
        "black": "#16161D",
        "red": "#E46876",
        "green": "#98BB6C",
        "yellow": "#E6C384",
        "blue": "#7E9CD8",
        "purple": "#957FB8",
        "cyan": "#7FB4CA",
        "white": "#C8C093",
        "brightBlack": "#727169",
        "brightRed": "#FF5D62",
        "brightGreen": "#98BB6C",
        "brightYellow": "#E6C384",
        "brightBlue": "#7FB4CA",
        "brightPurple": "#938AA9",
        "brightCyan": "#7AA89F",
        "brightWhite": "#DCD7BA",
    }


def _profile(font_ok: bool) -> dict:
    return {
        "guid": PROFILE_GUID,
        "name": "pytobs",
        "commandline": _exe(),
        "startingDirectory": "%USERPROFILE%",
        "colorScheme": SCHEME,
        "font": {
            "face": f"{FONT_NAME}, Cascadia Mono" if font_ok else "Cascadia Mono",
            "size": 11,
            "cellHeight": "1.3",
        },
        "padding": "18, 14, 18, 10",
        "cursorShape": "bar",
        "antialiasingMode": "grayscale",
        "scrollbarState": "hidden",
        "suppressApplicationTitle": True,
        "tabTitle": "pytobs",
        "tabColor": "#1F1F28",
        "hidden": False,
    }


def _install_font() -> bool:
    import winreg  # type: ignore[import-not-found]

    src = Path(__file__).parent / "assets" / "fonts" / FONT_FILE
    dest = _font_dest()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copyfile(src, dest)
    key = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
        winreg.SetValueEx(k, FONT_REG_NAME, 0, winreg.REG_SZ, str(dest))
    try:  # make the font available to running apps without a sign-out
        import ctypes

        ctypes.windll.gdi32.AddFontResourceW(str(dest))  # type: ignore[attr-defined]
        HWND_BROADCAST, WM_FONTCHANGE = 0xFFFF, 0x001D
        ctypes.windll.user32.SendMessageTimeoutW(  # type: ignore[attr-defined]
            HWND_BROADCAST, WM_FONTCHANGE, 0, 0, 0x0002, 1000, None
        )
    except Exception:
        pass
    return True


def _install_menu() -> None:
    import winreg  # type: ignore[import-not-found]

    wt = _wt()
    exe_cmd = _exe()
    command = f'"{wt}" -p "pytobs" {exe_cmd} "%1"' if wt else f'{exe_cmd} "%1"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MENU_KEY) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Edit with pytobs")
        icon = shutil.which("pytobs")
        if icon:
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, MENU_KEY + r"\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, command)


def _install_shortcut() -> None:
    wt = _wt()
    link = _start_menu_link()
    link.parent.mkdir(parents=True, exist_ok=True)
    target, arguments = (wt, '-p "pytobs"') if wt else (shutil.which("pytobs") or sys.executable, "")
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:PYTOBS_LNK);"
        "$s.TargetPath=$env:PYTOBS_TARGET;$s.Arguments=$env:PYTOBS_ARGS;"
        "$s.Description='pytobs - write, run, fix';$s.Save()"
    )
    env = dict(os.environ, PYTOBS_LNK=str(link), PYTOBS_TARGET=target or "", PYTOBS_ARGS=arguments)
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        env=env,
        capture_output=True,
        check=False,
    )


def setup() -> int:
    if sys.platform != "win32":
        print("pytobs --setup is for Windows. On other systems just run: pytobs")
        return 0
    steps = []
    try:
        font_ok = _install_font()
        steps.append(f"font        {FONT_NAME} installed for your user")
    except Exception as exc:
        font_ok = False
        steps.append(f"font        skipped ({exc}); using Cascadia Mono")
    fragment = _fragment_path()
    fragment.parent.mkdir(parents=True, exist_ok=True)
    fragment.write_text(
        json.dumps({"profiles": [_profile(font_ok)], "schemes": [_scheme()]}, indent=2),
        encoding="utf-8",
    )
    steps.append("terminal    'pytobs' profile added to Windows Terminal")
    try:
        _install_menu()
        steps.append("explorer    right-click a .py file > 'Edit with pytobs'")
    except Exception as exc:
        steps.append(f"explorer    skipped ({exc})")
    try:
        _install_shortcut()
        steps.append("start menu  'pytobs' shortcut added")
    except Exception as exc:
        steps.append(f"start menu  skipped ({exc})")
    print("\n  pytobs is set up\n")
    for s in steps:
        print("  " + s)
    print("\n  Restart Windows Terminal, then pick 'pytobs' from the tab menu,")
    print("  or run `pytobs file.py` in any terminal.\n")
    if not _wt():
        print("  Windows Terminal was not found. Install it from the Microsoft Store for the full look.\n")
    return 0


def uninstall() -> int:
    if sys.platform != "win32":
        return 0
    import winreg  # type: ignore[import-not-found]

    fragment = _fragment_path()
    if fragment.exists():
        fragment.unlink()
        try:
            fragment.parent.rmdir()
        except OSError:
            pass
    for key in (MENU_KEY + r"\command", MENU_KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            pass
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows NT\CurrentVersion\Fonts",
            0,
            winreg.KEY_SET_VALUE,
        ) as k:
            winreg.DeleteValue(k, FONT_REG_NAME)
    except OSError:
        pass
    link = _start_menu_link()
    if link.exists():
        link.unlink()
    print("pytobs integration removed. The font file stays until you sign out;")
    print(f"delete it from {_font_dest().parent} if you like. Remove the app with: uv tool uninstall pytobs")
    return 0
