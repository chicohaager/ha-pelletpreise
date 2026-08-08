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
from pelletpreise.vergleich import bilde_vergleich

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


def test_die_bundeslandseiten_fuehren_keine_langfristwerte():
    """Belegt, warum es die Sensoren „(beobachtet)" überhaupt gibt.

    Die Quelle nennt Tief- und Höchstwerte nur auf der Deutschland-Seite. Die
    Deutschland-Seite ist hier die **Positivkontrolle**: fände die Suche dort
    ebenfalls nichts, wäre der Befund kein Befund, sondern ein kaputter Test.

    Schlägt dieser Test eines Tages fehl, weil `low3Y` auch auf einer
    Bundesland-Seite auftaucht, ist das eine gute Nachricht — dann kann die
    Integration echte Langfristwerte je Bundesland liefern statt eigener
    Aufzeichnungen.
    """
    bund = hole(BASIS_URL)
    assert "low3Y" in bund and "high3Y" in bund, (
        "Auf der Deutschland-Seite fehlen low3Y/high3Y — die Gegenprobe "
        "greift nicht, der Befund unten wäre wertlos."
    )
    bayern = hole(f"{BASIS_URL}/bayern")
    assert "low3Y" not in bayern
    assert "high3Y" not in bayern


def test_bundeslandvergleich_gegen_die_echte_seite():
    """Alle 16 Seiten holen und daraus günstigstes/teuerstes Land bestimmen.

    Prüft genau den Weg, den die Integration bei eingeschaltetem Vergleich
    geht — nur ohne aiohttp. Die Zusicherungen sind bewusst grob: die Preise
    ändern sich täglich, festnageln lässt sich die **Form** der Auskunft.
    """
    preise = {}
    for slug in sorted(BUNDESLAENDER):
        regional = parse_bundesland(hole(f"{BASIS_URL}/{slug}"), slug)
        preise[slug] = regional.lose.euro_pro_tonne

    vergleich = bilde_vergleich(preise)
    assert vergleich is not None
    assert len(vergleich.preise) == 16
    assert vergleich.guenstigste.euro_pro_tonne == min(preise.values())
    assert vergleich.teuerste.euro_pro_tonne == max(preise.values())
    assert vergleich.guenstigste.euro_pro_tonne < vergleich.teuerste.euro_pro_tonne, (
        "Alle 16 Bundesländer zum selben Preis — vermutlich wird 16-mal "
        "dieselbe Seite gelesen."
    )
    print(
        f"\nGünstigstes: {vergleich.guenstigste.name} "
        f"{vergleich.guenstigste.euro_pro_tonne} €/t · "
        f"Teuerstes: {vergleich.teuerste.name} "
        f"{vergleich.teuerste.euro_pro_tonne} €/t · "
        f"Spanne {vergleich.spanne_euro} €/t"
    )


def test_bundesdurchschnitt_wird_je_plz_gebildet():
    """Deckt den Hinweis, der an den Vergleichssensoren steht.

    Der Sensor sagt in seinem Attribut ``hinweis``, der Bundesdurchschnitt
    entstehe je Postleitzahl und nicht aus den 16 Landeswerten. Beleg ist das
    Kleingedruckte der Quelle selbst — nicht der Zahlenabstand: am 08.08.2026
    lagen Bundesdurchschnitt (406,51) und Mittel der 16 Länder (406,16) nur
    0,35 € auseinander. Wer daraus eine Aussage bauen wollte, hätte ein
    Ersatzsignal: nah beieinander heißt weder „dasselbe" noch „etwas anderes".

    Die Zahlen stehen trotzdem in der Ausgabe (``-s``), weil ein wachsender
    Abstand ein guter Anlass wäre, hier noch einmal hinzusehen.
    """
    seite = hole(BASIS_URL)
    assert "auf Basis des günstigsten Händlerangebots je PLZ" in seite, (
        "Das Kleingedruckte der Deutschland-Seite nennt die PLZ-Basis nicht "
        "mehr — der Hinweis am Sensor ist dann nicht mehr belegt."
    )

    bund = parse_deutschland(seite).lose.euro_pro_tonne
    landeswerte = [
        parse_bundesland(hole(f"{BASIS_URL}/{slug}"), slug).lose.euro_pro_tonne
        for slug in sorted(BUNDESLAENDER)
    ]
    mittel = sum(landeswerte) / len(landeswerte)
    print(
        f"\nBundesdurchschnitt {bund} €/t · Mittel der 16 Länder "
        f"{mittel:.2f} €/t · Abstand {abs(bund - mittel):.2f} €/t"
    )


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
