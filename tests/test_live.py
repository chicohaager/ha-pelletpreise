"""Prüft gegen die echten Websites statt gegen die Fixtures.

Die Fixture-Tests belegen, dass der Parser eine Seite von damals richtig liest.
Sie können nicht auffallen, wenn heizpellets24 sein Format ändert — dann wären
sie weiterhin grün und die Sensoren zu Hause trotzdem leer. Dieser Test
schließt genau diese Lücke, und zwar für alle drei Landesdomains.

Er läuft nicht bei jedem Testlauf mit (er braucht Netz und belastet fremde
Seiten), sondern nur mit::

    python -m pytest tests/test_live.py -m live
"""

from __future__ import annotations

import urllib.request

import pytest

from pelletpreise.const import (
    BUNDESLAENDER_AT,
    BUNDESLAENDER_DE,
    LAENDER,
    REGION_DEUTSCHLAND,
    REGION_OESTERREICH,
    REGION_SCHWEIZ,
)
from pelletpreise.parser import (
    PLAUSIBEL_MAX,
    PLAUSIBEL_MIN,
    KeinAngebot,
    parse_bundesland,
    parse_landesseite,
)
from pelletpreise.vergleich import bilde_vergleich

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 (+home-assistant-pelletpreise)"
)

# Die Kantonsslugs stehen **nur hier** und nicht in const.py: die Integration
# bietet sie nicht an (Begründung dort), dieser Test misst aber weiter nach, ob
# der Grund noch gilt. Abgelesen am 09.08.2026 aus `countryStates` der Seite
# heizpellets24.ch/pelletpreise.
KANTONE_CH = (
    "aargau", "appenzell-innerrhoden", "appenzell-ausserrhoden", "bern",
    "basel-land", "basel-stadt", "freiburg", "genf", "glarus", "graubuenden",
    "jura", "luzern", "neuenburg", "nidwalden", "obwalden", "st-gallen",
    "schaffhausen", "solothurn", "schwyz", "thurgau", "tessin", "uri",
    "waadt", "wallis", "zug", "zuerich",
)

DE = LAENDER["de"]
AT = LAENDER["at"]
CH = LAENDER["ch"]

pytestmark = pytest.mark.live


def hole(pfad: str) -> str:
    anfrage = urllib.request.Request(  # noqa: S310 - feste https-Adresse
        pfad,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"},
    )
    with urllib.request.urlopen(anfrage, timeout=30) as antwort:  # noqa: S310
        return antwort.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Ist die Seite noch lesbar?
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("land", [DE, AT, CH], ids=lambda l: l.code)
def test_landesseite_ist_noch_lesbar(land):
    preise = parse_landesseite(hole(land.basis_url), land.name)
    assert PLAUSIBEL_MIN < preise.lose.preis_pro_tonne < PLAUSIBEL_MAX


@pytest.mark.parametrize("land", [DE, AT, CH], ids=lambda l: l.code)
def test_die_gelesene_waehrung_ist_die_erwartete(land):
    """Der Zahlenwert allein verrät die Währung nicht.

    522 sieht als Euro genauso plausibel aus wie als Franken. Ändert die
    Quelle hier etwas, muss es hier auffallen und nicht im Dashboard.
    """
    preise = parse_landesseite(hole(land.basis_url), land.name)
    assert preise.lose.waehrung == land.waehrung


@pytest.mark.parametrize(
    ("land", "slug"),
    [(DE, s) for s in sorted(BUNDESLAENDER_DE)]
    + [(AT, s) for s in sorted(BUNDESLAENDER_AT)],
    ids=lambda w: w if isinstance(w, str) else w.code,
)
def test_jede_bundeslandseite_ist_noch_lesbar(land, slug):
    """Alle Regionen, nicht nur eine Stichprobe.

    Ein Slug, der ins Leere zeigt, liefert stillschweigend die Landesseite —
    dort fehlt `localPrices`, der Parser meldet das, und genau dieser Fall
    wird hier sichtbar.

    `KeinAngebot` ist ausdrücklich zulässig: dass eine Region gerade keinen
    Preis führt, ist eine Auskunft der Quelle (Vorarlberg am 09.08.2026) und
    kein kaputtes Seitenformat.
    """
    try:
        preise = parse_bundesland(hole(f"{land.basis_url}/{slug}"), slug)
    except KeinAngebot:
        pytest.skip(f"{slug}: die Quelle führt derzeit keinen Preis für lose Ware")
    assert PLAUSIBEL_MIN < preise.lose.preis_pro_tonne < PLAUSIBEL_MAX
    assert preise.lose.waehrung == land.waehrung
    if preise.sackware is not None:
        assert PLAUSIBEL_MIN < preise.sackware.preis_pro_tonne < PLAUSIBEL_MAX


# ---------------------------------------------------------------------------
# Warum die Schweiz ohne Kantone kommt
# ---------------------------------------------------------------------------


def test_die_kantonsseiten_fuehren_keinen_eigenen_preis():
    """Der Beleg für die Entscheidung in `const.py`.

    Gemessen am 09.08.2026: 14 der 26 Kantone liefern gar keinen Preis, die
    übrigen 12 liefern ausnahmslos exakt die Landeszahl. Deshalb bietet die
    Integration für die Schweiz nur „Schweiz" an.

    Die deutschen Bundesländer sind die **Positivkontrolle**: fände dieselbe
    Messung auch dort überall denselben Wert, wäre der Befund kein Befund,
    sondern ein kaputter Test.

    Schlägt dieser Test fehl, weil die Kantone eigene Preise bekommen haben,
    ist das eine gute Nachricht — dann gehören sie in `const.py`.
    """
    land = parse_landesseite(hole(CH.basis_url), CH.name).lose.preis_pro_tonne

    kantonspreise: dict[str, float] = {}
    for slug in KANTONE_CH:
        try:
            kantonspreise[slug] = parse_bundesland(
                hole(f"{CH.basis_url}/{slug}"), slug
            ).lose.preis_pro_tonne
        except KeinAngebot:
            continue

    abweichend = {s: p for s, p in kantonspreise.items() if p != land}
    print(
        f"\nSchweiz {land} CHF/t · {len(kantonspreise)} von {len(KANTONE_CH)} "
        f"Kantonen mit Preis · davon abweichend: {abweichend or 'keiner'}"
    )
    assert not abweichend, (
        "Mindestens ein Kanton hat einen eigenen Preis — die Schweiz kann "
        f"jetzt regional aufgelöst werden: {abweichend}"
    )

    # Positivkontrolle: dieselbe Messung muss in Deutschland anschlagen.
    bund = parse_landesseite(hole(DE.basis_url), DE.name).lose.preis_pro_tonne
    deutsche = [
        parse_bundesland(hole(f"{DE.basis_url}/{slug}"), slug).lose.preis_pro_tonne
        for slug in ("bayern", "nordrhein-westfalen", "sachsen")
    ]
    assert any(p != bund for p in deutsche), (
        "Auch in Deutschland weicht kein Bundesland vom Bundesdurchschnitt ab "
        "— die Messung greift nicht, der Schweizer Befund oben ist wertlos."
    )


# ---------------------------------------------------------------------------
# Langfristwerte und Vergleich
# ---------------------------------------------------------------------------


def test_die_bundeslandseiten_fuehren_keine_langfristwerte():
    """Belegt, warum es die Sensoren „(beobachtet)" überhaupt gibt.

    Die Quelle nennt Tief- und Höchstwerte nur auf der Landesseite. Die
    Landesseite ist hier die **Positivkontrolle**: fände die Suche dort
    ebenfalls nichts, wäre der Befund kein Befund, sondern ein kaputter Test.

    Schlägt dieser Test eines Tages fehl, weil `low3Y` auch auf einer
    Bundesland-Seite auftaucht, ist das eine gute Nachricht — dann kann die
    Integration echte Langfristwerte je Bundesland liefern statt eigener
    Aufzeichnungen.
    """
    for land, slug in ((DE, "bayern"), (AT, "wien")):
        landesseite = hole(land.basis_url)
        assert "low3Y" in landesseite and "high3Y" in landesseite, (
            f"Auf der {land.name}-Seite fehlen low3Y/high3Y — die Gegenprobe "
            "greift nicht, der Befund unten wäre wertlos."
        )
        regionsseite = hole(f"{land.basis_url}/{slug}")
        assert "low3Y" not in regionsseite
        assert "high3Y" not in regionsseite


@pytest.mark.parametrize(
    ("land", "regionen"), [(DE, BUNDESLAENDER_DE), (AT, BUNDESLAENDER_AT)],
    ids=lambda w: w.code if hasattr(w, "code") else "",
)
def test_bundeslandvergleich_gegen_die_echte_seite(land, regionen):
    """Alle Seiten holen und daraus günstigstes/teuerstes Land bestimmen.

    Prüft genau den Weg, den die Integration bei eingeschaltetem Vergleich
    geht — nur ohne aiohttp. Die Zusicherungen sind bewusst grob: die Preise
    ändern sich täglich, festnageln lässt sich die **Form** der Auskunft.
    """
    preise: dict[str, float | None] = {}
    for slug in sorted(regionen):
        try:
            preise[slug] = parse_bundesland(
                hole(f"{land.basis_url}/{slug}"), slug
            ).lose.preis_pro_tonne
        except KeinAngebot:
            preise[slug] = None

    vergleich = bilde_vergleich(preise, regionen)
    assert vergleich is not None
    mit_preis = [p for p in preise.values() if p is not None]
    assert len(vergleich.preise) == len(mit_preis)
    assert vergleich.guenstigste.preis_pro_tonne == min(mit_preis)
    assert vergleich.teuerste.preis_pro_tonne == max(mit_preis)
    assert vergleich.guenstigste.preis_pro_tonne < vergleich.teuerste.preis_pro_tonne, (
        f"Alle {len(mit_preis)} Bundesländer zum selben Preis — vermutlich "
        "wird dieselbe Seite mehrfach gelesen."
    )
    print(
        f"\n{land.name}: Günstigstes {vergleich.guenstigste.name} "
        f"{vergleich.guenstigste.preis_pro_tonne} {land.waehrung}/t · "
        f"Teuerstes {vergleich.teuerste.name} "
        f"{vergleich.teuerste.preis_pro_tonne} {land.waehrung}/t · "
        f"Spanne {vergleich.spanne} {land.waehrung}/t · "
        f"ohne Angebot: {vergleich.ohne_angebot or 'keines'}"
    )


@pytest.mark.parametrize("land", [DE, AT, CH], ids=lambda l: l.code)
def test_landesdurchschnitt_wird_je_plz_gebildet(land):
    """Deckt den Hinweis, der an den Vergleichssensoren steht.

    Der Sensor sagt in seinem Attribut ``hinweis``, der Landesdurchschnitt
    entstehe je Postleitzahl und nicht aus den Bundeslandwerten. Beleg ist das
    Kleingedruckte der Quelle selbst — nicht der Zahlenabstand: am 08.08.2026
    lagen Bundesdurchschnitt (406,51) und Mittel der 16 Länder (406,16) nur
    0,35 € auseinander. Wer daraus eine Aussage bauen wollte, hätte ein
    Ersatzsignal: nah beieinander heißt weder „dasselbe" noch „etwas anderes".
    """
    seite = hole(land.basis_url)
    assert "auf Basis des günstigsten Händlerangebots je PLZ" in seite, (
        f"Das Kleingedruckte der {land.name}-Seite nennt die PLZ-Basis nicht "
        "mehr — der Hinweis am Sensor ist dann nicht mehr belegt."
    )


@pytest.mark.parametrize("land", [DE, AT, CH], ids=lambda l: l.code)
def test_bezugsmenge_steht_weiterhin_bei_6000_kg(land):
    """Die Grundlage jeder Hochrechnung — auf allen drei Seiten dieselbe.

    Ändert die Quelle ihre Bezugsmenge, wäre jeder Gesamtpreis still um den
    Faktor daneben. `REFERENZMENGE_KG` ist eine gelesene Tatsache, keine
    Annahme, und gehört deshalb nachgemessen.
    """
    assert "Gesamtabnahme von 6.000 kg" in hole(land.basis_url)


def test_regionen_liefern_unterschiedliche_preise():
    """Gegenprobe gegen einen Parser, der überall dasselbe liest."""
    bund = parse_landesseite(hole(DE.basis_url), DE.name).lose.preis_pro_tonne
    bayern = parse_bundesland(
        hole(f"{DE.basis_url}/bayern"), "bayern"
    ).lose.preis_pro_tonne
    nrw = parse_bundesland(
        hole(f"{DE.basis_url}/nordrhein-westfalen"), "nordrhein-westfalen"
    ).lose.preis_pro_tonne
    assert len({bund, bayern, nrw}) == 3, (
        f"Bund={bund}, Bayern={bayern}, NRW={nrw} — mindestens zwei Regionen "
        "liefern denselben Wert; vermutlich wird die falsche Seite gelesen"
    )
    assert REGION_DEUTSCHLAND == "deutschland"


def test_die_drei_landesseiten_liefern_verschiedene_zahlen():
    """Gegenprobe: liefert .at heimlich die .de-Seite aus, fällt es hier auf.

    Ein solcher Fehler wäre sonst unsichtbar — die Zahlen sähen plausibel aus,
    nur eben für das falsche Land.
    """
    werte = {
        land.code: parse_landesseite(hole(land.basis_url), land.name).lose.preis_pro_tonne
        for land in (DE, AT, CH)
    }
    assert len(set(werte.values())) == 3, f"Zwei Länder mit demselben Preis: {werte}"
    assert {REGION_DEUTSCHLAND, REGION_OESTERREICH, REGION_SCHWEIZ} == {
        land.landesregion for land in (DE, AT, CH)
    }
