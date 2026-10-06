import json

from pytobs import winsetup


def test_fragment_is_valid_terminal_json() -> None:
    fragment = {"profiles": [winsetup._profile(True)], "schemes": [winsetup._scheme()]}
    data = json.loads(json.dumps(fragment))
    profile = data["profiles"][0]
    assert profile["colorScheme"] == data["schemes"][0]["name"] == winsetup.SCHEME
    assert profile["font"]["face"].startswith("Geist Mono")
    assert profile["commandline"].startswith('"')  # quoted: user paths can contain spaces
    scheme = data["schemes"][0]
    for key in ("background", "foreground", "black", "brightWhite", "cursorColor"):
        assert scheme[key].startswith("#") and len(scheme[key]) == 7


def test_font_is_bundled() -> None:
    from pathlib import Path

    font = Path(winsetup.__file__).parent / "assets" / "fonts" / winsetup.FONT_FILE
    assert font.exists() and font.stat().st_size > 100_000


def test_setup_is_a_no_op_off_windows(capsys) -> None:
    import sys

    if sys.platform != "win32":
        assert winsetup.setup() == 0
        assert "for Windows" in capsys.readouterr().out
