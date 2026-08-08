"""Tests für die Hochrechnung und die Einblaspauschale.

Die Preise in den Beispielen sind die echten Werte der Fixtures vom 07.08.2026
(Bayern: 400,38 €/t lose, 477,86 €/t Sackware) — dieselben Zahlen, gegen die
auch `test_parser.py` prüft. Die erwarteten Ergebnisse sind **von Hand**
gerechnet und nicht aus dem Modul übernommen; sonst würde der Test nur
bestätigen, dass die Funktion tut, was sie tut.

Der eigentliche Zweck dieser Datei steht in `test_pauschale_landet_nur_im_gesamtpreis_der_losen_ware`:
die Einblaspauschale ist die einzige selbst eingetragene Zahl im ganzen
Datenpfad. Sie darf im Gesamtpreis der losen Ware landen und **sonst nirgends**
— weder im Preis je Tonne noch bei der Sackware. Genau das wird hier
festgenagelt, statt sich darauf zu verlassen, dass es beim nächsten neuen
Sensor jemand bedenkt.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pelletpreise.berechnung import (  # noqa: E402
    berechnungstext,
    euro,
    gesamtpreis_euro,
    pruefe_einblaspauschale,
    warenwert_euro,
)
from pelletpreise.const import (  # noqa: E402
    DEFAULT_EINBLASPAUSCHALE,
    MAX_EINBLASPAUSCHALE,
    MIN_EINBLASPAUSCHALE,
)

BAYERN_LOSE = 400.38
BAYERN_SACKWARE = 477.86
SENSOR_PY = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "pelletpreise"
    / "sensor.py"
)


# ---------------------------------------------------------------------------
# Warenwert — unverändertes Verhalten der Vorversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("euro_pro_tonne", "menge_kg", "erwartet"),
    [
        (BAYERN_LOSE, 6000, 2402.28),  # 400,38 × 6 = 2402,28
        (BAYERN_LOSE, 3000, 1201.14),
        (BAYERN_SACKWARE, 6000, 2867.16),  # 477,86 × 6 = 2867,16
        (BAYERN_LOSE, 500, 200.19),
    ],
)
def test_warenwert_ist_lineare_hochrechnung(euro_pro_tonne, menge_kg, erwartet):
    assert warenwert_euro(euro_pro_tonne, menge_kg) == erwartet


# ---------------------------------------------------------------------------
# Einblaspauschale
# ---------------------------------------------------------------------------


def test_ohne_pauschale_bleibt_der_gesamtpreis_unveraendert():
    """Der Regressionsschutz für alle bestehenden Einrichtungen.

    Wer die Integration vor dieser Änderung eingerichtet hat, hat keinen
    Zuschlag stehen. Sein Gesamtpreis muss auf den Cent derselbe bleiben —
    ein stillschweigend geänderter Preis wäre der schlimmste Ausgang dieser
    Erweiterung.
    """
    assert DEFAULT_EINBLASPAUSCHALE == 0.0
    assert gesamtpreis_euro(BAYERN_LOSE, 6000, DEFAULT_EINBLASPAUSCHALE) == 2402.28
    assert gesamtpreis_euro(BAYERN_LOSE, 6000) == warenwert_euro(BAYERN_LOSE, 6000)


@pytest.mark.parametrize(
    ("pauschale", "erwartet"),
    [
        (45.0, 2447.28),  # 2402,28 + 45,00
        (44.90, 2447.18),  # krummer Händlerbetrag
        (0.01, 2402.29),
        (MAX_EINBLASPAUSCHALE, 2902.28),
    ],
)
def test_pauschale_wird_einmal_auf_die_bestellung_geschlagen(pauschale, erwartet):
    assert gesamtpreis_euro(BAYERN_LOSE, 6000, pauschale) == erwartet


def test_pauschale_haengt_nicht_an_der_bestellmenge():
    """Sie fällt je Lieferung an, nicht je Tonne.

    Wäre sie in den €/t-Wert gemischt, ergäbe die doppelte Menge auch den
    doppelten Zuschlag — und der Preisverlauf spränge, sobald jemand seine
    Bestellmenge ändert.
    """
    for menge in (500, 3000, 6000, 30000):
        aufschlag = gesamtpreis_euro(BAYERN_LOSE, menge, 45.0) - warenwert_euro(
            BAYERN_LOSE, menge
        )
        assert round(aufschlag, 2) == 45.0


@pytest.mark.parametrize("grenzwert", [MIN_EINBLASPAUSCHALE, MAX_EINBLASPAUSCHALE])
def test_grenzwerte_sind_zulaessig(grenzwert):
    assert pruefe_einblaspauschale(grenzwert) == grenzwert


@pytest.mark.parametrize(
    "unsinn",
    [
        -1.0,  # würde den Gesamtpreis senken, ohne dass etwas auffiele
        -0.01,
        MAX_EINBLASPAUSCHALE + 0.01,
        4500.0,  # verrutschtes Komma bei 45,00
        float("nan"),
        float("inf"),
    ],
)
def test_unsinnige_betraege_werden_laut_abgelehnt(unsinn):
    """Kein Zurechtbiegen: ein stumm auf 0 gesetzter Wert wäre unsichtbar."""
    with pytest.raises(ValueError, match="Einblaspauschale"):
        pruefe_einblaspauschale(unsinn)


@pytest.mark.parametrize("unsinn", ["fünfundvierzig", None, object()])
def test_nichtzahlen_werden_abgelehnt(unsinn):
    with pytest.raises(ValueError, match="Einblaspauschale"):
        pruefe_einblaspauschale(unsinn)


def test_gesamtpreis_prueft_die_pauschale_mit():
    """Der Fehler muss auch dann kommen, wenn niemand vorher separat prüft."""
    with pytest.raises(ValueError, match="Einblaspauschale"):
        gesamtpreis_euro(BAYERN_LOSE, 6000, -5.0)


# ---------------------------------------------------------------------------
# Klartext am Sensor
# ---------------------------------------------------------------------------


def test_euro_formatiert_deutsch():
    assert euro(45.0) == "45,00 €"
    assert euro(44.9) == "44,90 €"
    assert euro(0) == "0,00 €"


def test_text_ohne_pauschale_erwaehnt_sie_nicht():
    text = berechnungstext(6000, 0.0)
    assert "Einblaspauschale" not in text
    assert "6000 kg ÷ 1000" in text
    assert "lineare Hochrechnung" in text


def test_text_mit_pauschale_nennt_betrag_und_herkunft():
    """Die Herkunftszeile ist der Kern.

    Ohne sie steht im Sensor eine Zahl, die aussieht wie von der Quelle
    gelesen, in Wahrheit aber selbst eingetragen wurde.
    """
    text = berechnungstext(6000, 45.0)
    assert "+ 45,00 € Einblaspauschale" in text
    assert "stammt nicht von heizpellets24.de" in text


# ---------------------------------------------------------------------------
# Verdrahtung: wo die Pauschale einfließen darf — und wo nicht
# ---------------------------------------------------------------------------


def _sensoren_mit_pauschale() -> tuple[set[str], set[str]]:
    """Lies aus `sensor.py`, welche Sensoren die Pauschale einrechnen.

    Bewusst über den Syntaxbaum statt über einen Import: `sensor.py` zieht
    Home Assistant nach, und dieser Test soll ohne HA-Installation laufen —
    genauso wie der Rest der Suite. Bewusst auch nicht per `grep`: gesucht ist
    die Zuordnung *Sensor → Argument*, und die steht in der Struktur, nicht in
    einer Zeile.

    Gibt (alle Sensorschlüssel, Schlüssel mit mit_einblaspauschale=True) zurück.
    """
    baum = ast.parse(SENSOR_PY.read_text(encoding="utf-8"))
    alle: set[str] = set()
    mit_pauschale: set[str] = set()

    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.Call):
            continue
        if getattr(knoten.func, "id", None) != "PelletpreisSensorDescription":
            continue
        schluessel = next(
            (
                kw.value.value
                for kw in knoten.keywords
                if kw.arg == "key" and isinstance(kw.value, ast.Constant)
            ),
            None,
        )
        assert schluessel is not None, "Sensorbeschreibung ohne 'key' gefunden"
        alle.add(schluessel)

        for unterknoten in ast.walk(knoten):
            if not isinstance(unterknoten, ast.keyword):
                continue
            if unterknoten.arg != "mit_einblaspauschale":
                continue
            assert isinstance(unterknoten.value, ast.Constant), (
                f"{schluessel}: mit_einblaspauschale muss eine Konstante sein, "
                "sonst ist hier nicht mehr prüfbar, welcher Sensor zurechnet."
            )
            if unterknoten.value.value is True:
                mit_pauschale.add(schluessel)

    return alle, mit_pauschale


def test_pauschale_landet_nur_im_gesamtpreis_der_losen_ware():
    """Genau ein Sensor darf die selbst eingetragene Zahl enthalten.

    Positivkontrolle für diesen Test: setzt man in `sensor.py` bei
    `sackware_gesamt` `mit_einblaspauschale=True`, wird er rot. Nimmt man sie
    bei `lose_gesamt` heraus, ebenfalls.
    """
    alle, mit_pauschale = _sensoren_mit_pauschale()
    assert alle, "In sensor.py wurde keine einzige Sensorbeschreibung gefunden"
    assert mit_pauschale == {"lose_gesamt"}


def test_jeder_gesamtpreis_entscheidet_die_frage_ausdruecklich():
    """Kein Sensor darf die Pauschale versehentlich mitbeantworten.

    `gesamtpreis()` hat für `mit_einblaspauschale` bewusst keine Vorgabe. Wer
    einen neuen Gesamtpreis-Sensor anlegt, muss sich entscheiden — dieser Test
    stellt sicher, dass das so bleibt und nicht doch eine Vorgabe einzieht.
    """
    quelltext = SENSOR_PY.read_text(encoding="utf-8")
    baum = ast.parse(quelltext)
    aufrufe = [
        knoten
        for knoten in ast.walk(baum)
        if isinstance(knoten, ast.Call)
        and getattr(knoten.func, "attr", None) in ("gesamtpreis", "berechnung")
    ]
    assert aufrufe, "In sensor.py wurde kein Aufruf von gesamtpreis()/berechnung() gefunden"
    for aufruf in aufrufe:
        argumente = {kw.arg for kw in aufruf.keywords}
        assert "mit_einblaspauschale" in argumente, (
            f"Aufruf in Zeile {aufruf.lineno} entscheidet nicht ausdrücklich "
            "über die Einblaspauschale."
        )
