"""Tests mit laufendem Home Assistant — was die anderen Tests nicht sehen.

Die übrige Suite prüft Logik ohne Framework: Parser, Hochrechnung,
Fortschreibung, Vergleich. Damit ist genau das **nicht** geprüft, was zwischen
dieser Logik und dem Nutzer liegt — ob die Entitäten überhaupt entstehen, ob
der Rekord einen Neustart übersteht, ob der Dienst greift, ob bei einem
Fehlschlag wirklich kein Wert erscheint. Genau dort sitzen die Fehler, die man
im Protokoll nicht sieht und in der Oberfläche für „geht halt nicht" hält.

Läuft nur mit ``pytest-homeassistant-custom-component`` (braucht Python 3.13,
weil Home Assistant ab 2025.2 nichts Älteres mehr unterstützt). Fehlt das
Paket, überspringt sich diese Datei — die Grundsuite bleibt ohne schwere
Abhängigkeit lauffähig::

    pip install pytest-homeassistant-custom-component
    python -m pytest tests/test_sensoren_ha.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="Braucht pytest-homeassistant-custom-component (Python 3.13+)",
)

from homeassistant.const import STATE_UNAVAILABLE  # noqa: E402
from homeassistant.core import HomeAssistant, State  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from pytest_homeassistant_custom_component.common import (  # noqa: E402
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

from custom_components.pelletpreise.const import (  # noqa: E402
    BUNDESLAENDER,
    CONF_BUNDESLAND_VERGLEICH,
    CONF_MENGE,
    CONF_REGION,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASIS_URL = "https://www.heizpellets24.de/pelletpreise"

# Die Zahlen der Fixtures vom 07.08.2026, gegen die auch test_parser.py prüft.
BAYERN_LOSE = 400.38
BAYERN_SACKWARE = 477.86
BW_LOSE = 414.22


def lies(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


@pytest.fixture(autouse=True)
def _custom_integrations(enable_custom_integrations):
    """Ohne diese Freigabe lädt Home Assistant custom_components/ gar nicht."""
    return


def eintrag(region: str, **optionen) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=region,
        title=f"Pelletpreise {region}",
        data={CONF_REGION: region},
        options={CONF_MENGE: 6000, **optionen},
    )


async def einrichten(hass: HomeAssistant, eintrag: MockConfigEntry) -> None:
    eintrag.add_to_hass(hass)
    assert await hass.config_entries.async_setup(eintrag.entry_id)
    await hass.async_block_till_done()


def entitaet(hass: HomeAssistant, schluessel: str) -> str:
    """Die Entitäts-ID zu einem Sensorschlüssel aus sensor.py.

    Bewusst über die unique_id des Entitätsregisters und **nicht** über die
    Entitäts-ID: die entsteht aus dem übersetzten Namen und lautet in einer
    englischsprachigen Testinstanz anders als in einer deutschen
    Installation. Ein Test, der auf „tiefstpreis" wartet, würde dort grün und
    hier rot — geprüft würde die Sprache, nicht die Funktion.
    """
    register = er.async_get(hass)
    treffer = [
        eintrag.entity_id
        for eintrag in register.entities.values()
        if eintrag.platform == DOMAIN and eintrag.unique_id.endswith(f"_{schluessel}")
    ]
    assert len(treffer) == 1, f"{schluessel}: {treffer}"
    return treffer[0]


def schluessel_im_register(hass: HomeAssistant, eintr: MockConfigEntry) -> set[str]:
    """Welche Sensorschlüssel wurden für diesen Eintrag wirklich angelegt?

    Ebenfalls über die unique_id: eine Prüfung auf „sackware" oder
    „bundesland" **in der Entitäts-ID** wäre in der englischsprachigen
    Testinstanz immer leer — sie hieße dort „bagged" und „state". Eine solche
    Zusicherung kann gar nicht anschlagen und meldet trotzdem Erfolg.
    """
    register = er.async_get(hass)
    return {
        eintragung.unique_id.removeprefix(f"{eintr.entry_id}_")
        for eintragung in register.entities.values()
        if eintragung.platform == DOMAIN
    }


def zustand(hass: HomeAssistant, schluessel: str) -> State:
    wert = hass.states.get(entitaet(hass, schluessel))
    assert wert is not None, f"{schluessel}: kein Zustand"
    return wert


# ---------------------------------------------------------------------------
# Beobachtete Extremwerte
# ---------------------------------------------------------------------------


async def test_extremwerte_entstehen_und_starten_beim_ersten_preis(
    hass: HomeAssistant, aioclient_mock
):
    aioclient_mock.get(f"{BASIS_URL}/bayern", text=lies("bayern.html"))
    await einrichten(hass, eintrag("bayern"))

    tief = zustand(hass, "lose_tief_beobachtet")
    hoch = zustand(hass, "lose_hoch_beobachtet")
    assert float(tief.state) == BAYERN_LOSE
    assert float(hoch.state) == BAYERN_LOSE
    assert tief.attributes["beobachtet_seit"] == tief.attributes["gesehen_am"]
    # Die Herkunft muss am Wert kleben, nicht nur im Quelltext stehen.
    assert "heizpellets24.de" in tief.attributes["hinweis"]

    # Und sie muss zum Wert passen: der Rekord ist keine Angabe der Quelle,
    # also darf an ihm nicht dieselbe Quellenangabe hängen wie am Tagespreis.
    # Genau das stand am 08.08.2026 in der laufenden Installation — „Daten von
    # heizpellets24.de" direkt neben dem Hinweis „Keine Angabe von
    # heizpellets24.de".
    tagespreis = zustand(hass, "lose_tonne")
    assert tief.attributes["attribution"] != tagespreis.attributes["attribution"]
    assert "Aufzeichnung" in tief.attributes["attribution"]
    assert "heizpellets24.de" in tief.attributes["attribution"]


async def test_sackware_bekommt_eigene_extremwerte(
    hass: HomeAssistant, aioclient_mock
):
    aioclient_mock.get(f"{BASIS_URL}/bayern", text=lies("bayern.html"))
    await einrichten(hass, eintrag("bayern"))

    assert float(zustand(hass, "sackware_tief_beobachtet").state) == (
        BAYERN_SACKWARE
    )
    assert float(zustand(hass, "sackware_hoch_beobachtet").state) == (
        BAYERN_SACKWARE
    )


async def test_deutschland_hat_keine_sackware_extremwerte(
    hass: HomeAssistant, aioclient_mock
):
    """Entitäten, die nie einen Wert bekommen können, dürfen nicht entstehen."""
    aioclient_mock.get(BASIS_URL, text=lies("deutschland.html"))
    eintr = eintrag("deutschland")
    await einrichten(hass, eintr)

    schluessel = schluessel_im_register(hass, eintr)
    assert schluessel, "Für Deutschland wurde überhaupt keine Entität angelegt"
    assert not [s for s in schluessel if "sackware" in s], sorted(schluessel)

    # Positivkontrolle in derselben Instanz: im Bundesland-Eintrag entstehen
    # die Sackware-Sensoren sehr wohl. Ohne sie wäre oben nicht zu
    # unterscheiden, ob die Suche richtig liegt oder nur nichts findet.
    aioclient_mock.get(f"{BASIS_URL}/bayern", text=lies("bayern.html"))
    bayern = eintrag("bayern")
    await einrichten(hass, bayern)
    assert "sackware_tief_beobachtet" in schluessel_im_register(hass, bayern)


async def test_ein_neuer_tiefstpreis_wird_uebernommen_der_hoechstwert_nicht(
    hass: HomeAssistant, aioclient_mock
):
    """Der eigentliche Zweck dieser Sensoren, an laufender Maschine geprüft."""
    aioclient_mock.get(f"{BASIS_URL}/bayern", text=lies("bayern.html"))
    eintr = eintrag("bayern")
    await einrichten(hass, eintr)

    # Zweiter Abruf mit einem billigeren Preis (Fixture eines anderen Landes
    # wäre teurer — deshalb hier bewusst der günstigere Weg über den Parser
    # der Bayern-Seite mit ausgetauschtem Preis).
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{BASIS_URL}/bayern",
        text=lies("bayern.html").replace(str(BAYERN_LOSE), "333.33"),
    )
    await hass.config_entries.async_reload(eintr.entry_id)
    await hass.async_block_till_done()

    assert float(zustand(hass, "lose_tief_beobachtet").state) == 333.33
    assert float(zustand(hass, "lose_hoch_beobachtet").state) == BAYERN_LOSE


async def _neustart_mit_gespeichertem_wert(
    hass: HomeAssistant, aioclient_mock, gespeichert: dict
) -> MockConfigEntry:
    """Richte ein, lerne die Entitäts-ID, entlade, säe den Speicher, starte neu.

    Die Entitäts-ID lässt sich nicht vorher hinschreiben: Home Assistant bildet
    sie aus dem **übersetzten** Namen, und die Testinstanz läuft auf Englisch.
    Eine geratene ID träfe ins Leere, der Speicher bliebe ungelesen — und der
    Test wäre grün, weil der Sensor „richtigerweise" beim heutigen Preis
    steht. Deshalb wird sie hier erst gemessen und dann benutzt.
    """
    aioclient_mock.get(f"{BASIS_URL}/bayern", text=lies("bayern.html"))
    eintr = eintrag("bayern")
    await einrichten(hass, eintr)
    tief_id = entitaet(hass, "lose_tief_beobachtet")

    assert await hass.config_entries.async_unload(eintr.entry_id)
    await hass.async_block_till_done()

    mock_restore_cache_with_extra_data(
        hass, ((State(tief_id, STATE_UNAVAILABLE), gespeichert),)
    )
    assert await hass.config_entries.async_setup(eintr.entry_id)
    await hass.async_block_till_done()
    return eintr


async def test_der_rekord_uebersteht_einen_neustart(hass: HomeAssistant, aioclient_mock):
    """Gegenprobe gegen einen Rekord, der beim Neustart auf heute zurückfällt.

    Wiederhergestellt wird aus den **Zusatzdaten**, nicht aus dem letzten
    Zustand: der steht hier bewusst auf „unavailable", wie nach einem Neustart
    während einer Störung der Quelle. Aus dem Zustand gelesen wäre die
    Aufzeichnung dann weg.
    """
    await _neustart_mit_gespeichertem_wert(
        hass,
        aioclient_mock,
        {
            "euro_pro_tonne": 242.92,
            "gesehen_am": "2024-08-25T12:00:00+02:00",
            "beobachtet_seit": "2024-01-01T12:00:00+01:00",
        },
    )

    tief = zustand(hass, "lose_tief_beobachtet")
    assert float(tief.state) == 242.92, "Der gespeicherte Rekord wurde nicht übernommen"
    assert tief.attributes["beobachtet_seit"].startswith("2024-01-01")
    assert tief.attributes["gesehen_am"].startswith("2024-08-25")
    # Der Höchstwert hatte nichts gespeichert und beginnt beim heutigen Preis.
    assert float(zustand(hass, "lose_hoch_beobachtet").state) == BAYERN_LOSE


async def test_unbrauchbarer_gespeicherter_wert_beginnt_neu_statt_zu_luegen(
    hass: HomeAssistant, aioclient_mock, caplog
):
    """Ein stiller Ersatzwert sähe im Sensor aus wie ein echter Rekord."""
    await _neustart_mit_gespeichertem_wert(
        hass,
        aioclient_mock,
        {"euro_pro_tonne": 42.0, "gesehen_am": "vorgestern", "beobachtet_seit": "?"},
    )

    assert float(zustand(hass, "lose_tief_beobachtet").state) == BAYERN_LOSE
    assert "unbrauchbar" in caplog.text, "Der Verlust muss im Protokoll stehen"


async def test_dienst_setzt_zurueck_und_lehnt_fremde_sensoren_ab(
    hass: HomeAssistant, aioclient_mock
):
    from homeassistant.exceptions import ServiceValidationError

    # Erst der günstigere Tag, dann der teurere: so unterscheidet sich der
    # Rekord vom aktuellen Preis — sonst könnte das Zurücksetzen nichts
    # bewirken und der Test wäre trotzdem grün.
    aioclient_mock.get(
        f"{BASIS_URL}/bayern",
        text=lies("bayern.html").replace(str(BAYERN_LOSE), "333.33"),
    )
    eintr = eintrag("bayern")
    await einrichten(hass, eintr)
    assert float(zustand(hass, "lose_tief_beobachtet").state) == 333.33

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASIS_URL}/bayern", text=lies("bayern.html"))
    await hass.config_entries.async_reload(eintr.entry_id)
    await hass.async_block_till_done()

    tief_id = entitaet(hass, "lose_tief_beobachtet")
    assert float(hass.states.get(tief_id).state) == 333.33, (
        "Der Rekord darf beim teureren Tag nicht mitwandern"
    )

    await hass.services.async_call(
        DOMAIN, "extremwerte_zuruecksetzen", {"entity_id": tief_id}, blocking=True
    )
    await hass.async_block_till_done()
    neu = hass.states.get(tief_id)
    assert float(neu.state) == BAYERN_LOSE
    assert neu.attributes["beobachtet_seit"] == neu.attributes["gesehen_am"]

    # Auf einem gewöhnlichen Preissensor muss der Dienst eine Erklärung
    # liefern statt eines AttributeError im Protokoll.
    with pytest.raises(ServiceValidationError, match="beobachtet"):
        await hass.services.async_call(
            DOMAIN,
            "extremwerte_zuruecksetzen",
            {"entity_id": entitaet(hass, "lose_tonne")},
            blocking=True,
        )


# ---------------------------------------------------------------------------
# Bundesland-Vergleich
# ---------------------------------------------------------------------------


def _alle_bundeslaender_mocken(aioclient_mock, teuerstes: str = "hamburg") -> None:
    """15 Länder auf dem Bayern-Preis, eines auf dem teureren BW-Preis."""
    for slug in BUNDESLAENDER:
        aioclient_mock.get(
            f"{BASIS_URL}/{slug}",
            text=lies(
                "baden-wuerttemberg.html" if slug == teuerstes else "bayern.html"
            ),
        )


async def test_ohne_schalter_entstehen_keine_vergleichssensoren(
    hass: HomeAssistant, aioclient_mock
):
    """Sonst stünden dauerhaft „nicht verfügbar"-Entitäten in der Oberfläche."""
    aioclient_mock.get(BASIS_URL, text=lies("deutschland.html"))
    eintr = eintrag("deutschland")
    await einrichten(hass, eintr)

    schluessel = schluessel_im_register(hass, eintr)
    assert schluessel, "Für Deutschland wurde überhaupt keine Entität angelegt"
    assert not [s for s in schluessel if "bundesland" in s], sorted(schluessel)
    # Gegenprobe: es wurde wirklich nur die eine Seite geholt.
    assert len(aioclient_mock.mock_calls) == 1


async def test_vergleich_liefert_guenstigstes_und_teuerstes_bundesland(
    hass: HomeAssistant, aioclient_mock
):
    aioclient_mock.get(BASIS_URL, text=lies("deutschland.html"))
    _alle_bundeslaender_mocken(aioclient_mock)
    await einrichten(hass, eintrag("deutschland", **{CONF_BUNDESLAND_VERGLEICH: True}))

    teuer = zustand(hass, "teuerstes_bundesland_lose")
    assert float(teuer.state) == BW_LOSE
    assert teuer.attributes["bundesland"] == "Hamburg"
    assert teuer.attributes["verglichene_bundeslaender"] == 16

    guenstig = zustand(hass, "guenstigstes_bundesland_lose")
    assert float(guenstig.state) == BAYERN_LOSE
    # 15 Länder liegen gleichauf — das darf der Sensor nicht verschweigen.
    assert len(guenstig.attributes["gleichauf"]) == 14
    assert guenstig.attributes["spanne_eur_pro_tonne"] == round(
        BW_LOSE - BAYERN_LOSE, 2
    )

    # 1 Deutschland-Seite + 16 Bundesländer
    assert len(aioclient_mock.mock_calls) == 17


async def test_ein_fehlschlag_laesst_den_vergleich_leer_aber_den_preis_stehen(
    hass: HomeAssistant, aioclient_mock, caplog
):
    """Kein Vergleich über 15 Länder — der fehlende könnte der günstigste sein."""
    aioclient_mock.get(BASIS_URL, text=lies("deutschland.html"))
    _alle_bundeslaender_mocken(aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get(BASIS_URL, text=lies("deutschland.html"))
    for slug in BUNDESLAENDER:
        if slug == "saarland":
            aioclient_mock.get(f"{BASIS_URL}/{slug}", status=503)
        else:
            aioclient_mock.get(f"{BASIS_URL}/{slug}", text=lies("bayern.html"))

    await einrichten(hass, eintrag("deutschland", **{CONF_BUNDESLAND_VERGLEICH: True}))

    assert zustand(hass, "guenstigstes_bundesland_lose").state == STATE_UNAVAILABLE
    assert zustand(hass, "teuerstes_bundesland_lose").state == STATE_UNAVAILABLE
    # Der Hauptzweck des Eintrags steht trotzdem.
    assert float(zustand(hass, "lose_tonne").state) > 0
    assert "Saarland" in caplog.text, "Das gescheiterte Land muss im Protokoll stehen"
