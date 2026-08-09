"""Sensoren der Pelletpreise-Integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    BEREICH_IMMER,
    BEREICH_NUR_LANDESEBENE,
    BEREICH_NUR_UNTERREGION,
    DOMAIN,
    Land,
    attribution,
    attribution_beobachtet,
    passt_zur_region,
)
from .berechnung import betrag_text
from .coordinator import PelletpreiseCoordinator, Preisdaten
from .extremwerte import (
    MODUS_HOCH,
    MODUS_TIEF,
    Extremwert,
    aus_speicher,
    fortschreiben,
    fuer_speicher,
)
from .parser import REFERENZMENGE_KG
from .vergleich import Vergleich

if TYPE_CHECKING:
    from . import PelletpreiseConfigEntry

_LOGGER = logging.getLogger(__name__)

SERVICE_EXTREMWERTE_ZURUECKSETZEN = "extremwerte_zuruecksetzen"

# Preise führt die Quelle als Währung/1.000 kg — das ist dasselbe wie /t.
#
# Die Währung steht hier als Platzhalter und nicht als Zeichen: sie hängt am
# Land (Schweiz: CHF) und wird aus der Seite gelesen, nicht angenommen. Die
# Beschreibungen sind eingefrorene Dataclasses und gelten für alle Einträge
# gemeinsam — die fertige Einheit entsteht deshalb erst je Entität, in
# `PelletpreisBasisSensor.__init__`.
PLATZHALTER_WAEHRUNG = "{waehrung}"
PREIS_PRO_TONNE = "{waehrung}/t"
PREIS_PRO_KG = "{waehrung}/kg"
BETRAG = "{waehrung}"


def _einheit(vorlage: str | None, waehrung: str) -> str | None:
    """Setze die Währung in eine Einheiten-Vorlage ein.

    Einheiten ohne Platzhalter (PERCENTAGE) bleiben unverändert — sie sind
    währungsfrei und deshalb in jedem Land richtig.

    Der Test ``test_keine_einheit_traegt_noch_einen_platzhalter`` prüft, dass
    hinterher nirgends mehr eine geschweifte Klammer steht: eine vergessene
    Ersetzung sähe im Dashboard als „{waehrung}/t" zwar auffällig aus, würde
    aber erst dem Nutzer auffallen und nicht hier.
    """
    if vorlage is None:
        return None
    if PLATZHALTER_WAEHRUNG not in vorlage:
        return vorlage
    return vorlage.format(waehrung=waehrung)


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

    nur_mit_vergleich: bool = False
    """Entsteht nur, wenn der Bundesland-Vergleich eingeschaltet ist.

    Ohne den Schalter würden diese Entitäten für immer „nicht verfügbar"
    anzeigen — sichtbar, unerklärlich und ohne jede Aussicht auf einen Wert.
    """


@dataclass(frozen=True, kw_only=True)
class PelletpreisExtremwertDescription(SensorEntityDescription):
    """Beschreibt einen selbst aufgezeichneten Tief- oder Höchstwert.

    Getrennt von der Beschreibung oben, weil der Zustand hier eine andere
    Herkunft hat: ``beobachtet`` liefert nicht den Sensorwert, sondern den
    **aktuellen** Preis, aus dem der Rekord fortgeschrieben wird. Eine
    gemeinsame Beschreibung hätte dasselbe Feld für zwei verschiedene Dinge
    benutzt.
    """

    beobachtet: Callable[[Preisdaten], float | None]
    modus: str
    bereich: str = BEREICH_IMMER


def _lose_gesamt_attribute(daten: Preisdaten) -> dict[str, Any]:
    """Zerlegt den Gesamtpreis der losen Ware in seine beiden Bestandteile.

    Der Warenwert steht hier getrennt neben der Pauschale, damit im Sensor
    nachvollziehbar bleibt, welcher Teil von heizpellets24.de gelesen und
    welcher selbst eingetragen wurde. Ohne diese Trennung wäre die eigene
    Zahl im Zustandswert nicht mehr von einem Marktwert zu unterscheiden.
    """
    return {
        "bestellmenge_kg": daten.menge_kg,
        "warenwert": daten.warenwert(daten.lose),
        "einblaspauschale": daten.einblaspauschale,
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
        "einblaspauschale": 0.0,
        "berechnung": daten.berechnung(mit_einblaspauschale=False),
    }
    if daten.einblaspauschale:
        attribute["hinweis_einblaspauschale"] = (
            f"Die eingetragene Einblaspauschale von "
            f"{betrag_text(daten.einblaspauschale, daten.waehrung)} gilt hier "
            "nicht: Sackware wird auf Paletten geliefert und nicht eingeblasen."
        )
    return attribute


def _vergleich_attribute(
    daten: Preisdaten, vergleich: Vergleich | None, *, guenstigste: bool
) -> dict[str, Any]:
    """Sagt, **welches** Bundesland der Wert ist — und was daneben lag.

    Der Zustand ist der Preis, damit er sich zeichnen lässt; ohne den Namen
    daneben wäre er allerdings nicht deutbar. Gleichstand und fehlende
    Angebote stehen ebenfalls hier: „günstigstes Bundesland" darf nicht so
    aussehen, als wäre es ein eindeutiger Einzelfall, wenn es keiner ist.
    """
    if vergleich is None:
        return {}
    rang = vergleich.guenstigste if guenstigste else vergleich.teuerste
    gleichauf = (
        vergleich.gleichauf_guenstigste if guenstigste else vergleich.gleichauf_teuerste
    )
    anzahl = len(daten.land.unterregionen)
    attribute: dict[str, Any] = {
        "bundesland": rang.name,
        "verglichene_bundeslaender": len(vergleich.preise),
        "spanne_pro_tonne": vergleich.spanne,
        "preise_je_bundesland": vergleich.preise,
        "hinweis": (
            f"Vergleich der {anzahl} Bundesland-Seiten von {daten.land.host}. "
            f"Der Landesdurchschnitt der {daten.land.name}-Seite bildet die "
            "Quelle nach eigener Angabe je Postleitzahl und nicht aus diesen "
            f"{anzahl} Werten — beide Zahlen liegen nah beieinander, sind aber "
            "nicht dasselbe."
        ),
    }
    if gleichauf:
        attribute["gleichauf"] = list(gleichauf)
    if vergleich.ohne_angebot:
        attribute["ohne_angebot"] = list(vergleich.ohne_angebot)
    return attribute


def _extremwert_hinweis(modus: str, land: Land) -> str:
    """Der Satz, der diesen Wert von einem Wert der Quelle unterscheidet."""
    richtung = "niedrigste" if modus == MODUS_TIEF else "höchste"
    return (
        f"Der {richtung} Preis, den diese Integration selbst gesehen hat. "
        f"Keine Angabe von {land.host}: die Quelle nennt Tief- und Höchstwerte "
        f"nur auf der {land.name}-Seite und nur über drei Jahre. Der Wert "
        "reicht deshalb nicht weiter zurück als 'beobachtet_seit'."
    )


SENSOREN: tuple[PelletpreisSensorDescription, ...] = (
    # --- Lose Ware -------------------------------------------------------
    PelletpreisSensorDescription(
        key="lose_tonne",
        translation_key="lose_tonne",
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:tanker-truck",
        wert=lambda d: d.lose.preis_pro_tonne,
    ),
    PelletpreisSensorDescription(
        key="lose_kg",
        translation_key="lose_kg",
        native_unit_of_measurement=PREIS_PRO_KG,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        icon="mdi:tanker-truck",
        wert=lambda d: round(d.lose.preis_pro_tonne / 1000, 4),
    ),
    PelletpreisSensorDescription(
        key="lose_gesamt",
        translation_key="lose_gesamt",
        native_unit_of_measurement=BETRAG,
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
        bereich=BEREICH_NUR_UNTERREGION,
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:package-variant-closed",
        wert=lambda d: d.sackware.preis_pro_tonne if d.sackware else None,
    ),
    PelletpreisSensorDescription(
        key="sackware_kg",
        translation_key="sackware_kg",
        bereich=BEREICH_NUR_UNTERREGION,
        native_unit_of_measurement=PREIS_PRO_KG,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        icon="mdi:package-variant-closed",
        wert=lambda d: round(d.sackware.preis_pro_tonne / 1000, 4) if d.sackware else None,
    ),
    PelletpreisSensorDescription(
        key="sackware_gesamt",
        translation_key="sackware_gesamt",
        bereich=BEREICH_NUR_UNTERREGION,
        native_unit_of_measurement=BETRAG,
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
        bereich=BEREICH_NUR_UNTERREGION,
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
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:arrow-down-bold",
        bereich=BEREICH_NUR_LANDESEBENE,
        wert=lambda d: d.langfrist.tief_3jahre if d.langfrist else None,
    ),
    PelletpreisSensorDescription(
        key="hoch_3jahre",
        translation_key="hoch_3jahre",
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:arrow-up-bold",
        bereich=BEREICH_NUR_LANDESEBENE,
        wert=lambda d: d.langfrist.hoch_3jahre if d.langfrist else None,
    ),
    PelletpreisSensorDescription(
        key="schnitt_3jahre",
        translation_key="schnitt_3jahre",
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:chart-line",
        bereich=BEREICH_NUR_LANDESEBENE,
        wert=lambda d: d.langfrist.schnitt_3jahre if d.langfrist else None,
    ),
    PelletpreisSensorDescription(
        key="differenz_3monate",
        translation_key="differenz_3monate",
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:calendar-range",
        bereich=BEREICH_NUR_LANDESEBENE,
        wert=lambda d: d.langfrist.differenz_3monate if d.langfrist else None,
    ),
    # --- Bundesland-Vergleich, nur auf Wunsch (16 zusätzliche Abrufe) -----
    PelletpreisSensorDescription(
        key="guenstigstes_bundesland_lose",
        translation_key="guenstigstes_bundesland_lose",
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:map-marker-down",
        bereich=BEREICH_NUR_LANDESEBENE,
        nur_mit_vergleich=True,
        wert=lambda d: (
            d.vergleich_lose.guenstigste.preis_pro_tonne if d.vergleich_lose else None
        ),
        zusatzattribute=lambda d: _vergleich_attribute(
            d, d.vergleich_lose, guenstigste=True
        ),
    ),
    PelletpreisSensorDescription(
        key="teuerstes_bundesland_lose",
        translation_key="teuerstes_bundesland_lose",
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:map-marker-up",
        bereich=BEREICH_NUR_LANDESEBENE,
        nur_mit_vergleich=True,
        wert=lambda d: (
            d.vergleich_lose.teuerste.preis_pro_tonne if d.vergleich_lose else None
        ),
        zusatzattribute=lambda d: _vergleich_attribute(
            d, d.vergleich_lose, guenstigste=False
        ),
    ),
    PelletpreisSensorDescription(
        key="guenstigstes_bundesland_sackware",
        translation_key="guenstigstes_bundesland_sackware",
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:map-marker-down",
        bereich=BEREICH_NUR_LANDESEBENE,
        nur_mit_vergleich=True,
        wert=lambda d: (
            d.vergleich_sackware.guenstigste.preis_pro_tonne
            if d.vergleich_sackware
            else None
        ),
        zusatzattribute=lambda d: _vergleich_attribute(
            d, d.vergleich_sackware, guenstigste=True
        ),
    ),
    PelletpreisSensorDescription(
        key="teuerstes_bundesland_sackware",
        translation_key="teuerstes_bundesland_sackware",
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:map-marker-up",
        bereich=BEREICH_NUR_LANDESEBENE,
        nur_mit_vergleich=True,
        wert=lambda d: (
            d.vergleich_sackware.teuerste.preis_pro_tonne
            if d.vergleich_sackware
            else None
        ),
        zusatzattribute=lambda d: _vergleich_attribute(
            d, d.vergleich_sackware, guenstigste=False
        ),
    ),
)


# Selbst aufgezeichnete Extremwerte. Sie kosten keinen zusätzlichen Abruf —
# sie sehen nur zu, was ohnehin geholt wird.
#
# `state_class` bleibt MEASUREMENT wie bei allen anderen Preissensoren: der
# Rekord ist der aktuelle Stand einer laufenden Beobachtung und soll sich
# genauso zeichnen lassen wie der Tagespreis.
EXTREMWERT_SENSOREN: tuple[PelletpreisExtremwertDescription, ...] = (
    PelletpreisExtremwertDescription(
        key="lose_tief_beobachtet",
        translation_key="lose_tief_beobachtet",
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:trending-down",
        modus=MODUS_TIEF,
        beobachtet=lambda d: d.lose.preis_pro_tonne,
    ),
    PelletpreisExtremwertDescription(
        key="lose_hoch_beobachtet",
        translation_key="lose_hoch_beobachtet",
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:trending-up",
        modus=MODUS_HOCH,
        beobachtet=lambda d: d.lose.preis_pro_tonne,
    ),
    PelletpreisExtremwertDescription(
        key="sackware_tief_beobachtet",
        translation_key="sackware_tief_beobachtet",
        bereich=BEREICH_NUR_UNTERREGION,
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:trending-down",
        modus=MODUS_TIEF,
        beobachtet=lambda d: d.sackware.preis_pro_tonne if d.sackware else None,
    ),
    PelletpreisExtremwertDescription(
        key="sackware_hoch_beobachtet",
        translation_key="sackware_hoch_beobachtet",
        bereich=BEREICH_NUR_UNTERREGION,
        native_unit_of_measurement=PREIS_PRO_TONNE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:trending-up",
        modus=MODUS_HOCH,
        beobachtet=lambda d: d.sackware.preis_pro_tonne if d.sackware else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PelletpreiseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Lege die Sensoren für einen Konfigurationseintrag an."""
    coordinator: PelletpreiseCoordinator = entry.runtime_data

    entitaeten: list[PelletpreisBasisSensor] = [
        PelletpreisSensor(coordinator, entry, beschreibung)
        for beschreibung in SENSOREN
        if passt_zur_region(beschreibung.bereich, coordinator.region)
        and (coordinator.bundesland_vergleich or not beschreibung.nur_mit_vergleich)
    ]
    entitaeten.extend(
        PelletpreisExtremwertSensor(coordinator, entry, beschreibung)
        for beschreibung in EXTREMWERT_SENSOREN
        if passt_zur_region(beschreibung.bereich, coordinator.region)
    )
    async_add_entities(entitaeten)

    # Ohne diesen Dienst wäre ein einmal aufgezeichneter Rekord nur noch durch
    # Löschen und Neuanlegen der Integration loszuwerden — samt Verlust aller
    # anderen Aufzeichnungen.
    entity_platform.async_get_current_platform().async_register_entity_service(
        SERVICE_EXTREMWERTE_ZURUECKSETZEN, None, "async_extremwerte_zuruecksetzen"
    )


class PelletpreisBasisSensor(CoordinatorEntity[PelletpreiseCoordinator], SensorEntity):
    """Gemeinsames Gerüst: Geräteangaben, Herkunftsattribute, Dienstsperre."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PelletpreiseCoordinator,
        entry: PelletpreiseConfigEntry,
        beschreibung: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = beschreibung
        self._attr_unique_id = f"{entry.entry_id}_{beschreibung.key}"
        # Die Quellenangabe nennt die Domain, von der dieser Eintrag wirklich
        # liest. "Daten von heizpellets24.de" an einem Schweizer Preis wäre
        # eine Behauptung über die Herkunft, die nicht stimmt.
        self._attr_attribution = attribution(coordinator.land)
        self._attr_native_unit_of_measurement = _einheit(
            beschreibung.native_unit_of_measurement, coordinator.waehrung
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Pelletpreise {coordinator.region_name}",
            manufacturer="HeizPellets24",
            model="Marktpreis-Beobachtung",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=coordinator.url,
        )

    @property
    def _basisattribute(self) -> dict[str, Any]:
        daten = self.coordinator.data
        if daten is None:
            return {}
        return {
            "region": daten.region_name,
            "land": daten.land.name,
            # Steht ausdrücklich am Sensor und nicht nur in der Einheit: wer
            # Attribute in einer Vorlage weiterrechnet, sieht sonst nicht, dass
            # er Franken vor sich hat.
            "waehrung": daten.waehrung,
            "quelle": self.coordinator.url,
            "basis_kg": REFERENZMENGE_KG,
        }

    async def async_extremwerte_zuruecksetzen(self) -> None:
        """Nur die Rekord-Sensoren können das — hier wird es laut abgelehnt.

        Home Assistant reicht einen Entitätsdienst an jede angesprochene
        Entität weiter. Ohne diese Sperre bekäme wer den Dienst auf einen
        gewöhnlichen Preissensor anwendet einen ``AttributeError`` im
        Protokoll und keine Erklärung.
        """
        raise ServiceValidationError(
            f"{self.entity_id} führt keinen beobachteten Extremwert. "
            "Der Dienst gilt nur für die Sensoren mit '(beobachtet)' im Namen."
        )


class PelletpreisSensor(PelletpreisBasisSensor):
    """Ein einzelner Preiswert."""

    entity_description: PelletpreisSensorDescription

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
        attribute = self._basisattribute
        if self.entity_description.zusatzattribute is not None:
            attribute.update(self.entity_description.zusatzattribute(daten))
        return attribute


@dataclass
class ExtremwertSpeicher(ExtraStoredData):
    """Was von einem Rekord einen Neustart überdauern muss.

    Bewusst **nicht** über den letzten Zustand der Entität wiederhergestellt:
    fällt heizpellets24.de aus, steht dort „unavailable", und ein Neustart in
    diesem Fenster hätte die ganze Aufzeichnung gelöscht. Diese Zusatzdaten
    schreibt Home Assistant unabhängig vom Zustandswert mit (alle 15 Minuten
    und beim Herunterfahren).
    """

    extrem: Extremwert

    def as_dict(self) -> dict[str, Any]:
        return fuer_speicher(self.extrem)


class PelletpreisExtremwertSensor(PelletpreisBasisSensor, RestoreEntity):
    """Der niedrigste bzw. höchste Preis, den diese Installation gesehen hat."""

    entity_description: PelletpreisExtremwertDescription

    def __init__(
        self,
        coordinator: PelletpreiseCoordinator,
        entry: PelletpreiseConfigEntry,
        beschreibung: PelletpreisExtremwertDescription,
    ) -> None:
        super().__init__(coordinator, entry, beschreibung)
        # Die Quellenangabe der übrigen Sensoren gilt hier nur zur Hälfte: der
        # einzelne Preis kommt von der Quelle, die Aussage „das ist der
        # tiefste seit Beobachtungsbeginn" kommt von hier.
        self._attr_attribution = attribution_beobachtet(coordinator.land)
        self._extrem: Extremwert | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        gespeichert = await self.async_get_last_extra_data()
        if gespeichert is not None:
            try:
                self._extrem = aus_speicher(gespeichert.as_dict())
            except ValueError as err:
                # Laut, nicht still: ein verworfener Rekord ist eine
                # verlorene Aufzeichnung und soll im Protokoll stehen.
                _LOGGER.warning(
                    "%s: gespeicherter Extremwert unbrauchbar, Aufzeichnung "
                    "beginnt neu. %s",
                    self.entity_id,
                    err,
                )
                self._extrem = None
        self._fortschreiben()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._fortschreiben()
        super()._handle_coordinator_update()

    @callback
    def _fortschreiben(self) -> None:
        """Beziehe den aktuellen Preis in den Rekord ein."""
        daten = self.coordinator.data
        if daten is None or not self.coordinator.last_update_success:
            return
        preis = self.entity_description.beobachtet(daten)
        if preis is None:
            # Sackware, die die Quelle heute nicht führt: der bisherige Rekord
            # bleibt stehen. Er war einmal wahr und wird es nicht dadurch
            # weniger, dass es heute kein Angebot gibt.
            return
        self._extrem = fortschreiben(
            self._extrem,
            preis,
            dt_util.now().isoformat(timespec="seconds"),
            modus=self.entity_description.modus,
        )

    @property
    def native_value(self) -> float | None:
        return self._extrem.preis_pro_tonne if self._extrem else None

    @property
    def available(self) -> bool:
        return super().available and self._extrem is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attribute = self._basisattribute
        attribute["hinweis"] = _extremwert_hinweis(
            self.entity_description.modus, self.coordinator.land
        )
        if self._extrem is not None:
            attribute["gesehen_am"] = self._extrem.gesehen_am
            attribute["beobachtet_seit"] = self._extrem.beobachtet_seit
        return attribute

    @property
    def extra_restore_state_data(self) -> ExtraStoredData | None:
        if self._extrem is None:
            return None
        return ExtremwertSpeicher(self._extrem)

    async def async_extremwerte_zuruecksetzen(self) -> None:
        """Verwirf die Aufzeichnung und beginne beim heutigen Preis von vorn."""
        _LOGGER.info(
            "%s: Extremwert zurückgesetzt (war %s)",
            self.entity_id,
            self._extrem.preis_pro_tonne if self._extrem else "leer",
        )
        self._extrem = None
        self._fortschreiben()
        self.async_write_ha_state()
