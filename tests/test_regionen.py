"""Tests für Länder, Regionsliste und Sensor-Zuordnung.

Diese Tests brauchen kein Home Assistant: `const.py` importiert bewusst nichts
aus dem Framework, damit genau diese Logik offline prüfbar bleibt.

Der Slug ist hier die gefährliche Stelle. Er ist dreierlei zugleich: Teil der
URL, `unique_id` des Eintrags und Schlüssel für die Zuordnung zum Land. Ein
falscher Slug liefert nicht etwa einen Fehler, sondern klaglos die Landesseite
— und damit den falschen Preis.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pelletpreise.const import (  # noqa: E402
    BEREICH_IMMER,
    BEREICH_NUR_LANDESEBENE,
    BEREICH_NUR_UNTERREGION,
    BUNDESLAENDER_AT,
    BUNDESLAENDER_DE,
    LAENDER,
    LAND_JE_REGION,
    REGION_DEUTSCHLAND,
    REGION_OESTERREICH,
    REGION_SCHWEIZ,
    REGIONEN,
    ist_landesebene,
    land_von_region,
    passt_zur_region,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Länder und Regionslisten
# ---------------------------------------------------------------------------


def test_drei_laender_mit_ihren_regionen():
    assert set(LAENDER) == {"de", "at", "ch"}
    assert len(BUNDESLAENDER_DE) == 16
    assert len(BUNDESLAENDER_AT) == 9
    # Schweiz bewusst ohne Kantone — siehe Begründung in const.py und den
    # Live-Test `test_die_kantonsseiten_fuehren_keinen_eigenen_preis`.
    assert LAENDER["ch"].unterregionen == {}
    assert len(REGIONEN) == 17 + 10 + 1


def test_jede_region_gehoert_zu_genau_einem_land():
    assert set(LAND_JE_REGION) == set(REGIONEN)
    assert land_von_region("bayern").code == "de"
    assert land_von_region("tirol").code == "at"
    assert land_von_region(REGION_SCHWEIZ).code == "ch"


def test_slugs_sind_ueber_alle_laender_eindeutig():
    """Der Slug ist zugleich die `unique_id` eines Eintrags.

    Käme derselbe Slug zweimal vor, ließe sich das zweite Land nicht
    einrichten — mit der Meldung „bereits konfiguriert", die auf etwas ganz
    anderes hindeutet. `const.py` lehnt das beim Import ab; hier steht die
    Zusicherung, dass die Bedingung überhaupt gilt.
    """
    alle = [slug for land in LAENDER.values() for slug in land.regionen]
    assert len(alle) == len(set(alle)), "Doppelter Regionsslug"


def test_unbekannte_region_wird_laut_abgelehnt():
    """Kein stiller Rückfall auf Deutschland.

    Ein Rückfall würde für eine unbekannte Region klaglos deutsche Preise
    anzeigen — in Euro, plausibel aussehend und falsch.
    """
    with pytest.raises(ValueError, match="Unbekannte Region"):
        land_von_region("kaernten-sued")


@pytest.mark.parametrize(
    "region", [REGION_DEUTSCHLAND, REGION_OESTERREICH, REGION_SCHWEIZ]
)
def test_landesebene_wird_erkannt(region):
    assert ist_landesebene(region) is True


@pytest.mark.parametrize("region", ["bayern", "tirol", "wien"])
def test_bundeslaender_sind_keine_landesebene(region):
    assert ist_landesebene(region) is False


# ---------------------------------------------------------------------------
# Slugs gegen die Quelle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "erwartet"),
    [
        ("deutschland.html", BUNDESLAENDER_DE),
        ("oesterreich.html", BUNDESLAENDER_AT),
    ],
    ids=["de", "at"],
)
def test_slugs_entsprechen_den_urls_der_quelle(fixture, erwartet):
    """Ein falscher Slug liefert stillschweigend die Landesseite.

    Deshalb werden die Slugs gegen die tatsächlich auf der Quellseite
    verlinkten Adressen geprüft und nicht gegen eine zweite Liste von mir.
    """
    html = (FIXTURES / fixture).read_text(encoding="utf-8", errors="replace")
    verlinkt = set(re.findall(r'/pelletpreise/([a-z-]+)"', html))
    assert verlinkt, f"In {fixture} wurden keine Regionslinks gefunden"
    assert set(erwartet) == verlinkt


def test_die_beiden_laenderlisten_ueberschneiden_sich_nicht():
    """Positivkontrolle zum Test darüber.

    Prüfte er beide Fixtures versehentlich gegen dieselbe Liste, wäre er
    trotzdem grün — die Listen müssen also nachweislich verschieden sein.
    """
    assert set(BUNDESLAENDER_DE).isdisjoint(BUNDESLAENDER_AT)


# ---------------------------------------------------------------------------
# Welcher Sensor entsteht wo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("region", sorted(REGIONEN))
def test_immer_gilt_ueberall(region):
    assert passt_zur_region(BEREICH_IMMER, region) is True


@pytest.mark.parametrize(
    ("region", "erwartet"),
    [
        ("bayern", True),
        ("tirol", True),
        (REGION_DEUTSCHLAND, False),
        (REGION_OESTERREICH, False),
        (REGION_SCHWEIZ, False),
    ],
)
def test_sackware_nur_fuer_bundeslaender(region, erwartet):
    assert passt_zur_region(BEREICH_NUR_UNTERREGION, region) is erwartet


@pytest.mark.parametrize(
    ("region", "erwartet"),
    [
        (REGION_DEUTSCHLAND, True),
        (REGION_OESTERREICH, True),
        (REGION_SCHWEIZ, True),
        ("bayern", False),
        ("wien", False),
    ],
)
def test_langfristwerte_nur_auf_landesebene(region, erwartet):
    assert passt_zur_region(BEREICH_NUR_LANDESEBENE, region) is erwartet


def test_die_schweiz_bekommt_keinen_sackware_sensor():
    """Folge der Entscheidung gegen die Kantone — ausdrücklich festgehalten.

    Sackware führt die Quelle nur auf Bundesland-Seiten. Weil es für die
    Schweiz keine gibt, kann dort auch kein Sackware-Sensor entstehen. Das ist
    kein Versehen, sondern die Kehrseite davon, keine Auflösung vorzutäuschen,
    die die Quelle nicht hat.
    """
    assert passt_zur_region(BEREICH_NUR_UNTERREGION, REGION_SCHWEIZ) is False


def test_unbekannter_bereich_ist_ein_fehler():
    """Kein stilles True/False bei einem Tippfehler im Bereichsnamen."""
    with pytest.raises(ValueError, match="Unbekannter Sensorbereich"):
        passt_zur_region("nur_montags", "bayern")


# ---------------------------------------------------------------------------
# Währung und Adressen
# ---------------------------------------------------------------------------


def test_jedes_land_kennt_seine_waehrung_und_seine_domain():
    assert LAENDER["de"].waehrung == "€"
    assert LAENDER["at"].waehrung == "€"
    assert LAENDER["ch"].waehrung == "CHF"
    assert LAENDER["de"].host == "www.heizpellets24.de"
    assert LAENDER["at"].basis_url == "https://www.heizpellets24.at/pelletpreise"
    assert LAENDER["ch"].attribution == "Daten von www.heizpellets24.ch"
