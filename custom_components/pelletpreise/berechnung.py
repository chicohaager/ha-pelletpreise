"""Hochrechnung der Gesamtpreise — bewusst ohne Home-Assistant-Abhängigkeit.

Hier steht die einzige Stelle, an der eine **selbst eingetragene** Zahl in einen
Preis einfließt: die Einblaspauschale. Alles andere kommt aus dem Parser und
damit von heizpellets24.de.

Genau deshalb liegt das hier getrennt und ohne Framework: die Rechnung muss
jederzeit offline prüfbar sein, und der Unterschied zwischen "von der Quelle
gelesen" und "vom Nutzer eingetragen" darf flussabwärts nicht verschwinden.
``berechnungstext`` schreibt diesen Unterschied deshalb in jedes Attribut
mit hinein — eine hinzugerechnete Konstante, die im Sensor wie ein Messwert
aussieht, ist ein Fehler, keine Bequemlichkeit.

Die Einblaspauschale gilt **nur für lose Ware**. Die Quelle sagt das im
Kleingedruckten unter ihrem Preis selbst — wortgleich auf allen drei
Landesseiten (de/at/ch, nachgemessen am 09.08.2026):

    "Preis inkl. MwSt. und Lieferung (lose Pellets zzgl. Einblaspauschale)."

Sackware wird auf Paletten geliefert und nicht eingeblasen; dort wäre der
Zuschlag frei erfunden.

Die Währung wird durchgereicht, nie angenommen: Schweizer Preise stehen in
CHF. Eine Funktion, die intern "€" anhängt, würde einen CHF-Betrag beschriften,
ohne dass es irgendwo auffiele — genau die Sorte stiller Fehler, gegen die
dieses Modul überhaupt getrennt liegt.
"""

from __future__ import annotations

from .const import MAX_EINBLASPAUSCHALE, MIN_EINBLASPAUSCHALE
from .parser import REFERENZMENGE_KG


def betrag_text(wert: float, waehrung: str) -> str:
    """Formatiere einen Betrag für die Anzeige in Attributen.

    Dezimaltrennzeichen nach Landesbrauch: im deutschsprachigen Raum das
    Komma, in der Schweiz der Punkt (dort schreibt man 522.12 CHF). Die
    Währung kommt von der Quelle und wird hier nur angehängt.
    """
    if waehrung == "CHF":
        return f"{wert:.2f} CHF"
    return f"{wert:.2f}".replace(".", ",") + f" {waehrung}"


def pruefe_einblaspauschale(betrag: float) -> float:
    """Lass keinen unsinnigen Zuschlag in eine Preisangabe laufen.

    Kein Zurechtbiegen auf einen gültigen Wert: eine stillschweigend auf 0
    gesetzte Pauschale sähe im Sensor genauso aus wie eine bewusst nicht
    eingetragene, und ein negativer Betrag würde den Gesamtpreis senken, ohne
    dass irgendwo etwas auffiele. Beides wird deshalb laut abgelehnt.
    """
    try:
        wert = float(betrag)
    except (TypeError, ValueError) as err:
        raise ValueError(
            f"Einblaspauschale: {betrag!r} ist keine Zahl."
        ) from err
    if not MIN_EINBLASPAUSCHALE <= wert <= MAX_EINBLASPAUSCHALE:
        raise ValueError(
            f"Einblaspauschale: {wert} liegt außerhalb des zulässigen "
            f"Bereichs ({MIN_EINBLASPAUSCHALE:.0f}–{MAX_EINBLASPAUSCHALE:.0f}). "
            "Der Bereich ist keine Marktaussage, sondern eine Tippfehlersperre: "
            "ein verrutschtes Komma soll nicht unbemerkt im Gesamtpreis landen."
        )
    return wert


def warenwert(preis_pro_tonne: float, menge_kg: int) -> float:
    """Der reine Warenwert der Bestellmenge, ohne jeden Zuschlag.

    Lineare Hochrechnung vom Referenzpreis der Quelle — siehe
    ``berechnungstext``. Währungsblind: der Wert steht in derselben Währung
    wie der übergebene Preis.
    """
    return round(preis_pro_tonne * menge_kg / 1000, 2)


def gesamtpreis(
    preis_pro_tonne: float, menge_kg: int, einblaspauschale: float = 0.0
) -> float:
    """Warenwert plus Einblaspauschale.

    Die Pauschale wird **nicht** in den Preis je Tonne eingerechnet, sondern
    einmal auf die Bestellung geschlagen — sie fällt je Lieferung an, nicht je
    Tonne. Wer sie in den €/t-Wert mischte, hätte einen Marktpreis, der es
    nicht mehr ist, und einen Verlauf, der beim Ändern der Bestellmenge
    springt.
    """
    return round(
        warenwert(preis_pro_tonne, menge_kg)
        + pruefe_einblaspauschale(einblaspauschale),
        2,
    )


def berechnungstext(
    menge_kg: int, einblaspauschale: float = 0.0, waehrung: str = "€"
) -> str:
    """Sagt im Klartext, wie der Gesamtpreis zustande kam.

    Landet als Attribut ``berechnung`` am Sensor. Der Text nennt die Pauschale
    ausdrücklich als eigene Eingabe, damit niemand sie später für einen von
    heizpellets24.de gelesenen Wert hält.
    """
    text = f"Referenzpreis × {menge_kg} kg ÷ 1000"
    if einblaspauschale:
        text += f" + {betrag_text(einblaspauschale, waehrung)} Einblaspauschale"
    text += (
        " — lineare Hochrechnung. Die Quelle nennt ihren Preis für "
        f"{REFERENZMENGE_KG} kg Gesamtabnahme; tatsächliche Angebote sind "
        "mengenabhängig."
    )
    if einblaspauschale:
        text += (
            " Die Einblaspauschale ist der von dir eingetragene Betrag und "
            "stammt nicht von heizpellets24."
        )
    return text
