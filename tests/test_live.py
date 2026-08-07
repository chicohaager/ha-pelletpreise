"""Prüft gegen die echte Website statt gegen die Fixtures.

Die Fixture-Tests belegen, dass der Parser eine Seite von damals richtig liest.
Sie können nicht auffallen, wenn heizpellets24.de sein Format ändert — dann
wären sie weiterhin grün und die Sensoren zu Hause trotzdem leer. Dieser Test
schließt genau diese Lücke.

Er läuft nicht bei jedem Testlauf mit (er braucht Netz und belastet eine fremde
Seite), sondern nur mit::

    python -m pytest tests/test_live.py -m live
"""

from __future__ import annotations

import urllib.request

import pytest

from pelletpreise.const import BUNDESLAENDER, REGION_DEUTSCHLAND
from pelletpreise.parser import (
    PLAUSIBEL_MAX,
    PLAUSIBEL_MIN,
    parse_bundesland,
    parse_deutschland,
)

BASIS_URL = "https://www.heizpellets24.de/pelletpreise"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 (+home-assistant-pelletpreise)"
)

pytestmark = pytest.mark.live


def hole(pfad: str) -> str:
    anfrage = urllib.request.Request(  # noqa: S310 - feste https-Adresse
        pfad,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"},
    )
    with urllib.request.urlopen(anfrage, timeout=30) as antwort:  # noqa: S310
        return antwort.read().decode("utf-8", errors="replace")


def test_deutschland_seite_ist_noch_lesbar():
    preise = parse_deutschland(hole(BASIS_URL))
    assert PLAUSIBEL_MIN < preise.lose.euro_pro_tonne < PLAUSIBEL_MAX


@pytest.mark.parametrize("slug", sorted(BUNDESLAENDER))
def test_jede_bundeslandseite_ist_noch_lesbar(slug):
    """Alle 16 Regionen, nicht nur eine Stichprobe.

    Ein Slug, der ins Leere zeigt, liefert stillschweigend die
    Deutschland-Seite — dort fehlt `localPrices`, der Parser meldet das, und
    genau dieser Fall wird hier sichtbar.
    """
    preise = parse_bundesland(hole(f"{BASIS_URL}/{slug}"), slug)
    assert PLAUSIBEL_MIN < preise.lose.euro_pro_tonne < PLAUSIBEL_MAX
    if preise.sackware is not None:
        assert PLAUSIBEL_MIN < preise.sackware.euro_pro_tonne < PLAUSIBEL_MAX


def test_regionen_liefern_unterschiedliche_preise():
    """Gegenprobe gegen einen Parser, der überall dasselbe liest."""
    bund = parse_deutschland(hole(BASIS_URL)).lose.euro_pro_tonne
    bayern = parse_bundesland(hole(f"{BASIS_URL}/bayern"), "bayern").lose.euro_pro_tonne
    nrw = parse_bundesland(
        hole(f"{BASIS_URL}/nordrhein-westfalen"), "nordrhein-westfalen"
    ).lose.euro_pro_tonne
    assert len({bund, bayern, nrw}) == 3, (
        f"Bund={bund}, Bayern={bayern}, NRW={nrw} — mindestens zwei Regionen "
        "liefern denselben Wert; vermutlich wird die falsche Seite gelesen"
    )
    assert REGION_DEUTSCHLAND == "deutschland"
