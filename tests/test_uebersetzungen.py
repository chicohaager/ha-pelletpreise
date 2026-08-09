"""Prüft, dass jede Entität und jeder Dienst einen übersetzten Namen hat.

Fehlt eine Übersetzung, zeigt Home Assistant den rohen Schlüssel an —
„lose_tief_beobachtet" statt „Lose Ware Tiefstpreis (beobachtet)". Das ist der
klassische Fehler, den kein Test findet, weil nichts abstürzt: die Integration
läuft, der Sensor hat einen Wert, und nur die Beschriftung ist Kauderwelsch.
Genau deshalb steht die Prüfung hier.

Bewusst über den Syntaxbaum von ``sensor.py`` statt über einen Import: die
Datei zieht Home Assistant nach, und diese Suite soll ohne HA-Installation
laufen — dieselbe Bauweise wie in ``test_berechnung.py``.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import yaml

PAKET = Path(__file__).resolve().parents[1] / "custom_components" / "pelletpreise"
SENSOR_PY = PAKET / "sensor.py"
SPRACHDATEIEN = (
    PAKET / "strings.json",
    PAKET / "translations" / "de.json",
    PAKET / "translations" / "en.json",
)

BESCHREIBUNGSKLASSEN = (
    "PelletpreisSensorDescription",
    "PelletpreisExtremwertDescription",
)


def _sensorschluessel() -> dict[str, str | None]:
    """Alle Sensorschlüssel aus sensor.py samt ihrem translation_key."""
    baum = ast.parse(SENSOR_PY.read_text(encoding="utf-8"))
    gefunden: dict[str, str | None] = {}
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.Call):
            continue
        if getattr(knoten.func, "id", None) not in BESCHREIBUNGSKLASSEN:
            continue
        argumente = {
            kw.arg: kw.value.value
            for kw in knoten.keywords
            if isinstance(kw.value, ast.Constant)
        }
        schluessel = argumente.get("key")
        assert schluessel is not None, "Sensorbeschreibung ohne 'key' gefunden"
        gefunden[schluessel] = argumente.get("translation_key")
    return gefunden


def sprache(datei: Path) -> dict:
    return json.loads(datei.read_text(encoding="utf-8"))


def test_es_wurden_ueberhaupt_sensoren_gefunden():
    """Positivkontrolle: ohne sie wäre eine leere Menge klaglos „vollständig"."""
    schluessel = _sensorschluessel()
    assert len(schluessel) >= 20, f"Nur {len(schluessel)} Sensorbeschreibungen gelesen"


def test_jeder_sensor_hat_einen_translation_key():
    ohne = [k for k, t in _sensorschluessel().items() if t is None]
    assert not ohne, f"Sensoren ohne translation_key: {ohne}"


def test_translation_key_entspricht_dem_schluessel():
    """Sonst zeigt der Sensor die Beschriftung eines anderen."""
    abweichend = {k: t for k, t in _sensorschluessel().items() if t != k}
    assert not abweichend, f"key und translation_key weichen ab: {abweichend}"


@pytest.mark.parametrize("datei", SPRACHDATEIEN, ids=lambda p: p.name)
def test_jede_sprachdatei_kennt_genau_diese_sensoren(datei):
    erwartet = set(_sensorschluessel())
    vorhanden = set(sprache(datei)["entity"]["sensor"])
    assert vorhanden == erwartet, (
        f"{datei.name}: fehlend {sorted(erwartet - vorhanden)}, "
        f"überzählig {sorted(vorhanden - erwartet)}"
    )


@pytest.mark.parametrize("datei", SPRACHDATEIEN, ids=lambda p: p.name)
def test_kein_sensorname_ist_leer(datei):
    leer = [
        k for k, v in sprache(datei)["entity"]["sensor"].items() if not v.get("name")
    ]
    assert not leer, f"{datei.name}: Sensoren ohne Namen: {leer}"


def test_dienste_aus_services_yaml_sind_uebersetzt():
    dienste = set(yaml.safe_load((PAKET / "services.yaml").read_text(encoding="utf-8")))
    assert dienste, "services.yaml enthält keinen Dienst"
    for datei in SPRACHDATEIEN:
        beschrieben = set(sprache(datei).get("services", {}))
        assert beschrieben == dienste, (
            f"{datei.name}: Dienste weichen von services.yaml ab — "
            f"fehlend {sorted(dienste - beschrieben)}, "
            f"überzählig {sorted(beschrieben - dienste)}"
        )


def test_der_registrierte_dienstname_steht_auch_in_services_yaml():
    """Ein Dienst ohne Eintrag in services.yaml taucht in der Oberfläche nicht auf.

    Er ließe sich dann nur per YAML-Automation aufrufen — für einen Dienst,
    der ausdrücklich zum Zurücksetzen von Hand gedacht ist, wäre das nutzlos.
    """
    baum = ast.parse(SENSOR_PY.read_text(encoding="utf-8"))
    registriert = {
        knoten.value.value
        for knoten in ast.walk(baum)
        if isinstance(knoten, ast.Assign)
        and isinstance(knoten.value, ast.Constant)
        and isinstance(knoten.value.value, str)
        and any(
            getattr(ziel, "id", "").startswith("SERVICE_") for ziel in knoten.targets
        )
    }
    dienste = set(yaml.safe_load((PAKET / "services.yaml").read_text(encoding="utf-8")))
    assert registriert == dienste, (
        f"sensor.py kennt {sorted(registriert)}, services.yaml {sorted(dienste)}"
    )


@pytest.mark.parametrize("datei", SPRACHDATEIEN, ids=lambda p: p.name)
def test_jedes_optionsfeld_ist_beschriftet_und_erklaert(datei):
    """Auch die Erklärzeile zählt: sie nennt die zusätzlichen Abrufe."""
    schritt = sprache(datei)["options"]["step"]["init"]
    assert set(schritt["data"]) == set(schritt["data_description"])
    assert "bundesland_vergleich" in schritt["data"]
    assert schritt["data_description"]["bundesland_vergleich"].strip()


# ---------------------------------------------------------------------------
# Einrichtungsdialog
# ---------------------------------------------------------------------------


def _schluesselbaum(wert, pfad: str = "") -> set[str]:
    """Alle Pfade eines verschachtelten Objekts — die Form, nicht der Text."""
    if not isinstance(wert, dict):
        return {pfad}
    return {p for k, v in wert.items() for p in _schluesselbaum(v, f"{pfad}/{k}")}


def test_alle_sprachdateien_haben_dieselbe_form():
    """Ein vergessener Schritt in en.json zeigt dem Nutzer den rohen Schlüssel.

    Beim Umbau auf drei Länder kam ein zweiter Einrichtungsschritt dazu. Wäre
    er nur in strings.json und de.json gelandet, sähe eine englischsprachige
    Installation dort „region" statt einer Erklärung — und nichts stürzte ab.
    """
    formen = {datei.name: _schluesselbaum(sprache(datei)) for datei in SPRACHDATEIEN}
    vorlage = formen["strings.json"]
    for name, form in formen.items():
        assert form == vorlage, (
            f"{name}: fehlend {sorted(vorlage - form)}, "
            f"überzählig {sorted(form - vorlage)}"
        )


def test_die_schritte_der_sprachdateien_sind_die_des_dialogs():
    """Sonst zeigt Home Assistant für einen Schritt gar keine Beschriftung.

    Die Schritte werden aus `config_flow.py` gelesen (Methodennamen
    `async_step_*`) und nicht danebengeschrieben — eine zweite von Hand
    gepflegte Liste würde still veralten.
    """
    quelle = (PAKET / "config_flow.py").read_text(encoding="utf-8")
    baum = ast.parse(quelle)
    schritte = {
        knoten.name.removeprefix("async_step_")
        for klasse in ast.walk(baum)
        if isinstance(klasse, ast.ClassDef) and klasse.name.endswith("ConfigFlow")
        for knoten in klasse.body
        if isinstance(knoten, ast.AsyncFunctionDef)
        and knoten.name.startswith("async_step_")
    }
    assert schritte, "In config_flow.py wurde kein einziger Schritt gefunden"
    for datei in SPRACHDATEIEN:
        assert set(sprache(datei)["config"]["step"]) == schritte, (
            f"{datei.name}: Schritte weichen von config_flow.py ab "
            f"({sorted(schritte)})"
        )
