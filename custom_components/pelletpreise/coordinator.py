"""Abruf der Pelletpreise von heizpellets24 (de/at/ch)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

# Unter anderem Namen importiert, und zwar als Modul: `Preisdaten` hat
# Methoden, die genauso heißen wie die Rechenfunktionen (`warenwert`,
# `gesamtpreis`, `berechnung`). Mit `rechnen.warenwert(...)` ist an jeder
# Aufrufstelle zu sehen, welche der beiden gemeint ist — sonst hinge die
# Antwort an Pythons Namensauflösung statt am Lesen.
from . import berechnung as rechnen
from .berechnung import pruefe_einblaspauschale
from .const import (
    CONF_BUNDESLAND_VERGLEICH,
    CONF_EINBLASPAUSCHALE,
    CONF_MENGE,
    CONF_REGION,
    DEFAULT_BUNDESLAND_VERGLEICH,
    DEFAULT_EINBLASPAUSCHALE,
    DOMAIN,
    REGIONEN,
    UPDATE_INTERVAL_HOURS,
    VERGLEICH_PARALLEL,
    Land,
    ist_landesebene,
    land_von_region,
)
from .parser import (
    REFERENZMENGE_KG,
    KeinAngebot,
    Landespreise,
    ParseError,
    Preis,
    Regionalpreise,
    parse_bundesland,
    parse_landesseite,
)
from .vergleich import Vergleich, bilde_vergleich

_LOGGER = logging.getLogger(__name__)

# Ein browserähnliches Kennzeichen, damit die Seite regulär ausgeliefert wird,
# ergänzt um einen ehrlichen Hinweis, wer hier anfragt.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 (+home-assistant-pelletpreise)"
)
ANFRAGE_TIMEOUT = aiohttp.ClientTimeout(total=30)


def region_url(region: str) -> str:
    """Die abzurufende Seite einer Region.

    Das Land steckt in der Region: ``bayern`` liegt auf heizpellets24.de,
    ``tirol`` auf heizpellets24.at. Die Zuordnung kommt aus ``const.py`` und
    wird nicht geraten — ein Slug auf der falschen Domain liefert eine
    404-Seite, und die enthält keinen Preis, sondern einen Parse-Fehler.

    Alle verwendeten Adressen sind laut robots.txt für alle Clients
    freigegeben; das wurde für alle drei Domains einzeln geprüft. Die dort
    gesperrten Datenendpunkte (/ajaxcontent/, /JsonHandler.ashx,
    /ChartHandler.ashx) werden bewusst nicht verwendet.
    """
    land = land_von_region(region)
    if region == land.landesregion:
        return land.basis_url
    return f"{land.basis_url}/{region}"


@dataclass(frozen=True)
class Preisdaten:
    """Ergebnis eines Abrufs."""

    land: Land
    region: str
    region_name: str
    menge_kg: int

    waehrung: str
    """Währung, wie die Quelle sie auf **dieser** Seite geführt hat.

    Nicht aus dem Land abgeleitet, sondern gelesen und gegen die erwartete
    Währung geprüft. Ein CHF-Preis mit einem Eurozeichen daneben wäre nirgends
    zu sehen — der Zahlenwert allein sieht in beiden Währungen plausibel aus.
    """

    einblaspauschale: float
    """Vom Nutzer eingetragener Zuschlag je Lieferung — **kein** Wert der Quelle.

    Fließt ausschließlich in den Gesamtpreis der **losen** Ware ein; die
    Preise je Tonne und je Kilogramm bleiben davon unberührt, weil sie
    Marktpreise der Quelle sind und keine Rechnung. Steht in derselben
    Währung wie die Preise des Eintrags.
    """

    lose: Preis
    sackware: Preis | None
    """Nur Bundesland-Seiten führen Sackware; auf Landesebene ist es None."""

    langfrist: Landespreise | None
    """Nur für die Landesebene gefüllt (Deutschland, Österreich, Schweiz)."""

    vergleich_lose: Vergleich | None = None
    """Günstigstes/teuerstes Bundesland bei loser Ware.

    Nur gefüllt, wenn der Bundesland-Vergleich eingeschaltet ist **und** alle
    Bundesland-Seiten des Landes gelesen werden konnten. Bei einem einzigen
    Lesefehler bleibt das Feld leer: „das günstigste von 15" wäre eine Aussage
    über eine Menge, die gar nicht vollständig geprüft wurde.
    """

    vergleich_sackware: Vergleich | None = None
    """Dasselbe für Sackware — Bundesländer ohne Angebot bleiben außen vor."""

    def warenwert(self, preis: Preis) -> float:
        """Der reine Warenwert der Bestellmenge, ohne jeden Zuschlag."""
        return rechnen.warenwert(preis.preis_pro_tonne, self.menge_kg)

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
        return rechnen.gesamtpreis(
            preis.preis_pro_tonne,
            self.menge_kg,
            self.einblaspauschale if mit_einblaspauschale else 0.0,
        )

    def berechnung(self, *, mit_einblaspauschale: bool) -> str:
        """Klartext zur Rechnung, für das Sensor-Attribut ``berechnung``."""
        return rechnen.berechnungstext(
            self.menge_kg,
            self.einblaspauschale if mit_einblaspauschale else 0.0,
            self.waehrung,
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
                    f"heizpellets24 antwortete mit HTTP {antwort.status} auf {url}"
                )
            return await antwort.text()
    except TimeoutError as err:
        raise UpdateFailed(f"Zeitüberschreitung beim Abruf von {url}") from err
    except aiohttp.ClientError as err:
        raise UpdateFailed(f"Verbindungsfehler beim Abruf von {url}: {err}") from err


def pruefe_waehrung(land: Land, *preise: Preis | None) -> str:
    """Vergleiche die gelesene Währung mit der erwarteten.

    Die Einheit am Sensor kommt aus der Seite, nicht aus dieser Konstanten —
    diese Prüfung ist die Gegenprobe. Stellte die Quelle eines Tages um (oder
    lieferte eine Domain versehentlich die Seite einer anderen aus), stünde
    sonst ein CHF-Betrag mit einem Eurozeichen im Dashboard, und **nichts**
    daran wäre auffällig: 522 sieht als Euro genauso plausibel aus wie als
    Franken. Deshalb bricht der Abruf hier lieber ab.
    """
    gelesen = {preis.waehrung for preis in preise if preis is not None}
    if not gelesen:
        raise UpdateFailed(
            f"{land.name}: kein einziger Preis mit Währungsangabe gelesen."
        )
    if gelesen != {land.waehrung}:
        raise UpdateFailed(
            f"{land.name}: erwartet wurde die Währung {land.waehrung}, "
            f"gelesen wurde {sorted(gelesen)}. Der Abruf wird verworfen — ein "
            "Preis mit falscher Währung wäre im Dashboard nicht als solcher zu "
            f"erkennen. Bitte prüfen, was {land.host} geändert hat."
        )
    return land.waehrung


async def regionpreise_abrufen(
    session: aiohttp.ClientSession, land: Land
) -> dict[str, Regionalpreise | None]:
    """Hole alle Bundesland-Seiten eines Landes — alles oder nichts.

    Ein **Lesefehler** reißt den ganzen Vergleich mit: wer wissen will, wo es
    am günstigsten ist, bekommt entweder eine Antwort über alle Länder oder
    gar keine. Ein Vergleich über die zufällig erreichbaren Seiten wäre der
    klassische stille Fehler — er sähe genauso aus wie das echte Ergebnis.

    Ausgenommen ist ``KeinAngebot``: dass die Quelle für eine Region keinen
    Preis führt, ist ihre Auskunft und kein Fehlschlag (Vorarlberg am
    09.08.2026). Solche Regionen kommen als ``None`` zurück und landen am
    Sensor unter ``ohne_angebot`` — sichtbar, statt den Vergleich zu
    verhindern oder still mitgezählt zu werden.

    Die Abrufe laufen gedrosselt (``VERGLEICH_PARALLEL``), damit hier nicht
    alle Anfragen gleichzeitig bei einer fremden Website auflaufen.
    """
    grenze = asyncio.Semaphore(VERGLEICH_PARALLEL)

    async def eine_seite(slug: str) -> Regionalpreise | None:
        async with grenze:
            html = await seite_holen(session, region_url(slug))
        try:
            return parse_bundesland(html, land.unterregionen[slug])
        except KeinAngebot:
            return None

    slugs = sorted(land.unterregionen)
    ergebnisse = await asyncio.gather(
        *(eine_seite(slug) for slug in slugs), return_exceptions=True
    )

    preise: dict[str, Regionalpreise | None] = {}
    for slug, ergebnis in zip(slugs, ergebnisse, strict=True):
        if isinstance(ergebnis, BaseException):
            raise UpdateFailed(
                f"Bundesland-Vergleich abgebrochen bei "
                f"{land.unterregionen[slug]}: {ergebnis}"
            ) from ergebnis
        preise[slug] = ergebnis
    return preise


async def preise_abrufen(
    session: aiohttp.ClientSession,
    region: str,
    menge_kg: int,
    einblaspauschale: float = DEFAULT_EINBLASPAUSCHALE,
    *,
    bundesland_vergleich: bool = DEFAULT_BUNDESLAND_VERGLEICH,
) -> Preisdaten:
    """Hole und lies die Preise einer Region.

    Diese Funktion ist der einzige Weg zu den Daten — der Einrichtungsdialog
    benutzt sie genauso wie der laufende Abruf. Damit prüft die Einrichtung
    genau das, was später auch passiert, und nicht etwas Ähnliches.
    """
    try:
        land = land_von_region(region)
    except ValueError as err:
        raise UpdateFailed(str(err)) from err
    region_name = REGIONEN[region]

    # Zuerst prüfen, dann abrufen: ein unsinniger Zuschlag ist ein
    # Konfigurationsfehler und rechtfertigt keine Anfrage an eine fremde
    # Website. Über den Einrichtungsdialog kann er gar nicht entstehen — von
    # Hand geänderte Einträge in .storage schon.
    try:
        pauschale = pruefe_einblaspauschale(einblaspauschale)
    except ValueError as err:
        raise UpdateFailed(str(err)) from err

    html = await seite_holen(session, region_url(region))

    try:
        if ist_landesebene(region):
            landeswerte = parse_landesseite(html, region_name)
            lose, sackware, langfrist = landeswerte.lose, None, landeswerte
        else:
            regional = parse_bundesland(html, region_name)
            lose, sackware, langfrist = regional.lose, regional.sackware, None
    except ParseError as err:
        # Der Parser sagt genau, was er nicht gefunden hat. Diese Auskunft geht
        # unverändert an den Nutzer, damit eine Änderung an der Website als
        # solche erkennbar ist und nicht als "Sensor kaputt". Das gilt auch für
        # KeinAngebot: für einen einzelnen Eintrag ist ein Preis, den es nicht
        # gibt, ein Grund für "nicht verfügbar" — und kein Grund für einen
        # Ersatzwert.
        raise UpdateFailed(str(err)) from err

    waehrung = pruefe_waehrung(land, lose, sackware)

    vergleich_lose: Vergleich | None = None
    vergleich_sackware: Vergleich | None = None
    if bundesland_vergleich and ist_landesebene(region) and land.unterregionen:
        try:
            regionalpreise = await regionpreise_abrufen(session, land)
        except (UpdateFailed, ParseError) as err:
            # Bewusst kein Abbruch des ganzen Abrufs: der Landesdurchschnitt
            # steht bereits und ist der Hauptzweck des Eintrags. Die
            # Vergleichssensoren bleiben ohne Wert — und der Grund steht im
            # Protokoll, statt sich hinter einer leeren Anzeige zu verstecken.
            _LOGGER.warning(
                "Pelletpreise: Bundesland-Vergleich übersprungen. %s", err
            )
        else:
            ohne_lose = sorted(
                land.unterregionen[slug]
                for slug, werte in regionalpreise.items()
                if werte is None
            )
            if ohne_lose:
                # Laut, nicht still: sonst sähe ein Vergleich über neun
                # Bundesländer genauso aus wie einer über zwei.
                _LOGGER.info(
                    "Pelletpreise %s: ohne Preis für lose Ware und deshalb "
                    "nicht im Vergleich: %s",
                    land.name,
                    ", ".join(ohne_lose),
                )
            vergleich_lose = bilde_vergleich(
                {
                    slug: werte.lose.preis_pro_tonne if werte else None
                    for slug, werte in regionalpreise.items()
                },
                land.unterregionen,
            )
            vergleich_sackware = bilde_vergleich(
                {
                    slug: (
                        werte.sackware.preis_pro_tonne
                        if werte and werte.sackware
                        else None
                    )
                    for slug, werte in regionalpreise.items()
                },
                land.unterregionen,
            )

    return Preisdaten(
        land=land,
        region=region,
        region_name=region_name,
        menge_kg=menge_kg,
        waehrung=waehrung,
        einblaspauschale=pauschale,
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
        self.land: Land = land_von_region(self.region)
        self.region_name: str = REGIONEN[self.region]
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
        # Der Vergleich kostet je Bundesland einen zusätzlichen Abruf und
        # ergibt nur im Landeseintrag Sinn. Die weiteren Bedingungen sind keine
        # Formsache: ohne sie würde ein von Hand gesetzter Schalter in einem
        # Bundesland-Eintrag stillschweigend zusätzliche Abrufe je
        # Aktualisierung auslösen, ohne dass dort je ein Sensor davon
        # entstünde — und im Schweizer Eintrag gäbe es gar nichts zu
        # vergleichen, weil die Quelle dort keine Regionalpreise führt.
        self.bundesland_vergleich: bool = (
            bool(
                entry.options.get(
                    CONF_BUNDESLAND_VERGLEICH, DEFAULT_BUNDESLAND_VERGLEICH
                )
            )
            and ist_landesebene(self.region)
            and bool(self.land.unterregionen)
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

    @property
    def waehrung(self) -> str:
        """Die Währung dieses Eintrags.

        Vor dem ersten erfolgreichen Abruf gibt es keinen gelesenen Wert; dann
        gilt die erwartete Währung des Landes. Sie wird bei jedem Abruf gegen
        die gelesene geprüft (``pruefe_waehrung``), weicht sie ab, kommen gar
        keine Daten durch — die Einheit kann deshalb nicht dauerhaft falsch
        stehen.
        """
        if self.data is not None:
            return self.data.waehrung
        return self.land.waehrung

    async def _async_update_data(self) -> Preisdaten:
        daten = await preise_abrufen(
            self._session,
            self.region,
            self.menge,
            self.einblaspauschale,
            bundesland_vergleich=self.bundesland_vergleich,
        )
        if daten.sackware is None and not ist_landesebene(self.region):
            _LOGGER.debug(
                "%s: die Seite führt derzeit keinen Sackware-Preis", self.region_name
            )
        return daten
