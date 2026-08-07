"""Tests für Regionsliste und Sensor-Zuordnung.

Diese Tests brauchen kein Home Assistant: `const.py` importiert bewusst nichts
aus dem Framework, damit genau diese Logik offline prüfbar bleibt.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pelletpreise.const import (  # noqa: E402
    BEREICH_IMMER,
    BEREICH_NUR_BUNDESLAND,
    BEREICH_NUR_DEUTSCHLAND,
    BUNDESLAENDER,
    REGION_DEUTSCHLAND,
    REGIONEN,
    passt_zur_region,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_alle_sechzehn_bundeslaender():
    assert len(BUNDESLAENDER) == 16
    assert REGION_DEUTSCHLAND not in BUNDESLAENDER
    assert len(REGIONEN) == 17


def test_slugs_entsprechen_den_urls_der_quelle():
    """Ein falscher Slug liefert stillschweigend die Deutschland-Seite.

    Deshalb werden die Slugs gegen die tatsächlich auf der Quellseite
    verlinkten Adressen geprüft und nicht gegen eine zweite Liste von mir.
    """
    import re

    html = (FIXTURES / "deutschland.html").read_text(encoding="utf-8", errors="replace")
    verlinkt = set(re.findall(r'/pelletpreise/([a-z-]+)"', html))
    assert verlinkt, "In der Fixture wurden keine Bundesland-Links gefunden"
    assert set(BUNDESLAENDER) == verlinkt


@pytest.mark.parametrize("region", [REGION_DEUTSCHLAND, *BUNDESLAENDER])
def test_immer_gilt_ueberall(region):
    assert passt_zur_region(BEREICH_IMMER, region) is True


def test_sackware_nur_fuer_bundeslaender():
    assert passt_zur_region(BEREICH_NUR_BUNDESLAND, "bayern") is True
    assert passt_zur_region(BEREICH_NUR_BUNDESLAND, REGION_DEUTSCHLAND) is False


def test_langfristwerte_nur_fuer_deutschland():
    assert passt_zur_region(BEREICH_NUR_DEUTSCHLAND, REGION_DEUTSCHLAND) is True
    assert passt_zur_region(BEREICH_NUR_DEUTSCHLAND, "bayern") is False


def test_unbekannter_bereich_ist_ein_fehler():
    """Kein stilles True/False bei einem Tippfehler im Bereichsnamen."""
    with pytest.raises(ValueError, match="Unbekannter Sensorbereich"):
        passt_zur_region("nur_montags", "bayern")
