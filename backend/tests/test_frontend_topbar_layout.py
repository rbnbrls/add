"""Regressietests voor de top bar (hoofdmenu) van de frontend.

Het hoofdmenu moet in de top bar gecentreerd staan (issue #8). De top bar
wordt gestyled via de CSS-bestanden die `frontend/app/layout.tsx` in volgorde
importeert; latere imports overschrijven eerdere. Deze tests lezen diezelfde
cascade uit en bewaken twee dingen:

1. de effectieve layout centreert het menu (.global-flow) in de top bar;
2. de top-bar layout staat in één stylesheet, zodat twee bestanden elkaar niet
   stil kunnen overrulen (dat was de oorzaak van het links uitgelijnde menu).
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
APP = FRONTEND / "app"


def layout_stylesheets() -> list[Path]:
    """CSS-bestanden in de volgorde waarin layout.tsx ze importeert."""
    text = (APP / "layout.tsx").read_text(encoding="utf-8")
    return [APP / name for name in re.findall(r'import\s+"\./([^"]+\.css)"', text)]


def _split_declarations(block: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for chunk in block.split(";"):
        if ":" not in chunk:
            continue
        prop, value = chunk.split(":", 1)
        declarations[prop.strip().lower()] = value.strip().lower()
    return declarations


def parse_css(text: str) -> list[tuple[str | None, str, dict[str, str]]]:
    """Parseer CSS naar (media-conditie, selector, declaraties).

    Media-condities worden doorgegeven aan de regels binnen de at-rule; de
    selector is telkens één losse selector uit de selectorlijst.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    rules: list[tuple[str | None, str, dict[str, str]]] = []
    index = 0
    while index < len(text):
        open_brace = text.find("{", index)
        if open_brace == -1:
            break
        head = text[index:open_brace].strip()
        depth = 1
        cursor = open_brace + 1
        while cursor < len(text) and depth:
            if text[cursor] == "{":
                depth += 1
            elif text[cursor] == "}":
                depth -= 1
            cursor += 1
        body = text[open_brace + 1 : cursor - 1]
        if head.startswith("@"):
            condition = head if head.lower().startswith("@media") else head
            for media, selector, declarations in parse_css(body):
                rules.append((condition if media is None else f"{condition} and {media}", selector, declarations))
        else:
            declarations = _split_declarations(body)
            for selector in head.split(","):
                rules.append((None, selector.strip(), declarations))
        index = cursor
    return rules


def _max_width(condition: str | None) -> int | None:
    if not condition:
        return None
    match = re.search(r"max-width:\s*(\d+)px", condition)
    return int(match.group(1)) if match else None


def resolve(selector: str, viewport: int) -> dict[str, str]:
    """Effectieve declaraties voor een selector in de cascade van layout.tsx."""
    resolved: dict[str, str] = {}
    for stylesheet in layout_stylesheets():
        for condition, rule_selector, declarations in parse_css(stylesheet.read_text(encoding="utf-8")):
            if rule_selector != selector:
                continue
            limit = _max_width(condition)
            if condition is not None and (limit is None or limit < viewport):
                continue
            resolved.update(declarations)
    return resolved


def stylesheets_declaring(selector: str, prop: str) -> list[str]:
    """Stylesheets die `prop` zetten voor `selector` op het hoogste niveau."""
    declaring = []
    for stylesheet in layout_stylesheets():
        for condition, rule_selector, declarations in parse_css(stylesheet.read_text(encoding="utf-8")):
            if condition is None and rule_selector == selector and prop in declarations:
                declaring.append(stylesheet.name)
    return declaring


def flex_grow(declarations: dict[str, str]) -> float:
    if "flex-grow" in declarations:
        return float(declarations["flex-grow"])
    shorthand = declarations.get("flex")
    if shorthand:
        parts = shorthand.split()
        if parts and parts[0] not in {"none", "auto", "initial"}:
            try:
                return float(parts[0])
            except ValueError:
                return 0.0
    return 0.0


def test_layout_imports_the_stylesheets_we_inspect():
    names = [path.name for path in layout_stylesheets()]
    assert "style.css" in names and "accessibility.css" in names
    assert names.index("style.css") < names.index("accessibility.css")


def test_top_bar_layout_is_defined_in_a_single_stylesheet():
    assert stylesheets_declaring(".global-nav", "display") == ["accessibility.css"]


def test_menu_is_centered_in_the_top_bar_on_desktop():
    nav = resolve(".global-nav", 1280)
    assert nav.get("display") == "grid"
    tracks = nav["grid-template-columns"].split()
    assert len(tracks) == 3, f"verwacht 3 kolommen (logo | menu | tools), kreeg {tracks}"
    assert tracks[0] == tracks[2], f"zijkolommen moeten even breed zijn, kreeg {tracks}"
    assert tracks[1] in {"auto", "min-content", "max-content"}, tracks

    flow = resolve(".global-flow", 1280)
    assert flow.get("justify-content") == "center"
    assert flex_grow(flow) == 0.0, "flex-grow op .global-flow duwt het menu naar links"

    tools = resolve(".global-nav-tools", 1280)
    assert tools.get("justify-self") == "end"


def test_menu_stays_centered_on_narrow_screens():
    nav = resolve(".global-nav", 600)
    assert nav.get("display") == "flex"
    assert nav.get("flex-wrap") == "wrap"

    flow = resolve(".global-flow", 600)
    assert flow.get("justify-content") == "center"
    assert flex_grow(flow) == 0.0
    assert flow.get("flex-basis") == "100%"


def test_menu_is_not_left_aligned_on_small_screens():
    flow = resolve(".global-flow", 480)
    assert flow.get("justify-content") != "flex-start"
