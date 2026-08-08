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
    CONF_MENGE,
    CONF_REGION,
    DEFAULT_BUNDESLAND_VERGLEICH,
    DEFAULT_EINBLASPAUSCHALE,
    DEFAULT_MENGE,
    DOMAIN,
    MAX_EINBLASPAUSCHALE,
    MAX_MENGE,
    MIN_EINBLASPAUSCHALE,
    MIN_MENGE,
    REGION_DEUTSCHLAND,
    REGIONEN,
)
from .coordinator import preise_abrufen


def _regionsauswahl() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=slug, label=name)
                for slug, name in REGIONEN.items()
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


def _pauschalenauswahl() -> NumberSelector:
    """Eingabefeld für die Einblaspauschale.

    Schrittweite 0,01, weil Händler krumme Beträge nehmen (44,90 € ist kein
    Sonderfall). Die Vorgabe bleibt 0 — welchen Betrag der eigene Händler
    verlangt, steht auf dessen Angebot und nicht auf der Quellseite.
    """
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_EINBLASPAUSCHALE,
            max=MAX_EINBLASPAUSCHALE,
            step=0.01,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="€",
        )
    )


class PelletpreiseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Richtet eine Region ein."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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
                    data={CONF_REGION: region},
                    options={
                        CONF_MENGE: menge,
                        CONF_EINBLASPAUSCHALE: pauschale,
                    },
                )
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="user",
                data_schema=self._schema(user_input),
                errors=errors,
                description_placeholders={"fehler": fehler},
            )

        return self.async_show_form(step_id="user", data_schema=self._schema(None))

    def _schema(self, vorgabe: dict[str, Any] | None) -> vol.Schema:
        vorgabe = vorgabe or {}
        return vol.Schema(
            {
                vol.Required(
                    CONF_REGION, default=vorgabe.get(CONF_REGION, vol.UNDEFINED)
                ): _regionsauswahl(),
                vol.Required(
                    CONF_MENGE, default=vorgabe.get(CONF_MENGE, DEFAULT_MENGE)
                ): _mengenauswahl(),
                vol.Required(
                    CONF_EINBLASPAUSCHALE,
                    default=vorgabe.get(
                        CONF_EINBLASPAUSCHALE, DEFAULT_EINBLASPAUSCHALE
                    ),
                ): _pauschalenauswahl(),
            }
        )

    async def _abruf_pruefen(
        self, region: str, menge: int, pauschale: float
    ) -> str | None:
        """Hole die Seite einmal. Gibt die Fehlermeldung zurück, sonst None.

        Bewusst über dieselbe Funktion wie im laufenden Betrieb: eine
        Einrichtungsprüfung, die einen anderen Weg nimmt als die spätere
        Abfrage, prüft nicht das, was danach passiert.
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
    def _ist_deutschland(self) -> bool:
        """Nur im Deutschland-Eintrag ergibt der Bundesland-Vergleich Sinn.

        Der Schalter wird deshalb sonst gar nicht erst gezeigt: eine Option,
        die für 16 von 17 Regionen nichts bewirkt, ist ein Versprechen, das
        der Dialog nicht halten kann.
        """
        return self.config_entry.data.get(CONF_REGION) == REGION_DEUTSCHLAND

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
            if self._ist_deutschland:
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
            ): _pauschalenauswahl(),
        }
        if self._ist_deutschland:
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
                "region": REGIONEN.get(
                    self.config_entry.data.get(CONF_REGION, ""), "?"
                )
            },
        )
