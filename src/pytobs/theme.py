"""Design tokens for the Sumi theme and their mapping onto Textual and Rich."""

from __future__ import annotations

from rich.style import Style
from textual.theme import Theme
from textual.widgets.text_area import TextAreaTheme


class C:
    """Colour tokens. Everything visual reads from here."""

    base = "#1F1F28"  # editor background
    mantle = "#1A1A22"  # output pane, status bar
    surface = "#2A2A37"  # popups
    overlay = "#363646"  # selection, active row
    cursor_line = "#24242F"
    text = "#DCD7BA"
    muted = "#8A8980"
    faint = "#54546D"
    accent = "#7E9CD8"
    ok = "#98BB6C"
    warn = "#E6C384"
    error = "#E46876"
    # syntax: four hues, everything else is plain text
    keyword = "#957FB8"
    string = "#98BB6C"
    callable = "#7FB4CA"
    constant = "#D27E99"


# Glyphs present in Geist Mono (bundled) and Cascadia Mono (Windows default).
class G:
    run = "▶"
    dot = "●"
    sep = "·"
    cross = "×"
    spinner = "▖▘▝▗"
    chevron = "›"


APP_THEME = Theme(
    name="sumi",
    primary=C.accent,
    secondary=C.callable,
    accent=C.accent,
    warning=C.warn,
    error=C.error,
    success=C.ok,
    foreground=C.text,
    background=C.base,
    surface=C.mantle,
    panel=C.surface,
    dark=True,
    variables={
        "block-cursor-background": C.overlay,
        "block-cursor-foreground": C.text,
        "block-cursor-text-style": "bold",
        "block-hover-background": C.surface,
        "input-cursor-background": C.accent,
        "input-cursor-foreground": C.base,
        "input-selection-background": C.overlay,
        "scrollbar": C.surface,
        "scrollbar-hover": C.overlay,
        "scrollbar-active": C.accent,
        "scrollbar-background": C.base,
        "scrollbar-background-hover": C.base,
        "scrollbar-background-active": C.base,
        "scrollbar-corner-color": C.base,
        "footer-key-foreground": C.text,
        "footer-description-foreground": C.muted,
        "border": C.overlay,
        "border-blurred": C.surface,
    },
)


def _style(color: str, **kwargs: bool) -> Style:
    return Style(color=color, **kwargs)


_SYNTAX: dict[str, Style] = {}
for _name in (
    "keyword",
    "keyword.function",
    "keyword.return",
    "keyword.operator",
    "include",
    "conditional",
    "repeat",
    "exception",
    "operator.keyword",
):
    _SYNTAX[_name] = _style(C.keyword)
for _name in ("string", "string.documentation", "escape", "string.special"):
    _SYNTAX[_name] = _style(C.string)
for _name in (
    "function",
    "function.call",
    "method",
    "method.call",
    "function.builtin",
    "type",
    "type.builtin",
    "class",
    "constructor",
    "decorator",
):
    _SYNTAX[_name] = _style(C.callable)
for _name in ("number", "float", "boolean", "constant.builtin", "constant"):
    _SYNTAX[_name] = _style(C.constant)
_SYNTAX["comment"] = Style(color=C.muted, italic=True)

EDITOR_THEME = TextAreaTheme(
    name="sumi",
    base_style=Style(color=C.text, bgcolor=C.base),
    gutter_style=Style(color=C.faint, bgcolor=C.base),
    cursor_style=Style(color=C.base, bgcolor=C.accent),
    cursor_line_style=Style(bgcolor=C.cursor_line),
    cursor_line_gutter_style=Style(color=C.muted, bgcolor=C.cursor_line),
    bracket_matching_style=Style(bgcolor=C.overlay, bold=True),
    selection_style=Style(bgcolor=C.overlay),
    syntax_styles=_SYNTAX,
)
