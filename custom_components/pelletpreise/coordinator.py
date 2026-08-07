"""Abruf der Pelletpreise von heizpellets24.de."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_MENGE,
    CONF_REGION,
    DOMAIN,
    REGION_DEUTSCHLAND,
    REGIONEN,
    UPDATE_INTERVAL_HOURS,
)
from .parser import (
    REFERENZMENGE_KG,
    Bundespreise,
    ParseError,
    Preis,
    parse_bundesland,
    parse_deutschland,
)

_LOGGER = logging.getLogger(__name__)

BASIS_URL = "https://www.heizpellets24.de/pelletpreise"

# Ein browserähnliches Kennzeichen, damit die Seite regulär ausgeliefert wird,
# ergänzt um einen ehrlichen Hinweis, wer hier anfragt.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 (+home-assistant-pelletpreise)"
)
ANFRAGE_TIMEOUT = aiohttp.ClientTimeout(total=30)


def region_url(region: str) -> str:
    """Die abzurufende Seite einer Region.

    Beide Adressen sind laut robots.txt von heizpellets24.de für alle Clients
    freigegeben. Die dort gesperrten Datenendpunkte (/ajaxcontent/,
    /JsonHandler.ashx, /ChartHandler.ashx) werden bewusst nicht verwendet.
    """
    if region == REGION_DEUTSCHLAND:
        return BASIS_URL
    return f"{BASIS_URL}/{region}"


@dataclass(frozen=True)
class Preisdaten:
    """Ergebnis eines Abrufs."""

    region: str
    region_name: str
    menge_kg: int

    lose: Preis
    sackware: Preis | None
    """Nur Bundesland-Seiten führen Sackware; für Deutschland ist es None."""

    langfrist: Bundespreise | None
    """Nur für die Region Deutschland gefüllt."""

    def gesamtpreis(self, preis: Preis) -> float:
        """Rechne den Referenzpreis auf die Bestellmenge hoch.

        Achtung, das ist eine **lineare Hochrechnung**, kein Angebot: die
        Quelle nennt ihren Preis für eine Gesamtabnahme von 6.000 kg. Echte
        Pelletpreise sind mengenabhängig — kleinere Mengen sind je Tonne
        teurer. Der Wert taugt für die Größenordnung, nicht für die
        Kalkulation. Der Sensor sagt das in seinen Attributen dazu.
        """
        return round(preis.euro_pro_tonne * self.menge_kg / 1000, 2)


async def seite_holen(session: aiohttp.ClientSession, url: str) -> str:
    """Lade eine Preisseite.

    Fehler werden hier **nicht** abgefangen und in Leerwerte verwandelt. Ein
    Sensor, der bei einer Störung stillschweigend einen Ersatzwert zeigt, ist
    schlimmer als einer, der "nicht verfügbar" meldet — beim Preis fällt der
    Unterschied erst bei der Rechnung auf.
    """
    kopfzeilen = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9",
        # Die Preise ändern sich täglich; eine zwischengespeicherte Antwort
        # wäre ein Messwert von vorgestern.
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    try:
        async with session.get(url, headers=kopfzeilen, timeout=ANFRAGE_TIMEOUT) as antwort:
            if antwort.status != 200:
                raise UpdateFailed(
                    f"heizpellets24.de antwortete mit HTTP {antwort.status} auf {url}"
                )
            return await antwort.text()
    except TimeoutError as err:
        raise UpdateFailed(f"Zeitüberschreitung beim Abruf von {url}") from err
    except aiohttp.ClientError as err:
        raise UpdateFailed(f"Verbindungsfehler beim Abruf von {url}: {err}") from err


async def preise_abrufen(
    session: aiohttp.ClientSession, region: str, menge_kg: int
) -> Preisdaten:
    """Hole und lies die Preise einer Region.

    Diese Funktion ist der einzige Weg zu den Daten — der Einrichtungsdialog
    benutzt sie genauso wie der laufende Abruf. Damit prüft die Einrichtung
    genau das, was später auch passiert, und nicht etwas Ähnliches.
    """
    region_name = REGIONEN.get(region, region)
    html = await seite_holen(session, region_url(region))

    try:
        if region == REGION_DEUTSCHLAND:
            bund = parse_deutschland(html)
            lose, sackware, langfrist = bund.lose, None, bund
        else:
            regional = parse_bundesland(html, region_name)
            lose, sackware, langfrist = regional.lose, regional.sackware, None
    except ParseError as err:
        # Der Parser sagt genau, was er nicht gefunden hat. Diese Auskunft geht
        # unverändert an den Nutzer, damit eine Änderung an der Website als
        # solche erkennbar ist und nicht als "Sensor kaputt".
        raise UpdateFailed(str(err)) from err

    return Preisdaten(
        region=region,
        region_name=region_name,
        menge_kg=menge_kg,
        lose=lose,
        sackware=sackware,
        langfrist=langfrist,
    )


class PelletpreiseCoordinator(DataUpdateCoordinator[Preisdaten]):
    """Holt die Preise für genau eine Region."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        session: aiohttp.ClientSession,
    ) -> None:
        self.region: str = entry.data[CONF_REGION]
        self.region_name: str = REGIONEN.get(self.region, self.region)
        self.menge: int = entry.options.get(
            CONF_MENGE, entry.data.get(CONF_MENGE, REFERENZMENGE_KG)
        )
        self._session = session
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.region}",
            update_interval=timedelta(hours=UPDATE_INTERVAL_HOURS),
        )

    @property
    def url(self) -> str:
        return region_url(self.region)

    async def _async_update_data(self) -> Preisdaten:
        daten = await preise_abrufen(self._session, self.region, self.menge)
        if daten.sackware is None and self.region != REGION_DEUTSCHLAND:
            _LOGGER.debug(
                "%s: die Seite führt derzeit keinen Sackware-Preis", self.region_name
            )
        return daten
