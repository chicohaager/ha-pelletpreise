"""Tests für den heizpellets24-Parser.

Die Fixtures sind echte, am 07.08.2026 abgerufene Seiten. Die erwarteten Zahlen
stammen **nicht** aus dem Parser selbst, sondern aus der im Browser gerenderten
Bundesland-Tabelle von heizpellets24.de — sonst würde der Test nur bestätigen,
dass der Parser tut, was er tut:

    Bundesland          | Lose Ware | Sackware
    Bayern              |    400,38 |   477,86
    Baden-Württemberg   |    414,22 |   493,79

Neben den Positivfällen steht hier bewusst genauso viel Negativprüfung: ein
Parser, der bei kaputter Eingabe irgendetwas zurückgibt, ist gefährlicher als
gar keiner. Jeder Fehlerfall bekommt eine eigene Zusicherung.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pelletpreise.parser import (  # noqa: E402
    PLAUSIBEL_MAX,
    KeinAngebot,
    ParseError,
    parse_bundesland,
    parse_landesseite,
)

FIXTURES = Path(__file__).parent / "fixtures"


def lies(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Positivfälle — Werte gegen die gerenderte Website geprüft
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("datei", "lose", "sackware"),
    [
        ("bayern.html", 400.38, 477.86),
        ("baden-wuerttemberg.html", 414.22, 493.79),
    ],
)
def test_bundesland_liefert_die_angezeigten_preise(datei, lose, sackware):
    preise = parse_bundesland(lies(datei), datei)
    assert preise.lose.preis_pro_tonne == lose
    assert preise.sackware is not None
    assert preise.sackware.preis_pro_tonne == sackware


def test_zwei_bundeslaender_haben_verschiedene_preise():
    """Positivkontrolle gegen einen Parser, der stets denselben Wert findet.

    Ohne diese Zusicherung würde ein Parser, der versehentlich immer den
    Bundesdurchschnitt (406,26) liest, alle Einzeltests oben bestehen, sobald
    man deren Erwartungswerte anpasst.
    """
    bayern = parse_bundesland(lies("bayern.html"), "Bayern")
    bw = parse_bundesland(lies("baden-wuerttemberg.html"), "BW")
    assert bayern.lose.preis_pro_tonne != bw.lose.preis_pro_tonne
    assert bayern.lose.preis_pro_tonne != 406.26, (
        "Der Parser hat den Bundesdurchschnitt statt des Regionalpreises gelesen"
    )


def test_sackware_ist_gemessen_und_nicht_hochgerechnet():
    """Die Vorgängerversion rechnete Sackware als lose × 1,12.

    Genau dieser Zusammenhang darf nicht mehr bestehen — sonst wäre wieder
    eine Schätzung als Messwert unterwegs.
    """
    for datei in ("bayern.html", "baden-wuerttemberg.html"):
        preise = parse_bundesland(lies(datei), datei)
        hochgerechnet = preise.lose.preis_pro_tonne * 1.12
        assert abs(preise.sackware.preis_pro_tonne - hochgerechnet) > 1.0, (
            f"{datei}: Sackware entspricht rechnerisch lose × 1,12 — "
            "das war der alte Schätzwert, kein gelesener Preis"
        )


def test_wochenaenderung_wird_mitgelesen():
    preise = parse_bundesland(lies("bayern.html"), "Bayern")
    assert preise.lose.aenderung_prozent_woche == pytest.approx(0.31)
    assert preise.sackware.aenderung_prozent_woche == pytest.approx(2.68)


def test_deutschland_liefert_durchschnitt_und_langfristwerte():
    preise = parse_landesseite(lies("deutschland.html"), "Deutschland")
    assert preise.lose.preis_pro_tonne == 406.26
    assert preise.lose.aenderung_prozent_woche == pytest.approx(0.88)
    assert preise.differenz_woche == pytest.approx(3.56)
    assert preise.differenz_3monate == pytest.approx(48.76)
    assert preise.tief_3jahre == pytest.approx(242.92)
    assert preise.hoch_3jahre == pytest.approx(406.4)
    assert preise.schnitt_3jahre == pytest.approx(313.43)


# ---------------------------------------------------------------------------
# Negativfälle — der Parser muss scheitern statt zu raten
# ---------------------------------------------------------------------------


def test_falsche_seite_wird_erkannt():
    """Deutschland-Seite an den Bundesland-Parser: kein localPrices-Block."""
    with pytest.raises(ParseError, match="localPrices.*leer"):
        parse_bundesland(lies("deutschland.html"), "Deutschland")


def test_bundeslandseite_am_landesparser_wird_erkannt():
    with pytest.raises(ParseError, match="countryAvg"):
        parse_landesseite(lies("bayern.html"), "Bayern")


def test_seite_ohne_nuxt_payload():
    with pytest.raises(ParseError, match="window.__NUXT__"):
        parse_bundesland("<html><body>Wartungsarbeiten</body></html>", "Bayern")


def test_leere_antwort():
    with pytest.raises(ParseError):
        parse_bundesland("", "Bayern")


def test_html_fehlerseite_liefert_keinen_preis():
    """Ein HTTP-Fehler mit HTML-Body darf nicht zufällig als Preis durchgehen."""
    fehlerseite = "<html><h1>404</h1><p>Preis: 406,26 € pro 1.000kg</p></html>"
    with pytest.raises(ParseError):
        parse_bundesland(fehlerseite, "Bayern")


def test_abgeschnittener_payload():
    html = lies("bayern.html")
    beschnitten = html[: html.find("window.__NUXT__") + 8000]
    with pytest.raises(ParseError):
        parse_bundesland(beschnitten, "Bayern")


def test_unplausibler_preis_wird_verworfen():
    """Ein Wert außerhalb des Plausibilitätsbereichs darf nicht durchrutschen."""
    html = lies("bayern.html")
    # 400.38 ist der Preis für lose Ware im Payload; auf einen unmöglichen
    # Wert verbogen muss der Parser das als Parse-Fehler melden.
    verbogen = html.replace("400.38", str(PLAUSIBEL_MAX + 1000), 1)
    assert verbogen != html, "Die Sabotage kam nicht an — der Test prüft nichts"
    with pytest.raises(ParseError, match="plausibl"):
        parse_bundesland(verbogen, "Bayern")


def test_preis_null_gilt_als_keine_daten():
    """Produkt-ID 27 (Big Bags) steht in den Fixtures auf 0.

    0 heißt "kein Angebot", nicht "kostenlos" — der Parser darf daraus keinen
    Preis machen. Geprüft an Sackware, indem deren Wert auf 0 gesetzt wird.
    """
    html = lies("bayern.html")
    verbogen = html.replace("477.86", "0", 1)
    assert verbogen != html, "Die Sabotage kam nicht an — der Test prüft nichts"
    preise = parse_bundesland(verbogen, "Bayern")
    assert preise.sackware is None
    assert preise.lose.preis_pro_tonne == 400.38


def test_fehlende_lose_ware_ist_ein_fehler():
    html = lies("bayern.html")
    verbogen = html.replace("400.38", "0", 1)
    assert verbogen != html, "Die Sabotage kam nicht an — der Test prüft nichts"
    with pytest.raises(KeinAngebot, match="lose"):
        parse_bundesland(verbogen, "Bayern")


def test_kein_angebot_ist_ein_parsefehler_und_bleibt_unterscheidbar():
    """Beides muss gelten, und beides hat einen Zweck.

    `KeinAngebot` erbt von `ParseError`, damit jede bestehende Behandlung
    weiter greift (ein einzelner Regionseintrag wird „nicht verfügbar").
    Gleichzeitig muss es sich abfangen lassen, damit der Bundesland-Vergleich
    eine Region ohne Angebot überspringen kann, statt sich an ihr aufzuhängen
    — ein `except ParseError` an dieser Stelle würde auch echte Formatfehler
    verschlucken.
    """
    assert issubclass(KeinAngebot, ParseError)
    assert KeinAngebot is not ParseError


# ---------------------------------------------------------------------------
# Österreich und Schweiz — dieselbe Seitentechnik, andere Domain
#
# Die Fixtures sind am 09.08.2026 abgerufene Seiten von heizpellets24.at bzw.
# .ch. Die Erwartungswerte stammen aus der gerenderten Seite:
#
#     Österreich  416,14 €/t     Wien     407,00 €/t lose, 495,05 €/t Sackware
#     Schweiz     522,12 CHF/t   Vorarlberg: kein Preis für lose Ware
# ---------------------------------------------------------------------------


def test_oesterreich_liefert_durchschnitt_und_langfristwerte():
    preise = parse_landesseite(lies("oesterreich.html"), "Österreich")
    assert preise.lose.preis_pro_tonne == 416.14
    assert preise.lose.waehrung == "€"
    assert preise.tief_3jahre == pytest.approx(282.1)
    assert preise.hoch_3jahre == pytest.approx(422.93)


def test_oesterreichische_bundeslandseite_liefert_lose_und_sackware():
    preise = parse_bundesland(lies("wien.html"), "Wien")
    assert preise.lose.preis_pro_tonne == 407.00
    assert preise.sackware is not None
    assert preise.sackware.preis_pro_tonne == 495.05
    assert preise.sackware.aenderung_prozent_woche == pytest.approx(8.24)


def test_oesterreich_hat_andere_preise_als_deutschland():
    """Positivkontrolle gegen eine Domain, die stillschweigend .de ausliefert.

    Ohne diese Zusicherung wäre ein Umleiten von .at nach .de nicht von einem
    funktionierenden Abruf zu unterscheiden — die Zahlen sähen plausibel aus.
    """
    at = parse_landesseite(lies("oesterreich.html"), "Österreich").lose.preis_pro_tonne
    de = parse_landesseite(lies("deutschland.html"), "Deutschland").lose.preis_pro_tonne
    assert at != de


def test_schweiz_wird_in_franken_gefuehrt():
    """Der Kern der Länder-Erweiterung.

    Die Zahl allein verrät die Währung nicht: 522 ist als Euro genauso
    plausibel wie als Franken. Deshalb wird sie gelesen und nicht angenommen.
    """
    preise = parse_landesseite(lies("schweiz.html"), "Schweiz")
    assert preise.lose.preis_pro_tonne == 522.12
    assert preise.lose.waehrung == "CHF"
    assert preise.waehrung == "CHF"


def test_deutschland_und_oesterreich_werden_in_euro_gefuehrt():
    """Gegenprobe: die Währung wird wirklich gelesen und nicht geraten."""
    for datei, name in (("deutschland.html", "Deutschland"), ("oesterreich.html", "Österreich")):
        assert parse_landesseite(lies(datei), name).lose.waehrung == "€"


def test_region_ohne_preis_meldet_kein_angebot():
    """Vorarlberg führte am 09.08.2026 keinen Preis für lose Ware.

    Kein Lesefehler, sondern eine Auskunft der Quelle — und deshalb eine
    eigene Ausnahme, die der Vergleich überspringen darf.
    """
    with pytest.raises(KeinAngebot, match="lose"):
        parse_bundesland(lies("vorarlberg.html"), "Vorarlberg")


def test_fehlende_waehrung_wird_nicht_durch_eine_annahme_ersetzt():
    html = lies("schweiz.html")
    verbogen = html.replace("currency:", "waehrung:")
    assert verbogen != html, "Die Sabotage kam nicht an — der Test prüft nichts"
    with pytest.raises(ParseError, match="currency"):
        parse_landesseite(verbogen, "Schweiz")
