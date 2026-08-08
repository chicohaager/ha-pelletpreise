"""Abruf der Pelletpreise von heizpellets24.de."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .berechnung import (
    berechnungstext,
    gesamtpreis_euro,
    pruefe_einblaspauschale,
    warenwert_euro,
)
from .const import (
    BUNDESLAENDER,
    CONF_BUNDESLAND_VERGLEICH,
    CONF_EINBLASPAUSCHALE,
    CONF_MENGE,
    CONF_REGION,
    DEFAULT_BUNDESLAND_VERGLEICH,
    DEFAULT_EINBLASPAUSCHALE,
    DOMAIN,
    REGION_DEUTSCHLAND,
    REGIONEN,
    UPDATE_INTERVAL_HOURS,
    VERGLEICH_PARALLEL,
)
from .parser import (
    REFERENZMENGE_KG,
    Bundespreise,
    ParseError,
    Preis,
    Regionalpreise,
    parse_bundesland,
    parse_deutschland,
)
from .vergleich import Vergleich, bilde_vergleich

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

    einblaspauschale_eur: float
    """Vom Nutzer eingetragener Zuschlag je Lieferung — **kein** Wert der Quelle.

    Fließt ausschließlich in den Gesamtpreis der **losen** Ware ein; die
    Preise je Tonne und je Kilogramm bleiben davon unberührt, weil sie
    Marktpreise der Quelle sind und keine Rechnung.
    """

    lose: Preis
    sackware: Preis | None
    """Nur Bundesland-Seiten führen Sackware; für Deutschland ist es None."""

    langfrist: Bundespreise | None
    """Nur für die Region Deutschland gefüllt."""

    vergleich_lose: Vergleich | None = None
    """Günstigstes/teuerstes Bundesland bei loser Ware.

    Nur gefüllt, wenn der Bundesland-Vergleich eingeschaltet ist **und** alle
    16 Seiten gelesen werden konnten. Bei einem einzigen Fehlschlag bleibt das
    Feld leer: „das günstigste von 15" wäre eine Aussage über eine Menge, die
    gar nicht vollständig geprüft wurde.
    """

    vergleich_sackware: Vergleich | None = None
    """Dasselbe für Sackware — Bundesländer ohne Angebot bleiben außen vor."""

    def warenwert(self, preis: Preis) -> float:
        """Der reine Warenwert der Bestellmenge, ohne jeden Zuschlag."""
        return warenwert_euro(preis.euro_pro_tonne, self.menge_kg)

    def gesamtpreis(self, preis: Preis, *, mit_einblaspauschale: bool) -> float:
        """Rechne den Referenzpreis auf die Bestellmenge hoch.

        ``mit_einblaspauschale`` ist bewusst ein Pflichtargument ohne Vorgabe:
        die Pauschale gilt nur für lose Ware, und diese Entscheidung soll an
        jeder Aufrufstelle sichtbar getroffen werden. Ein stiller Standardwert
        hieße, dass ein neuer Sensor die Frage versehentlich mitbeantwortet.

        Achtung, das ist eine **lineare Hochrechnung**, kein Angebot: die
        Quelle nennt ihren Preis für eine Gesamtabnahme von 6.000 kg. Echte
        Pelletpreise sind mengenabhängig — kleinere Mengen sind je Tonne
        teurer. Der Wert taugt für die Größenordnung, nicht für die
        Kalkulation. Der Sensor sagt das in seinen Attributen dazu.
        """
        return gesamtpreis_euro(
            preis.euro_pro_tonne,
            self.menge_kg,
            self.einblaspauschale_eur if mit_einblaspauschale else 0.0,
        )

    def berechnung(self, *, mit_einblaspauschale: bool) -> str:
        """Klartext zur Rechnung, für das Sensor-Attribut ``berechnung``."""
        return berechnungstext(
            self.menge_kg,
            self.einblaspauschale_eur if mit_einblaspauschale else 0.0,
        )


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


async def bundeslandpreise_abrufen(
    session: aiohttp.ClientSession,
) -> dict[str, Regionalpreise]:
    """Hole alle 16 Bundesland-Seiten — alles oder nichts.

    Ein Fehlschlag reißt den ganzen Vergleich mit: wer wissen will, wo es am
    günstigsten ist, bekommt entweder eine Antwort über alle 16 Länder oder
    gar keine. Ein Vergleich über die zufällig erreichbaren Seiten wäre der
    klassische stille Fehler — er sähe genauso aus wie das echte Ergebnis.

    Die Abrufe laufen gedrosselt (``VERGLEICH_PARALLEL``), damit hier nicht
    16 gleichzeitige Anfragen bei einer fremden Website auflaufen.
    """
    grenze = asyncio.Semaphore(VERGLEICH_PARALLEL)

    async def eine_seite(slug: str) -> Regionalpreise:
        async with grenze:
            html = await seite_holen(session, region_url(slug))
        return parse_bundesland(html, REGIONEN[slug])

    slugs = sorted(BUNDESLAENDER)
    ergebnisse = await asyncio.gather(
        *(eine_seite(slug) for slug in slugs), return_exceptions=True
    )

    preise: dict[str, Regionalpreise] = {}
    for slug, ergebnis in zip(slugs, ergebnisse, strict=True):
        if isinstance(ergebnis, BaseException):
            raise UpdateFailed(
                f"Bundesland-Vergleich abgebrochen bei {REGIONEN[slug]}: {ergebnis}"
            ) from ergebnis
        preise[slug] = ergebnis
    return preise


async def preise_abrufen(
    session: aiohttp.ClientSession,
    region: str,
    menge_kg: int,
    einblaspauschale_eur: float = DEFAULT_EINBLASPAUSCHALE,
    *,
    bundesland_vergleich: bool = DEFAULT_BUNDESLAND_VERGLEICH,
) -> Preisdaten:
    """Hole und lies die Preise einer Region.

    Diese Funktion ist der einzige Weg zu den Daten — der Einrichtungsdialog
    benutzt sie genauso wie der laufende Abruf. Damit prüft die Einrichtung
    genau das, was später auch passiert, und nicht etwas Ähnliches.
    """
    region_name = REGIONEN.get(region, region)

    # Zuerst prüfen, dann abrufen: ein unsinniger Zuschlag ist ein
    # Konfigurationsfehler und rechtfertigt keine Anfrage an eine fremde
    # Website. Über den Einrichtungsdialog kann er gar nicht entstehen — von
    # Hand geänderte Einträge in .storage schon.
    try:
        pauschale = pruefe_einblaspauschale(einblaspauschale_eur)
    except ValueError as err:
        raise UpdateFailed(str(err)) from err

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

    vergleich_lose: Vergleich | None = None
    vergleich_sackware: Vergleich | None = None
    if bundesland_vergleich and region == REGION_DEUTSCHLAND:
        try:
            regionalpreise = await bundeslandpreise_abrufen(session)
        except (UpdateFailed, ParseError) as err:
            # Bewusst kein Abbruch des ganzen Abrufs: der Bundesdurchschnitt
            # steht bereits und ist der Hauptzweck des Eintrags. Die
            # Vergleichssensoren bleiben ohne Wert — und der Grund steht im
            # Protokoll, statt sich hinter einer leeren Anzeige zu verstecken.
            _LOGGER.warning(
                "Pelletpreise: Bundesland-Vergleich übersprungen. %s", err
            )
        else:
            vergleich_lose = bilde_vergleich(
                {
                    slug: preise.lose.euro_pro_tonne
                    for slug, preise in regionalpreise.items()
                }
            )
            vergleich_sackware = bilde_vergleich(
                {
                    slug: preise.sackware.euro_pro_tonne if preise.sackware else None
                    for slug, preise in regionalpreise.items()
                }
            )

    return Preisdaten(
        region=region,
        region_name=region_name,
        menge_kg=menge_kg,
        einblaspauschale_eur=pauschale,
        lose=lose,
        sackware=sackware,
        langfrist=langfrist,
        vergleich_lose=vergleich_lose,
        vergleich_sackware=vergleich_sackware,
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
        # Einträge, die vor dieser Version angelegt wurden, kennen den
        # Schlüssel nicht. Die Vorgabe 0 ergibt für sie exakt denselben
        # Gesamtpreis wie bisher — deshalb braucht es hier keine Migration und
        # keinen Versionssprung des Eintragsschemas.
        self.einblaspauschale: float = float(
            entry.options.get(
                CONF_EINBLASPAUSCHALE,
                entry.data.get(CONF_EINBLASPAUSCHALE, DEFAULT_EINBLASPAUSCHALE),
            )
        )
        # Der Vergleich kostet 16 zusätzliche Abrufe und ergibt nur im
        # Deutschland-Eintrag Sinn. Die zweite Bedingung ist keine Formsache:
        # ohne sie würde ein von Hand gesetzter Schalter in einem
        # Bundesland-Eintrag stillschweigend 16 Abrufe je Aktualisierung
        # auslösen, ohne dass dort je ein Sensor davon entstünde.
        self.bundesland_vergleich: bool = bool(
            entry.options.get(
                CONF_BUNDESLAND_VERGLEICH, DEFAULT_BUNDESLAND_VERGLEICH
            )
        ) and self.region == REGION_DEUTSCHLAND
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
        daten = await preise_abrufen(
            self._session,
            self.region,
            self.menge,
            self.einblaspauschale,
            bundesland_vergleich=self.bundesland_vergleich,
        )
        if daten.sackware is None and self.region != REGION_DEUTSCHLAND:
            _LOGGER.debug(
                "%s: die Seite führt derzeit keinen Sackware-Preis", self.region_name
            )
        return daten
