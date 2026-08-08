"""Sensoren der Pelletpreise-Integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTRIBUTION,
    BEREICH_IMMER,
    BEREICH_NUR_BUNDESLAND,
    BEREICH_NUR_DEUTSCHLAND,
    DOMAIN,
    passt_zur_region,
)
from .berechnung import euro
from .coordinator import PelletpreiseCoordinator, Preisdaten
from .parser import REFERENZMENGE_KG

if TYPE_CHECKING:
    from . import PelletpreiseConfigEntry

# Preise führt die Quelle als €/1.000 kg — das ist dasselbe wie €/t.
EURO_PRO_TONNE = "€/t"
EURO_PRO_KG = "€/kg"
EURO = "€"

# Bewusst **kein** device_class=MONETARY:
# Home Assistant lässt zu MONETARY nur `state_class: total` (oder gar keine)
# zu und verbucht den Wert als aufsummierbaren Betrag. Ein Marktpreis ist
# aber ein Messwert, kein Kontostand. Die Vorgängerversion hatte MONETARY mit
# `measurement` kombiniert; Home Assistant hat das bei jedem Start als Fehler
# protokolliert. Ohne device_class liefert `measurement` genau die richtige
# Langzeitstatistik (Mittel/Min/Max).


@dataclass(frozen=True, kw_only=True)
class PelletpreisSensorDescription(SensorEntityDescription):
    """Beschreibt einen Sensor samt Zugriff auf die Daten."""

    wert: Callable[[Preisdaten], float | None]
    """Liefert den Messwert — oder None, wenn die Quelle dazu nichts hergibt."""

    bereich: str = BEREICH_IMMER
    """Für welche Regionen dieser Sensor überhaupt Daten haben kann."""

    zusatzattribute: Callable[[Preisdaten], dict[str, Any]] | None = None


def _lose_gesamt_attribute(daten: Preisdaten) -> dict[str, Any]:
    """Zerlegt den Gesamtpreis der losen Ware in seine beiden Bestandteile.

    Der Warenwert steht hier getrennt neben der Pauschale, damit im Sensor
    nachvollziehbar bleibt, welcher Teil von heizpellets24.de gelesen und
    welcher selbst eingetragen wurde. Ohne diese Trennung wäre die eigene
    Zahl im Zustandswert nicht mehr von einem Marktwert zu unterscheiden.
    """
    return {
        "bestellmenge_kg": daten.menge_kg,
        "warenwert_eur": daten.warenwert(daten.lose),
        "einblaspauschale_eur": daten.einblaspauschale_eur,
        "berechnung": daten.berechnung(mit_einblaspauschale=True),
    }


def _sackware_gesamt_attribute(daten: Preisdaten) -> dict[str, Any]:
    """Wie oben, nur ohne Pauschale — mit Begründung, falls eine gesetzt ist.

    Sackware kommt auf Paletten und wird nicht eingeblasen. Wer eine Pauschale
    eingetragen hat und sie hier nicht wiederfindet, soll den Grund am Sensor
    lesen können und ihn nicht für einen Rechenfehler halten.
    """
    attribute: dict[str, Any] = {
        "bestellmenge_kg": daten.menge_kg,
        "einblaspauschale_eur": 0.0,
        "berechnung": daten.berechnung(mit_einblaspauschale=False),
    }
    if daten.einblaspauschale_eur:
        attribute["hinweis_einblaspauschale"] = (
            f"Die eingetragene Einblaspauschale von "
            f"{euro(daten.einblaspauschale_eur)} gilt hier nicht: Sackware "
            "wird auf Paletten geliefert und nicht eingeblasen."
        )
    return attribute


SENSOREN: tuple[PelletpreisSensorDescription, ...] = (
    # --- Lose Ware -------------------------------------------------------
    PelletpreisSensorDescription(
        key="lose_tonne",
        translation_key="lose_tonne",
        native_unit_of_measurement=EURO_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:tanker-truck",
        wert=lambda d: d.lose.euro_pro_tonne,
    ),
    PelletpreisSensorDescription(
        key="lose_kg",
        translation_key="lose_kg",
        native_unit_of_measurement=EURO_PRO_KG,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        icon="mdi:tanker-truck",
        wert=lambda d: round(d.lose.euro_pro_tonne / 1000, 4),
    ),
    PelletpreisSensorDescription(
        key="lose_gesamt",
        translation_key="lose_gesamt",
        native_unit_of_measurement=EURO,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:cash",
        # Einzige Stelle, an der eine selbst eingetragene Zahl in einen
        # Sensorwert einfließt. Die Attribute weisen sie getrennt aus.
        wert=lambda d: d.gesamtpreis(d.lose, mit_einblaspauschale=True),
        zusatzattribute=_lose_gesamt_attribute,
    ),
    PelletpreisSensorDescription(
        key="lose_aenderung_woche",
        translation_key="lose_aenderung_woche",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:swap-vertical",
        wert=lambda d: d.lose.aenderung_prozent_woche,
    ),
    # --- Sackware --------------------------------------------------------
    PelletpreisSensorDescription(
        key="sackware_tonne",
        translation_key="sackware_tonne",
        bereich=BEREICH_NUR_BUNDESLAND,
        native_unit_of_measurement=EURO_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:package-variant-closed",
        wert=lambda d: d.sackware.euro_pro_tonne if d.sackware else None,
    ),
    PelletpreisSensorDescription(
        key="sackware_kg",
        translation_key="sackware_kg",
        bereich=BEREICH_NUR_BUNDESLAND,
        native_unit_of_measurement=EURO_PRO_KG,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        icon="mdi:package-variant-closed",
        wert=lambda d: round(d.sackware.euro_pro_tonne / 1000, 4) if d.sackware else None,
    ),
    PelletpreisSensorDescription(
        key="sackware_gesamt",
        translation_key="sackware_gesamt",
        bereich=BEREICH_NUR_BUNDESLAND,
        native_unit_of_measurement=EURO,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:cash",
        wert=lambda d: (
            d.gesamtpreis(d.sackware, mit_einblaspauschale=False)
            if d.sackware
            else None
        ),
        zusatzattribute=_sackware_gesamt_attribute,
    ),
    PelletpreisSensorDescription(
        key="sackware_aenderung_woche",
        translation_key="sackware_aenderung_woche",
        bereich=BEREICH_NUR_BUNDESLAND,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:swap-vertical",
        wert=lambda d: d.sackware.aenderung_prozent_woche if d.sackware else None,
    ),
    # --- Langfristwerte, nur auf der Deutschland-Seite vorhanden ----------
    PelletpreisSensorDescription(
        key="tief_3jahre",
        translation_key="tief_3jahre",
        native_unit_of_measurement=EURO_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:arrow-down-bold",
        bereich=BEREICH_NUR_DEUTSCHLAND,
        wert=lambda d: d.langfrist.tief_3jahre if d.langfrist else None,
    ),
    PelletpreisSensorDescription(
        key="hoch_3jahre",
        translation_key="hoch_3jahre",
        native_unit_of_measurement=EURO_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:arrow-up-bold",
        bereich=BEREICH_NUR_DEUTSCHLAND,
        wert=lambda d: d.langfrist.hoch_3jahre if d.langfrist else None,
    ),
    PelletpreisSensorDescription(
        key="schnitt_3jahre",
        translation_key="schnitt_3jahre",
        native_unit_of_measurement=EURO_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:chart-line",
        bereich=BEREICH_NUR_DEUTSCHLAND,
        wert=lambda d: d.langfrist.schnitt_3jahre if d.langfrist else None,
    ),
    PelletpreisSensorDescription(
        key="differenz_3monate",
        translation_key="differenz_3monate",
        native_unit_of_measurement=EURO_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:calendar-range",
        bereich=BEREICH_NUR_DEUTSCHLAND,
        wert=lambda d: d.langfrist.differenz_3monate_euro if d.langfrist else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PelletpreiseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Lege die Sensoren für einen Konfigurationseintrag an."""
    coordinator: PelletpreiseCoordinator = entry.runtime_data
    async_add_entities(
        PelletpreisSensor(coordinator, entry, beschreibung)
        for beschreibung in SENSOREN
        if passt_zur_region(beschreibung.bereich, coordinator.region)
    )


class PelletpreisSensor(CoordinatorEntity[PelletpreiseCoordinator], SensorEntity):
    """Ein einzelner Preiswert."""

    entity_description: PelletpreisSensorDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: PelletpreiseCoordinator,
        entry: PelletpreiseConfigEntry,
        beschreibung: PelletpreisSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = beschreibung
        self._attr_unique_id = f"{entry.entry_id}_{beschreibung.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Pelletpreise {coordinator.region_name}",
            manufacturer="HeizPellets24",
            model="Marktpreis-Beobachtung",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=coordinator.url,
        )

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.wert(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Ein Wert, den die Quelle heute nicht führt, ist nicht verfügbar.

        Bewusst kein Ersatzwert: eine 0 oder ein alter Preis sähe aus wie eine
        Auskunft und wäre keine.
        """
        if not super().available or self.coordinator.data is None:
            return False
        return self.entity_description.wert(self.coordinator.data) is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        daten = self.coordinator.data
        if daten is None:
            return {}
        attribute: dict[str, Any] = {
            "region": daten.region_name,
            "quelle": self.coordinator.url,
            "basis_kg": REFERENZMENGE_KG,
        }
        if self.entity_description.zusatzattribute is not None:
            attribute.update(self.entity_description.zusatzattribute(daten))
        return attribute
