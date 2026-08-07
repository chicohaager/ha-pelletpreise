"""Pelletpreise — Marktpreise für Holzpellets in Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_MENGE, CONF_REGION, REGION_DEUTSCHLAND
from .coordinator import PelletpreiseCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

type PelletpreiseConfigEntry = ConfigEntry[PelletpreiseCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: PelletpreiseConfigEntry) -> bool:
    """Richte einen Konfigurationseintrag ein."""
    coordinator = PelletpreiseCoordinator(
        hass, entry, async_get_clientsession(hass)
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Ohne diesen Listener bliebe eine geänderte Bestellmenge bis zum nächsten
    # Neustart wirkungslos — der Options-Dialog würde "gespeichert" melden und
    # nichts bewirken.
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PelletpreiseConfigEntry) -> bool:
    """Entlade einen Konfigurationseintrag."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: PelletpreiseConfigEntry) -> None:
    """Lade den Eintrag neu, wenn die Optionen geändert wurden."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Hebe Einträge älterer Versionen auf das aktuelle Schema.

    Version 1 speicherte eine Postleitzahl. Die hatte allerdings **keine**
    Wirkung: die damalige Fassung rief ausschließlich die Deutschland-Seite ab
    und zeigte damit für jede PLZ denselben Bundesdurchschnitt. Der Eintrag
    wird deshalb auf die Region "Deutschland" gehoben — das entspricht genau
    dem, was bisher tatsächlich angezeigt wurde.

    Eine PLZ hier auf ein Bundesland abzubilden wäre eine stille Änderung der
    Bedeutung; die Regionswahl trifft besser der Nutzer selbst.
    """
    if entry.version >= 2:
        return True

    # Die Entitäten der Version 1 hatten andere unique_ids. Ohne dieses
    # Aufräumen bleiben sie für immer als "nicht verfügbar" im Register
    # stehen — sichtbar in der Oberfläche, ohne je wieder einen Wert zu
    # bekommen.
    register = er.async_get(hass)
    altes_praefix = f"{entry.entry_id}_pelletpreis_"
    entfernt = 0
    for eintrag in list(er.async_entries_for_config_entry(register, entry.entry_id)):
        if eintrag.unique_id.startswith(altes_praefix):
            register.async_remove(eintrag.entity_id)
            entfernt += 1
    if entfernt:
        _LOGGER.info("Pelletpreise: %s Entitäten der Vorversion entfernt", entfernt)

    daten = dict(entry.data)
    alte_plz = daten.pop("plz", None)
    daten.pop("schlauchlaenge", None)  # wurde nie ausgewertet
    daten[CONF_REGION] = REGION_DEUTSCHLAND
    optionen = {CONF_MENGE: daten.pop(CONF_MENGE, 6000)}

    _LOGGER.warning(
        "Pelletpreise: Eintrag von Version 1 übernommen. Die bisherige "
        "Postleitzahl %s war ohne Wirkung — es wurde immer der "
        "Bundesdurchschnitt angezeigt. Der Eintrag steht nun auf "
        "'Deutschland'. Für einen Regionalpreis bitte unter Geräte & Dienste "
        "das Bundesland auswählen. Die Entitäts-IDs haben sich geändert.",
        alte_plz,
    )

    hass.config_entries.async_update_entry(
        entry,
        data=daten,
        options=optionen,
        title="Pelletpreise Deutschland",
        unique_id=REGION_DEUTSCHLAND,
        version=2,
    )
    return True
