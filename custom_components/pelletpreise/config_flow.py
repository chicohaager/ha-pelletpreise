"""Einrichtungsdialog der Pelletpreise-Integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SelectOptionDict,
)
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    CONF_BUNDESLAND_VERGLEICH,
    CONF_EINBLASPAUSCHALE,
    CONF_LAND,
    CONF_MENGE,
    CONF_REGION,
    DEFAULT_BUNDESLAND_VERGLEICH,
    DEFAULT_EINBLASPAUSCHALE,
    DEFAULT_MENGE,
    DOMAIN,
    LAENDER,
    LAND_DE,
    MAX_EINBLASPAUSCHALE,
    MAX_MENGE,
    MIN_EINBLASPAUSCHALE,
    MIN_MENGE,
    REGIONEN,
    Land,
    ist_landesebene,
    land_von_region,
)
from .coordinator import preise_abrufen


def _landauswahl() -> SelectSelector:
    """Das Land zuerst — es entscheidet über Regionsliste **und** Währung.

    Zwei Schritte statt einer langen Liste: Deutschland, Österreich und die
    Schweiz zusammen ergäben 27 Einträge in einem Aufklappmenü, in dem
    „Salzburg" und „Sachsen" direkt untereinander stünden. Wer sich dort
    verklickt, bekommt keinen Fehler, sondern klaglos den Preis des falschen
    Landes — in einem Fall sogar in einer anderen Währung.
    """
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=land.code, label=land.name)
                for land in LAENDER.values()
            ],
            mode=SelectSelectorMode.LIST,
        )
    )


def _regionsauswahl(land: Land) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=slug, label=name)
                for slug, name in land.regionen.items()
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _mengenauswahl() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_MENGE,
            max=MAX_MENGE,
            step=100,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="kg",
        )
    )


def _pauschalenauswahl(waehrung: str) -> NumberSelector:
    """Eingabefeld für die Einblaspauschale.

    Schrittweite 0,01, weil Händler krumme Beträge nehmen (44,90 € ist kein
    Sonderfall). Die Vorgabe bleibt 0 — welchen Betrag der eigene Händler
    verlangt, steht auf dessen Angebot und nicht auf der Quellseite.

    Die Einheit am Feld ist die Währung des gewählten Landes: bei einem
    Schweizer Eintrag wird der Betrag zu einem CHF-Preis addiert, und ein
    Eurozeichen am Eingabefeld würde genau die falsche Erwartung wecken.
    """
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_EINBLASPAUSCHALE,
            max=MAX_EINBLASPAUSCHALE,
            step=0.01,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=waehrung,
        )
    )


class PelletpreiseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Richtet eine Region ein."""

    VERSION = 2

    def __init__(self) -> None:
        self._land: Land = LAENDER[LAND_DE]

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schritt 1: das Land."""
        if user_input is not None:
            self._land = LAENDER[user_input[CONF_LAND]]
            return await self.async_step_region()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_LAND, default=LAND_DE): _landauswahl()}
            ),
        )

    async def async_step_region(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schritt 2: Region, Bestellmenge und Einblaspauschale."""
        errors: dict[str, str] = {}

        if user_input is not None:
            region = user_input[CONF_REGION]
            menge = int(user_input[CONF_MENGE])
            pauschale = float(
                user_input.get(CONF_EINBLASPAUSCHALE, DEFAULT_EINBLASPAUSCHALE)
            )

            await self.async_set_unique_id(region)
            self._abort_if_unique_id_configured()

            # Der Abruf wird hier wirklich geprüft. Die Vorgängerversion hat
            # jeden Fehler protokolliert und den Eintrag trotzdem angelegt —
            # der Nutzer bekam eine erfolgreiche Einrichtung mit Sensoren, die
            # nie einen Wert hatten.
            fehler = await self._abruf_pruefen(region, menge, pauschale)
            if fehler is None:
                return self.async_create_entry(
                    title=f"Pelletpreise {REGIONEN[region]}",
                    # Das Land steht **nicht** mit im Eintrag: es steckt
                    # eindeutig in der Region (`land_von_region`). Zwei
                    # Speicherorte für dieselbe Tatsache können auseinander
                    # laufen, und dann zeigte der Eintrag Preise der einen
                    # Domain mit der Währung der anderen.
                    data={CONF_REGION: region},
                    options={
                        CONF_MENGE: menge,
                        CONF_EINBLASPAUSCHALE: pauschale,
                    },
                )
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="region",
                data_schema=self._schema(user_input),
                errors=errors,
                description_placeholders=self._platzhalter(fehler),
            )

        return self.async_show_form(
            step_id="region",
            data_schema=self._schema(None),
            description_placeholders=self._platzhalter(None),
        )

    def _platzhalter(self, fehler: str | None) -> dict[str, str]:
        return {
            "land": self._land.name,
            "waehrung": self._land.waehrung,
            "quelle": self._land.host,
            "fehler": fehler or "",
        }

    def _schema(self, vorgabe: dict[str, Any] | None) -> vol.Schema:
        vorgabe = vorgabe or {}
        return vol.Schema(
            {
                vol.Required(
                    CONF_REGION,
                    default=vorgabe.get(CONF_REGION, self._land.landesregion),
                ): _regionsauswahl(self._land),
                vol.Required(
                    CONF_MENGE, default=vorgabe.get(CONF_MENGE, DEFAULT_MENGE)
                ): _mengenauswahl(),
                vol.Required(
                    CONF_EINBLASPAUSCHALE,
                    default=vorgabe.get(
                        CONF_EINBLASPAUSCHALE, DEFAULT_EINBLASPAUSCHALE
                    ),
                ): _pauschalenauswahl(self._land.waehrung),
            }
        )

    async def _abruf_pruefen(
        self, region: str, menge: int, pauschale: float
    ) -> str | None:
        """Hole die Seite einmal. Gibt die Fehlermeldung zurück, sonst None.

        Bewusst über dieselbe Funktion wie im laufenden Betrieb: eine
        Einrichtungsprüfung, die einen anderen Weg nimmt als die spätere
        Abfrage, prüft nicht das, was danach passiert. Sie deckt damit auch
        den Fall ab, dass eine Region gerade gar keinen Preis führt — dann
        entsteht kein Eintrag mit dauerhaft leeren Sensoren, sondern eine
        Fehlermeldung, die den Grund nennt.
        """
        try:
            await preise_abrufen(
                async_get_clientsession(self.hass), region, menge, pauschale
            )
        except UpdateFailed as err:
            return str(err)
        except Exception as err:  # noqa: BLE001
            return f"Unerwarteter Fehler: {err}"
        return None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> PelletpreiseOptionsFlow:
        return PelletpreiseOptionsFlow()


class PelletpreiseOptionsFlow(OptionsFlow):
    """Ändert Bestellmenge und Einblaspauschale eines bestehenden Eintrags.

    Wichtig: hier wird `self.config_entry` **nicht** zugewiesen. Seit
    Home Assistant 2024.11 ist das eine Property ohne Setter; die
    Vorgängerversion tat es trotzdem und der Dialog brach beim Öffnen mit
    "AttributeError: property 'config_entry' ... has no setter" ab (HTTP 500).
    Die Basisklasse stellt den Eintrag von selbst bereit.
    """

    @property
    def _region(self) -> str:
        return self.config_entry.data.get(CONF_REGION, "")

    @property
    def _land(self) -> Land:
        return land_von_region(self._region)

    @property
    def _hat_vergleich(self) -> bool:
        """Nur im Landeseintrag mit Unterregionen ergibt der Vergleich Sinn.

        Der Schalter wird deshalb sonst gar nicht erst gezeigt: eine Option,
        die nichts bewirkt, ist ein Versprechen, das der Dialog nicht halten
        kann. Im Schweizer Eintrag fehlt er ebenfalls — die Quelle führt dort
        keine Regionalpreise, es gäbe also nichts zu vergleichen.
        """
        return ist_landesebene(self._region) and bool(self._land.unterregionen)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            optionen: dict[str, Any] = {
                CONF_MENGE: int(user_input[CONF_MENGE]),
                CONF_EINBLASPAUSCHALE: float(
                    user_input.get(CONF_EINBLASPAUSCHALE, DEFAULT_EINBLASPAUSCHALE)
                ),
            }
            if self._hat_vergleich:
                optionen[CONF_BUNDESLAND_VERGLEICH] = bool(
                    user_input.get(
                        CONF_BUNDESLAND_VERGLEICH, DEFAULT_BUNDESLAND_VERGLEICH
                    )
                )
            return self.async_create_entry(data=optionen)

        aktuelle_menge = self.config_entry.options.get(
            CONF_MENGE, self.config_entry.data.get(CONF_MENGE, DEFAULT_MENGE)
        )
        # Bestehende Einträge kennen den Schlüssel nicht — dann steht hier 0,
        # und am Gesamtpreis ändert sich nichts, solange nichts eingetragen wird.
        aktuelle_pauschale = self.config_entry.options.get(
            CONF_EINBLASPAUSCHALE,
            self.config_entry.data.get(
                CONF_EINBLASPAUSCHALE, DEFAULT_EINBLASPAUSCHALE
            ),
        )
        felder: dict[Any, Any] = {
            vol.Required(CONF_MENGE, default=aktuelle_menge): _mengenauswahl(),
            vol.Required(
                CONF_EINBLASPAUSCHALE, default=aktuelle_pauschale
            ): _pauschalenauswahl(self._land.waehrung),
        }
        if self._hat_vergleich:
            felder[
                vol.Required(
                    CONF_BUNDESLAND_VERGLEICH,
                    default=self.config_entry.options.get(
                        CONF_BUNDESLAND_VERGLEICH, DEFAULT_BUNDESLAND_VERGLEICH
                    ),
                )
            ] = BooleanSelector()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(felder),
            description_placeholders={
                "region": REGIONEN.get(self._region, "?"),
                "anzahl": str(len(self._land.unterregionen)),
                "quelle": self._land.host,
            },
        )
