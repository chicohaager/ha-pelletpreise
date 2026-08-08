"""Konstanten der Pelletpreise-Integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "pelletpreise"

# Konfigurationsschlüssel
CONF_REGION: Final = "region"
CONF_MENGE: Final = "menge"
CONF_EINBLASPAUSCHALE: Final = "einblaspauschale"
CONF_BUNDESLAND_VERGLEICH: Final = "bundesland_vergleich"

# Auswahlmöglichkeiten für die Region.
#
# Die Slugs sind die URL-Bestandteile von heizpellets24.de und stammen aus dem
# Seiten-Payload (Feld `countryStates[].friendlyName`); sie wurden zusätzlich
# gegen die tatsächlich verlinkten /pelletpreise/<slug>-Adressen geprüft.
# Nicht raten: ein falscher Slug liefert die Deutschland-Seite und damit
# stillschweigend den falschen Preis.
REGION_DEUTSCHLAND: Final = "deutschland"

BUNDESLAENDER: Final[dict[str, str]] = {
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

# Kurz halten: der Name landet im Gerätenamen und damit in jeder Entitäts-ID.
# "Deutschland (Bundesdurchschnitt)" ergäbe Entitäten wie
# sensor.pelletpreise_deutschland_bundesdurchschnitt_lose_ware — die Erklärung
# steht besser im Einrichtungsdialog als in jeder ID.
REGIONEN: Final[dict[str, str]] = {
    REGION_DEUTSCHLAND: "Deutschland",
    **BUNDESLAENDER,
}

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
DEFAULT_EINBLASPAUSCHALE: Final = 0.0
MIN_EINBLASPAUSCHALE: Final = 0.0
# Obergrenze als Tippfehlersperre, nicht als Marktaussage: sie soll ein
# verrutschtes Komma abfangen, bevor es unbemerkt im Gesamtpreis landet.
MAX_EINBLASPAUSCHALE: Final = 500.0

# Bundesland-Vergleich (günstigstes/teuerstes Bundesland).
#
# Vorgabe aus: die Deutschland-Seite liefert die Bundesland-Tabelle nicht mit,
# der Vergleich kostet deshalb 16 zusätzliche Seitenabrufe je Aktualisierung.
# Das ist Last auf einer fremden Website und gehört nicht ungefragt zum
# Standardbetrieb — wer den Vergleich will, schaltet ihn ein.
DEFAULT_BUNDESLAND_VERGLEICH: Final = False

# Wie viele der 16 Seiten gleichzeitig geholt werden. Vier ist ein Kompromiss:
# nacheinander dauerte der Abruf unnötig lange, alle 16 auf einmal wäre für
# eine fremde Seite unhöflich.
VERGLEICH_PARALLEL: Final = 4

# Abrufintervall. Die Quelle aktualisiert einmal täglich; häufigeres Abrufen
# brächte keine neuen Daten und belastete eine fremde Website ohne Nutzen.
UPDATE_INTERVAL_HOURS: Final = 12

ATTRIBUTION: Final = "Daten von heizpellets24.de"

# Für die selbst aufgezeichneten Extremwerte gilt diese Angabe **nicht**
# unverändert: der einzelne Preis stammt von dort, die Aussage „das ist der
# tiefste seit …" nicht. Am Sensor stünde sonst wörtlich „Daten von
# heizpellets24.de" direkt neben dem Hinweis „Keine Angabe von
# heizpellets24.de" — eine Quellenangabe ist eine Behauptung über die
# Herkunft und muss zum Wert passen, an dem sie hängt.
ATTRIBUTION_BEOBACHTET: Final = (
    "Preise von heizpellets24.de, Aufzeichnung durch diese Integration"
)

# Für welche Regionen ein Sensor überhaupt Daten haben kann. Die Quelle führt
# Sackware nur auf den Bundesland-Seiten und die Langfristwerte nur auf der
# Deutschland-Seite; Entitäten, die nie einen Wert bekommen können, werden gar
# nicht erst angelegt.
BEREICH_IMMER: Final = "immer"
BEREICH_NUR_BUNDESLAND: Final = "nur_bundesland"
BEREICH_NUR_DEUTSCHLAND: Final = "nur_deutschland"


def passt_zur_region(bereich: str, region: str) -> bool:
    """Kann ein Sensor dieses Bereichs in dieser Region Daten haben?"""
    if bereich == BEREICH_IMMER:
        return True
    ist_deutschland = region == REGION_DEUTSCHLAND
    if bereich == BEREICH_NUR_DEUTSCHLAND:
        return ist_deutschland
    if bereich == BEREICH_NUR_BUNDESLAND:
        return not ist_deutschland
    raise ValueError(f"Unbekannter Sensorbereich: {bereich!r}")
