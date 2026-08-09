"""Konstanten der Pelletpreise-Integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

DOMAIN: Final = "pelletpreise"

# Konfigurationsschlüssel
CONF_LAND: Final = "land"
CONF_REGION: Final = "region"
CONF_MENGE: Final = "menge"
CONF_EINBLASPAUSCHALE: Final = "einblaspauschale"
CONF_BUNDESLAND_VERGLEICH: Final = "bundesland_vergleich"

# Währungszeichen, wie die Quelle sie selbst im Nuxt-Payload führt (Feld
# `currency`). Sie stehen hier **nicht**, um die Einheit zu setzen — die liest
# der Parser aus der Seite. Sie stehen hier als Gegenprobe: weicht die gelesene
# Währung von der erwarteten ab, bricht der Abruf ab, statt einen CHF-Betrag
# mit einem Eurozeichen zu beschriften.
#
# Live gemessen am 09.08.2026:
#   heizpellets24.de/pelletpreise → currency:"€"
#   heizpellets24.at/pelletpreise → currency:"€"
#   heizpellets24.ch/pelletpreise → currency:"CHF"
WAEHRUNG_EUR: Final = "€"
WAEHRUNG_CHF: Final = "CHF"


@dataclass(frozen=True)
class Land:
    """Ein Land samt seiner Seite, seiner Währung und seiner Unterregionen."""

    code: str
    """Länderkürzel, zugleich die Top-Level-Domain der Quelle."""

    name: str
    landesregion: str
    """Slug der Landesebene — die Seite ohne Regionszusatz."""

    waehrung: str
    """Erwartete Währung. Gegenprobe zum gelesenen Wert, siehe oben."""

    unterregionen: dict[str, str] = field(default_factory=dict)
    """Slug → Name. Leer, wenn die Quelle für dieses Land keine echten
    Regionalpreise führt (Schweiz, siehe unten)."""

    @property
    def host(self) -> str:
        return f"www.heizpellets24.{self.code}"

    @property
    def basis_url(self) -> str:
        return f"https://{self.host}/pelletpreise"

    @property
    def attribution(self) -> str:
        return f"Daten von {self.host}"

    @property
    def regionen(self) -> dict[str, str]:
        return {self.landesregion: self.name, **self.unterregionen}


# Die Slugs sind die URL-Bestandteile von heizpellets24 und stammen aus dem
# Seiten-Payload (Feld `countryStates[].friendlyName`); sie wurden zusätzlich
# gegen die tatsächlich verlinkten /pelletpreise/<slug>-Adressen geprüft
# (Test `test_slugs_entsprechen_den_urls_der_quelle`, je Land).
# Nicht raten: ein falscher Slug liefert die Landesseite und damit
# stillschweigend den falschen Preis.
REGION_DEUTSCHLAND: Final = "deutschland"
REGION_OESTERREICH: Final = "oesterreich"
REGION_SCHWEIZ: Final = "schweiz"

LAND_DE: Final = "de"
LAND_AT: Final = "at"
LAND_CH: Final = "ch"

BUNDESLAENDER_DE: Final[dict[str, str]] = {
    "baden-wuerttemberg": "Baden-Württemberg",
    "bayern": "Bayern",
    "berlin": "Berlin",
    "brandenburg": "Brandenburg",
    "bremen": "Bremen",
    "hamburg": "Hamburg",
    "hessen": "Hessen",
    "mecklenburg-vorpommern": "Mecklenburg-Vorpommern",
    "niedersachsen": "Niedersachsen",
    "nordrhein-westfalen": "Nordrhein-Westfalen",
    "rheinland-pfalz": "Rheinland-Pfalz",
    "saarland": "Saarland",
    "sachsen": "Sachsen",
    "sachsen-anhalt": "Sachsen-Anhalt",
    "schleswig-holstein": "Schleswig-Holstein",
    "thueringen": "Thüringen",
}

BUNDESLAENDER_AT: Final[dict[str, str]] = {
    "burgenland": "Burgenland",
    "kaernten": "Kärnten",
    "niederoesterreich": "Niederösterreich",
    "oberoesterreich": "Oberösterreich",
    "salzburg": "Salzburg",
    "steiermark": "Steiermark",
    "tirol": "Tirol",
    "vorarlberg": "Vorarlberg",
    "wien": "Wien",
}

# Schweiz: **bewusst ohne Kantone.**
#
# Die Quelle hat zwar 26 Kantonsseiten, sie führen aber keine eigenen Preise.
# Live nachgemessen am 09.08.2026 über alle 26 Seiten:
#
#   * 14 Kantone liefern gar keinen Preis (Wert 0) — u.a. Genf, Luzern,
#     Tessin, Waadt, Wallis, Zug, Graubünden.
#   * die übrigen 12 liefern ausnahmslos exakt die Landeszahl
#     (522,12 CHF/t lose, 504,04 CHF/t Sackware) — dieselbe Zahl, die auch
#     /pelletpreise selbst nennt.
#
# 26 Kantone zur Auswahl zu stellen hieße also, eine Auflösung vorzutäuschen,
# die die Quelle nicht hat: die Hälfte der Einträge wäre dauerhaft "nicht
# verfügbar", die andere Hälfte zeigte denselben Wert wie "Schweiz", und ein
# Kantonsvergleich wäre ein zwölffacher Gleichstand. Das ist dieselbe
# Begründung, aus der die Integration keine Postleitzahl abfragt.
#
# Der Live-Test `test_die_kantonsseiten_fuehren_keinen_eigenen_preis` hält
# diesen Befund nach — mit den deutschen Bundesländern als Positivkontrolle.
# Schlägt er eines Tages fehl, weil die Kantone eigene Preise bekommen, ist
# das eine gute Nachricht und der Anlass, sie hier einzutragen.
LAENDER: Final[dict[str, Land]] = {
    LAND_DE: Land(
        code=LAND_DE,
        name="Deutschland",
        landesregion=REGION_DEUTSCHLAND,
        waehrung=WAEHRUNG_EUR,
        unterregionen=BUNDESLAENDER_DE,
    ),
    LAND_AT: Land(
        code=LAND_AT,
        name="Österreich",
        landesregion=REGION_OESTERREICH,
        waehrung=WAEHRUNG_EUR,
        unterregionen=BUNDESLAENDER_AT,
    ),
    LAND_CH: Land(
        code=LAND_CH,
        name="Schweiz",
        landesregion=REGION_SCHWEIZ,
        waehrung=WAEHRUNG_CHF,
        unterregionen={},
    ),
}

# Rückwärtskompatibler Name: vor der Länder-Erweiterung hieß die deutsche
# Liste so, und `bundesland_vergleich` heißt in Optionen und Übersetzungen
# weiterhin so. In Deutschland wie in Österreich sind die Unterregionen
# tatsächlich Bundesländer — der Name lügt also nicht.
BUNDESLAENDER: Final[dict[str, str]] = BUNDESLAENDER_DE


def _regionen_zusammenfuehren() -> tuple[dict[str, str], dict[str, str]]:
    """Baue die flache Regionsliste — und lehne Doppelungen laut ab.

    Der Slug ist zugleich die ``unique_id`` eines Eintrags. Käme derselbe Slug
    in zwei Ländern vor, ließe sich das zweite Land gar nicht einrichten
    ("bereits konfiguriert") — und zwar stillschweigend, mit einer Meldung,
    die auf etwas ganz anderes hindeutet. Deshalb fällt das hier beim Import
    auf und nicht beim Nutzer.
    """
    regionen: dict[str, str] = {}
    land_je_region: dict[str, str] = {}
    for land in LAENDER.values():
        for slug, name in land.regionen.items():
            if slug in regionen:
                raise ValueError(
                    f"Regionsslug {slug!r} kommt in {LAENDER[land_je_region[slug]].name} "
                    f"und in {land.name} vor. Slugs sind zugleich die unique_id "
                    "eines Eintrags und müssen über alle Länder eindeutig sein."
                )
            regionen[slug] = name
            land_je_region[slug] = land.code
    return regionen, land_je_region


REGIONEN, LAND_JE_REGION = _regionen_zusammenfuehren()


def land_von_region(region: str) -> Land:
    """Zu welchem Land gehört diese Region?

    Kein Rückfall auf Deutschland: eine unbekannte Region würde sonst
    stillschweigend deutsche Preise anzeigen. Lieber laut scheitern.
    """
    code = LAND_JE_REGION.get(region)
    if code is None:
        raise ValueError(
            f"Unbekannte Region: {region!r}. Bekannt sind: {sorted(REGIONEN)}."
        )
    return LAENDER[code]


def ist_landesebene(region: str) -> bool:
    """Ist das die Landesseite (Deutschland/Österreich/Schweiz)?"""
    return region == land_von_region(region).landesregion


# Bestellmenge
DEFAULT_MENGE: Final = 6000  # entspricht der Bezugsmenge der Quelle
MIN_MENGE: Final = 500
MAX_MENGE: Final = 30000

# Einblaspauschale, die der Händler je Lieferung berechnet.
#
# Vorgabe 0: die Quelle nennt keinen solchen Betrag — sie schreibt unter ihrem
# Preis ausdrücklich "lose Pellets zzgl. Einblaspauschale" und lässt die Höhe
# offen, weil sie je Händler verschieden ist. Ein hier voreingestellter
# "üblicher" Wert wäre geraten und stünde am Ende als Zahl im Gesamtpreis.
# Lieber 0 und sichtbar leer als ein plausibel aussehender Erfindungswert.
#
# (proPellets Austria beziffert die durchschnittliche Einblaspauschale in
# Österreich mit ca. 53,80 € je Zustellung. Auch das bleibt hier bewusst
# keine Vorgabe: es ist ein Landesdurchschnitt eines Verbands und nicht der
# Betrag, den der eigene Händler auf die Rechnung schreibt.)
DEFAULT_EINBLASPAUSCHALE: Final = 0.0
MIN_EINBLASPAUSCHALE: Final = 0.0
# Obergrenze als Tippfehlersperre, nicht als Marktaussage: sie soll ein
# verrutschtes Komma abfangen, bevor es unbemerkt im Gesamtpreis landet.
MAX_EINBLASPAUSCHALE: Final = 500.0

# Bundesland-Vergleich (günstigstes/teuerstes Bundesland).
#
# Vorgabe aus: die Landesseite liefert die Bundesland-Tabelle nicht mit, der
# Vergleich kostet deshalb einen zusätzlichen Seitenabruf je Bundesland
# (Deutschland 16, Österreich 9). Das ist Last auf einer fremden Website und
# gehört nicht ungefragt zum Standardbetrieb — wer den Vergleich will,
# schaltet ihn ein. In der Schweiz gibt es ihn gar nicht: ohne Unterregionen
# gäbe es nichts zu vergleichen.
DEFAULT_BUNDESLAND_VERGLEICH: Final = False

# Wie viele Seiten gleichzeitig geholt werden. Vier ist ein Kompromiss:
# nacheinander dauerte der Abruf unnötig lange, alle auf einmal wäre für eine
# fremde Seite unhöflich.
VERGLEICH_PARALLEL: Final = 4

# Abrufintervall. Die Quelle aktualisiert einmal täglich; häufigeres Abrufen
# brächte keine neuen Daten und belastete eine fremde Website ohne Nutzen.
UPDATE_INTERVAL_HOURS: Final = 12


def attribution(land: Land) -> str:
    """Quellenangabe für die Sensoren eines Landes."""
    return land.attribution


def attribution_beobachtet(land: Land) -> str:
    """Quellenangabe für die selbst aufgezeichneten Extremwerte.

    Für sie gilt die Angabe oben **nicht** unverändert: der einzelne Preis
    stammt von dort, die Aussage „das ist der tiefste seit …" nicht. Am Sensor
    stünde sonst wörtlich „Daten von heizpellets24.de" direkt neben dem Hinweis
    „Keine Angabe von heizpellets24.de" — eine Quellenangabe ist eine
    Behauptung über die Herkunft und muss zum Wert passen, an dem sie hängt.
    """
    return f"Preise von {land.host}, Aufzeichnung durch diese Integration"


# Für welche Regionen ein Sensor überhaupt Daten haben kann. Die Quelle führt
# Sackware nur auf den Bundesland-Seiten und die Langfristwerte nur auf der
# Landesseite; Entitäten, die nie einen Wert bekommen können, werden gar nicht
# erst angelegt.
BEREICH_IMMER: Final = "immer"
BEREICH_NUR_UNTERREGION: Final = "nur_unterregion"
BEREICH_NUR_LANDESEBENE: Final = "nur_landesebene"


def passt_zur_region(bereich: str, region: str) -> bool:
    """Kann ein Sensor dieses Bereichs in dieser Region Daten haben?"""
    if bereich == BEREICH_IMMER:
        return True
    if bereich == BEREICH_NUR_LANDESEBENE:
        return ist_landesebene(region)
    if bereich == BEREICH_NUR_UNTERREGION:
        return not ist_landesebene(region)
    raise ValueError(f"Unbekannter Sensorbereich: {bereich!r}")
