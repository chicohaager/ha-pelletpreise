"""Beobachtete Tief- und Höchstwerte — die eigene Aufzeichnung der Integration.

Der Wert dieser Sensoren stammt **nicht** von heizpellets24. Die Quelle
nennt Tief- und Höchstwerte ausschließlich auf der Landesseite
(``low3Y``/``high3Y`` im Nuxt-Payload); auf den Bundesland-Seiten gibt es sie
nicht. Live nachgemessen am 08.08.2026 (de) bzw. 09.08.2026 (at):

    /pelletpreise         → "low3Y" 2×, "high3Y" 2×
    /pelletpreise/bayern  → "low3Y" 0×, "high3Y" 0×

Derselbe Gegentest auf der Deutschland-Seite belegt, dass die Suche anschlägt,
wenn es etwas zu finden gibt — das Nichtvorhandensein auf der Bundesland-Seite
ist also ein Befund und kein Messfehler.

Deshalb führt die Integration hier selbst Buch: sie merkt sich den niedrigsten
und den höchsten Preis, den sie **selbst gesehen hat**. Damit gilt dieselbe
Regel wie bei der Einblaspauschale in ``berechnung.py``: eine Zahl, die nicht
aus der Quelle stammt, muss am Wert selbst als solche erkennbar bleiben und
nicht nur im Quelltext. Deshalb steht „(beobachtet)" im Sensornamen, deshalb
nennen die Attribute den Beobachtungsbeginn, und deshalb heißt das Datum
``gesehen_am`` — der Sensor sagt damit „seit ich zusehe", nicht „seit jeher".

Bewusst ohne Home-Assistant-Abhängigkeit, damit die Fortschreibungsregel
offline prüfbar bleibt.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from .parser import PLAUSIBEL_MAX, PLAUSIBEL_MIN

MODUS_TIEF: Final = "tief"
MODUS_HOCH: Final = "hoch"


@dataclass(frozen=True)
class Extremwert:
    """Ein festgehaltener Extremwert samt seiner Herkunft in der Zeit.

    Ohne Währung: der Rekord gehört zu genau einem Eintrag, und dessen Region
    — und damit dessen Land und Währung — steht fest, sobald er angelegt ist.
    Ein Eintrag wechselt nie das Land.
    """

    preis_pro_tonne: float
    gesehen_am: str
    """Wann dieser Wert zum **ersten** Mal gesehen wurde (ISO 8601, lokale Zeit)."""

    beobachtet_seit: str
    """Beginn der Aufzeichnung — ohne diese Angabe ist der Wert nicht deutbar.

    Ein Tiefstpreis von 380 €/t bedeutet etwas völlig anderes, je nachdem ob
    seit drei Tagen oder seit zwei Jahren zugesehen wird.
    """


def fortschreiben(
    bisher: Extremwert | None,
    preis: float,
    zeitpunkt: str,
    *,
    modus: str,
) -> Extremwert:
    """Schreibe den Extremwert mit einem neu gesehenen Preis fort.

    Bei Gleichstand bleibt der **erste** Zeitpunkt stehen: gefragt ist, seit
    wann dieser Preis das Extrem ist, nicht wann er zuletzt wieder auftrat.
    Ein täglich mitwanderndes Datum sähe aus wie ein neuer Rekord.
    """
    if modus not in (MODUS_TIEF, MODUS_HOCH):
        raise ValueError(f"Unbekannter Modus: {modus!r}")
    if bisher is None:
        return Extremwert(
            preis_pro_tonne=preis, gesehen_am=zeitpunkt, beobachtet_seit=zeitpunkt
        )
    if modus == MODUS_TIEF:
        ist_neuer_rekord = preis < bisher.preis_pro_tonne
    else:
        ist_neuer_rekord = preis > bisher.preis_pro_tonne
    if not ist_neuer_rekord:
        return bisher
    return Extremwert(
        preis_pro_tonne=preis,
        gesehen_am=zeitpunkt,
        # Der Beobachtungsbeginn ist eine Eigenschaft der Aufzeichnung, nicht
        # des Wertes — er darf bei einem neuen Rekord nicht mitspringen.
        beobachtet_seit=bisher.beobachtet_seit,
    )


# Bis Version 2.2.0 hieß das gespeicherte Feld "euro_pro_tonne". Der Name war
# damals richtig — es gab nur Deutschland. Geschrieben wird jetzt der neutrale
# Name, gelesen werden beide: ein Rekord, den jemand seit Monaten aufzeichnet,
# darf an einer Umbenennung nicht verloren gehen.
FELD_PREIS: Final = "preis_pro_tonne"
FELD_PREIS_ALT: Final = "euro_pro_tonne"


def fuer_speicher(extrem: Extremwert) -> dict[str, Any]:
    """Die Form, in der der Wert einen Neustart überdauert."""
    return {
        FELD_PREIS: extrem.preis_pro_tonne,
        "gesehen_am": extrem.gesehen_am,
        "beobachtet_seit": extrem.beobachtet_seit,
    }


def aus_speicher(rohdaten: Mapping[str, Any] | None) -> Extremwert | None:
    """Lies einen gespeicherten Extremwert zurück.

    ``None`` heißt „nichts gespeichert" — das ist der normale Zustand nach der
    Einrichtung. Ist etwas da, aber unbrauchbar, wird das **laut** als
    ``ValueError`` gemeldet und nicht stillschweigend zu 0 oder zum aktuellen
    Preis gemacht: ein still ersetzter Rekord sähe aus wie ein echter.
    """
    if rohdaten is None:
        return None
    if not isinstance(rohdaten, Mapping):
        raise ValueError(f"Gespeicherter Extremwert ist kein Objekt: {rohdaten!r}")

    if FELD_PREIS in rohdaten:
        preisfeld = FELD_PREIS
    elif FELD_PREIS_ALT in rohdaten:
        preisfeld = FELD_PREIS_ALT
    else:
        # Fehlt beides, ist der Rekord kaputt. In der Meldung steht der
        # heutige Name — der alte würde jemanden auf die Suche nach einem Feld
        # schicken, das neue Aufzeichnungen gar nicht mehr schreiben.
        preisfeld = FELD_PREIS
    fehlend = [
        feld
        for feld in (preisfeld, "gesehen_am", "beobachtet_seit")
        if feld not in rohdaten
    ]
    if fehlend:
        raise ValueError(f"Gespeicherter Extremwert ohne Feld(er): {', '.join(fehlend)}")

    roh_preis = rohdaten[preisfeld]
    if isinstance(roh_preis, bool) or not isinstance(roh_preis, (int, float)):
        raise ValueError(f"Gespeicherter Extremwert ist keine Zahl: {roh_preis!r}")
    preis = float(roh_preis)
    # Dieselbe Sperre wie im Parser: was als Preis nie plausibel war, wird auch
    # als Rekord nicht wieder eingesetzt.
    if not PLAUSIBEL_MIN <= preis <= PLAUSIBEL_MAX:
        raise ValueError(
            f"Gespeicherter Extremwert {preis} je 1.000 kg liegt außerhalb des "
            f"plausiblen Bereichs ({PLAUSIBEL_MIN:.0f}–{PLAUSIBEL_MAX:.0f})."
        )

    zeiten: dict[str, str] = {}
    for feld in ("gesehen_am", "beobachtet_seit"):
        wert = rohdaten[feld]
        if not isinstance(wert, str):
            raise ValueError(f"Gespeichertes Feld {feld} ist kein Text: {wert!r}")
        try:
            datetime.fromisoformat(wert)
        except ValueError as err:
            raise ValueError(
                f"Gespeichertes Feld {feld} ist kein Zeitstempel: {wert!r}"
            ) from err
        zeiten[feld] = wert

    return Extremwert(
        preis_pro_tonne=preis,
        gesehen_am=zeiten["gesehen_am"],
        beobachtet_seit=zeiten["beobachtet_seit"],
    )
