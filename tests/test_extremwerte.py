"""Tests für die selbst aufgezeichneten Tief- und Höchstwerte.

Diese Sensoren sind der einzige Ort neben der Einblaspauschale, an dem ein
Wert **nicht** aus der Quelle stammt, sondern aus der eigenen Buchführung.
Zwei Eigenschaften entscheiden darüber, ob die Auskunft etwas taugt, und beide
sind hier festgenagelt:

* Der Rekord darf nur in eine Richtung wandern. Ein Tiefstwert, der bei einem
  teureren Tag mitsteigt, wäre kein Tiefstwert, sondern der Tagespreis mit
  einem falschen Namen.
* ``beobachtet_seit`` darf niemals mitspringen. Ohne diesen Bezug ist der Wert
  nicht deutbar — 380 €/t bedeutet nach drei Tagen etwas anderes als nach
  zwei Jahren.
"""

from __future__ import annotations

import pytest

from pelletpreise.extremwerte import (  # noqa: E402
    MODUS_HOCH,
    MODUS_TIEF,
    Extremwert,
    aus_speicher,
    fortschreiben,
    fuer_speicher,
)
from pelletpreise.parser import PLAUSIBEL_MAX, PLAUSIBEL_MIN  # noqa: E402

GESTERN = "2026-08-07T09:00:00+02:00"
HEUTE = "2026-08-08T09:00:00+02:00"


# ---------------------------------------------------------------------------
# Fortschreiben
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("modus", [MODUS_TIEF, MODUS_HOCH])
def test_der_erste_wert_beginnt_die_aufzeichnung(modus):
    extrem = fortschreiben(None, 400.38, HEUTE, modus=modus)
    assert extrem.preis_pro_tonne == 400.38
    assert extrem.gesehen_am == HEUTE
    assert extrem.beobachtet_seit == HEUTE


def test_tiefstwert_faellt_nur():
    start = fortschreiben(None, 400.38, GESTERN, modus=MODUS_TIEF)

    teurer = fortschreiben(start, 420.00, HEUTE, modus=MODUS_TIEF)
    assert teurer == start, "Ein teurerer Tag darf den Tiefstwert nicht anheben"

    billiger = fortschreiben(start, 388.10, HEUTE, modus=MODUS_TIEF)
    assert billiger.preis_pro_tonne == 388.10
    assert billiger.gesehen_am == HEUTE


def test_hoechstwert_steigt_nur():
    start = fortschreiben(None, 400.38, GESTERN, modus=MODUS_HOCH)

    billiger = fortschreiben(start, 388.10, HEUTE, modus=MODUS_HOCH)
    assert billiger == start, "Ein billigerer Tag darf den Höchstwert nicht senken"

    teurer = fortschreiben(start, 420.00, HEUTE, modus=MODUS_HOCH)
    assert teurer.preis_pro_tonne == 420.00
    assert teurer.gesehen_am == HEUTE


@pytest.mark.parametrize("modus", [MODUS_TIEF, MODUS_HOCH])
def test_beobachtungsbeginn_springt_bei_einem_rekord_nicht_mit(modus):
    """Der Beginn gehört der Aufzeichnung, nicht dem Wert."""
    start = fortschreiben(None, 400.38, GESTERN, modus=modus)
    neu = fortschreiben(
        start, 200.00 if modus == MODUS_TIEF else 900.00, HEUTE, modus=modus
    )
    assert neu.gesehen_am == HEUTE
    assert neu.beobachtet_seit == GESTERN


@pytest.mark.parametrize("modus", [MODUS_TIEF, MODUS_HOCH])
def test_gleichstand_behaelt_das_erste_datum(modus):
    """Gefragt ist, seit wann der Preis das Extrem ist — nicht wann zuletzt.

    Ohne diese Regel wanderte das Datum bei einem seit Wochen unveränderten
    Preis täglich mit und sähe aus wie ein täglich neuer Rekord.
    """
    start = fortschreiben(None, 400.38, GESTERN, modus=modus)
    gleich = fortschreiben(start, 400.38, HEUTE, modus=modus)
    assert gleich.gesehen_am == GESTERN


def test_unbekannter_modus_wird_abgelehnt():
    with pytest.raises(ValueError, match="Modus"):
        fortschreiben(None, 400.38, HEUTE, modus="mittelwert")


# ---------------------------------------------------------------------------
# Speichern und Zurücklesen
# ---------------------------------------------------------------------------


def test_rundreise_durch_den_speicher():
    extrem = Extremwert(
        preis_pro_tonne=400.38, gesehen_am=GESTERN, beobachtet_seit=GESTERN
    )
    assert aus_speicher(fuer_speicher(extrem)) == extrem


def test_nichts_gespeichert_ist_kein_fehler():
    assert aus_speicher(None) is None


@pytest.mark.parametrize(
    ("rohdaten", "erwartet"),
    [
        ({"gesehen_am": HEUTE, "beobachtet_seit": HEUTE}, "preis_pro_tonne"),
        ({"preis_pro_tonne": 400.38, "gesehen_am": HEUTE}, "beobachtet_seit"),
        (
            {"preis_pro_tonne": "400,38", "gesehen_am": HEUTE, "beobachtet_seit": HEUTE},
            "keine Zahl",
        ),
        (
            {"preis_pro_tonne": True, "gesehen_am": HEUTE, "beobachtet_seit": HEUTE},
            "keine Zahl",
        ),
        (
            {
                "preis_pro_tonne": PLAUSIBEL_MIN - 1,
                "gesehen_am": HEUTE,
                "beobachtet_seit": HEUTE,
            },
            "plausiblen Bereichs",
        ),
        (
            {
                "preis_pro_tonne": PLAUSIBEL_MAX + 1,
                "gesehen_am": HEUTE,
                "beobachtet_seit": HEUTE,
            },
            "plausiblen Bereichs",
        ),
        (
            {
                "preis_pro_tonne": 400.38,
                "gesehen_am": "gestern früh",
                "beobachtet_seit": HEUTE,
            },
            "Zeitstempel",
        ),
        (
            {"preis_pro_tonne": 400.38, "gesehen_am": 17, "beobachtet_seit": HEUTE},
            "kein Text",
        ),
        ("400.38", "kein Objekt"),
    ],
)
def test_unbrauchbares_gespeichertes_wird_laut_abgelehnt(rohdaten, erwartet):
    """Kein stiller Ersatzwert.

    Ein still auf den heutigen Preis gesetzter „Rekord" sähe im Sensor exakt
    aus wie ein echter. Deshalb fliegt hier ein Fehler, den der Sensor ins
    Protokoll schreibt, bevor er die Aufzeichnung neu beginnt.
    """
    with pytest.raises(ValueError, match=erwartet):
        aus_speicher(rohdaten)


def test_die_plausibilitaetssperre_laesst_echte_preise_durch():
    """Positivkontrolle zu den Ablehnungen oben.

    Ohne sie wäre nicht zu unterscheiden, ob die Sperre die richtigen Werte
    ablehnt oder einfach alles.
    """
    for preis in (PLAUSIBEL_MIN, 242.92, 400.38, 712.50, PLAUSIBEL_MAX):
        rohdaten = {
            "preis_pro_tonne": preis,
            "gesehen_am": HEUTE,
            "beobachtet_seit": HEUTE,
        }
        assert aus_speicher(rohdaten).preis_pro_tonne == preis


# ---------------------------------------------------------------------------
# Umbenennung des gespeicherten Feldes
# ---------------------------------------------------------------------------


def test_alte_aufzeichnungen_ueberleben_die_umbenennung():
    """Bis 2.2.0 hieß das Feld "euro_pro_tonne".

    Wer seit Monaten aufzeichnet, hat genau diese Form in seinem
    Zustandsspeicher stehen. Würde sie nicht mehr gelesen, wäre der Rekord
    beim Update still weg — und der Sensor begänne beim heutigen Preis von
    vorn, ohne dass irgendetwas darauf hindeutete.
    """
    alt = {
        "euro_pro_tonne": 242.92,
        "gesehen_am": GESTERN,
        "beobachtet_seit": GESTERN,
    }
    wieder = aus_speicher(alt)
    assert wieder.preis_pro_tonne == 242.92
    assert wieder.beobachtet_seit == GESTERN


def test_geschrieben_wird_der_neue_name():
    """Positivkontrolle zur Verträglichkeit oben.

    Ohne sie könnte weiterhin der alte Name geschrieben werden, und der Test
    darüber wäre trotzdem grün — die Umbenennung hätte dann gar nicht
    stattgefunden.
    """
    gespeichert = fuer_speicher(
        Extremwert(preis_pro_tonne=522.12, gesehen_am=HEUTE, beobachtet_seit=HEUTE)
    )
    assert "preis_pro_tonne" in gespeichert
    assert "euro_pro_tonne" not in gespeichert
    assert aus_speicher(gespeichert).preis_pro_tonne == 522.12
