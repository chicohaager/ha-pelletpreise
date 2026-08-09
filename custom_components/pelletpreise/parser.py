"""Parser für die Preisdaten von heizpellets24 (de/at/ch).

Die Seite ist eine Nuxt-Anwendung. Die Preiszahlen stehen **nicht** im
gerenderten HTML der Tabelle (die füllt JavaScript nach), sondern im
server-gelieferten Nuxt-Payload am Seitenende:

    window.__NUXT__=(function(a,b,c,...){return {...}}(false,null,true,...));

Der Payload ist minifiziert: Werte, die mehrfach vorkommen, sind durch die
Parameternamen der äußeren Funktion ersetzt. Um an eine Zahl zu kommen, muss
man die Parameterliste auf die Argumentliste abbilden und den Namen auflösen.

Dieses Modul tut genau das — und **nichts darüber hinaus**. Es rät nie einen
Preis. Findet es die erwartete Struktur nicht, wirft es `ParseError` mit der
Angabe, was gefehlt hat. Ein falscher Preis wäre schlimmer als gar keiner:
Nutzer treffen damit Kaufentscheidungen über mehrere hundert Euro.

Dieselbe Seitentechnik läuft unter allen drei Landesdomains. Nachgemessen
am 09.08.2026: ``heizpellets24.at/pelletpreise`` und
``heizpellets24.ch/pelletpreise`` liefern denselben Payload-Aufbau
(``countryAvg``, ``localPrices``, ``low3Y``/``high3Y``) wie die deutsche Seite
und dasselbe Kleingedruckte (6.000 kg Bezugsmenge, inkl. MwSt. und Lieferung,
zzgl. Einblaspauschale). Unterschiedlich ist die **Währung**: die Schweizer
Seite führt ``currency:"CHF"``. Sie wird deshalb hier mitgelesen und nicht
angenommen — ein CHF-Betrag mit einem Eurozeichen daneben wäre genau die Art
Fehler, gegen die dieses Modul sonst so sorgfältig ist.

Alle hier verwendeten Seiten sind laut robots.txt für ``User-agent: *``
freigegeben (für alle drei Domains geprüft). Die dort gesperrten Pfade
(/ajaxcontent/, /JsonHandler.ashx, /ChartHandler.ashx) werden bewusst
**nicht** angefasst.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# Produkt-IDs, wie sie der Payload selbst in `groups[].defaultParams.productId`
# zusammen mit `calculationUrl` führt — nicht geraten, sondern dort abgelesen.
PRODUCT_ID_LOSE: Final = 20  # "Holzpellets lose",     calculationUrl: holzpellets-lose
PRODUCT_ID_SACKWARE: Final = 23  # "Holzpellets Sackware", calculationUrl: holzpellets-sackware

# Die Seite nennt ihre Bezugsgröße im Kleingedruckten unter dem Preis:
# "…Durchschnittspreis für <Land> auf Basis des günstigsten Händlerangebots je
#  PLZ bei Gesamtabnahme von 6.000 kg Holzpellets. Preis inkl. MwSt. und
#  Lieferung (lose Pellets zzgl. Einblaspauschale)."
REFERENZMENGE_KG: Final = 6000

# Preise werden als Währung/1.000 kg geführt (Spaltenkopf der
# Bundesland-Tabelle: "Ø €/1.000kg Preis bei 6.000kg Gesamtabnahme", auf der
# Schweizer Seite "CHF/1.000kg").
#
# Der Bereich dient **nicht** dazu, einen Wert zurechtzubiegen, sondern nur
# dazu, offensichtlichen Parse-Müll als Fehler sichtbar zu machen. Er ist
# absichtlich weit: der deutsche 3-Jahres-Tiefstwert lag bei 242,92 €/t, der
# Höchstwert der Energiekrise 2022 deutlich über 700 €/t, und die Schweizer
# Preise liegen in CHF nochmals rund ein Viertel höher (522,12 CHF/t am
# 09.08.2026). Ein und derselbe Bereich deckt beide Währungen ab, weil er
# ohnehin nur Größenordnungen ausschließt.
PLAUSIBEL_MIN: Final = 100.0
PLAUSIBEL_MAX: Final = 1500.0


class ParseError(Exception):
    """Die erwartete Struktur war nicht auffindbar.

    Wird bewusst nach oben durchgereicht, damit Home Assistant den Fehler
    anzeigt, statt einen Platzhalterwert zu übernehmen.
    """


class KeinAngebot(ParseError):
    """Die Seite war lesbar, führt für diese Region aber keinen Preis.

    Ausdrücklich **kein** Lesefehler, sondern eine Auskunft der Quelle: sie
    trägt 0 ein, wo es kein Angebot gibt. Belegt am 09.08.2026 für Vorarlberg
    und für 14 der 26 Schweizer Kantone.

    Der Unterschied ist wichtig, weil beide Fälle verschieden behandelt
    gehören: für einen einzelnen Regionseintrag bleibt es ein Grund, den
    Sensor auf „nicht verfügbar" zu setzen (ein Preis, den es nicht gibt, darf
    nicht ersetzt werden). Im Bundesland-Vergleich dagegen ist es kein Grund,
    den ganzen Vergleich hinzuwerfen — die Region gehört dort unter
    ``ohne_angebot``, sichtbar am Sensor.
    """


@dataclass(frozen=True)
class Preis:
    """Ein einzelner Preispunkt."""

    preis_pro_tonne: float
    """Preis je 1.000 kg, inkl. MwSt. und Lieferung — in ``waehrung``."""

    waehrung: str
    """Währungszeichen, wie die Seite es selbst führt ("€" oder "CHF").

    Steht am Preis und nicht als Konstante daneben: eine hinzugedachte
    Währung wäre flussabwärts nicht mehr von einer gelesenen zu unterscheiden.
    """

    aenderung_prozent_woche: float | None
    """Veränderung gegenüber der Vorwoche in Prozent, falls die Seite sie nennt."""


@dataclass(frozen=True)
class Regionalpreise:
    """Was eine Bundesland-Seite hergibt."""

    lose: Preis
    sackware: Preis | None
    """None, wenn die Seite für diese Region keine Sackware führt (Preis 0)."""


@dataclass(frozen=True)
class Landespreise:
    """Was eine Landesseite hergibt (Deutschland, Österreich, Schweiz)."""

    lose: Preis
    differenz_woche: float | None
    differenz_3monate: float | None
    tief_3jahre: float | None
    hoch_3jahre: float | None
    schnitt_3jahre: float | None

    @property
    def waehrung(self) -> str:
        return self.lose.waehrung


# --------------------------------------------------------------------------
# Nuxt-Payload
# --------------------------------------------------------------------------


def _split_top_level(text: str) -> list[str]:
    """Zerlege eine Argumentliste an Kommas der obersten Ebene.

    ``str.split(",")`` reicht nicht: Argumente enthalten Objekte, Arrays und
    Strings mit Kommas darin.
    """
    teile: list[str] = []
    tiefe = 0
    quote: str | None = None
    aktuell: list[str] = []
    i = 0
    while i < len(text):
        zeichen = text[i]
        if quote is not None:
            aktuell.append(zeichen)
            if zeichen == "\\" and i + 1 < len(text):
                aktuell.append(text[i + 1])
                i += 2
                continue
            if zeichen == quote:
                quote = None
            i += 1
            continue
        if zeichen in "\"'":
            quote = zeichen
            aktuell.append(zeichen)
            i += 1
            continue
        if zeichen in "([{":
            tiefe += 1
        elif zeichen in ")]}":
            tiefe -= 1
        if zeichen == "," and tiefe == 0:
            teile.append("".join(aktuell))
            aktuell = []
            i += 1
            continue
        aktuell.append(zeichen)
        i += 1
    teile.append("".join(aktuell))
    return teile


class NuxtPayload:
    """Der Nuxt-Payload einer Seite samt Auflösung der minifizierten Namen."""

    def __init__(self, html: str) -> None:
        start = html.find("window.__NUXT__")
        if start < 0:
            raise ParseError(
                "Kein 'window.__NUXT__' im HTML gefunden. Entweder hat "
                "heizpellets24.de die Seitentechnik gewechselt, oder die "
                "Antwort war gar keine Preisseite (z.B. eine Fehler- oder "
                "Consent-Seite)."
            )
        ende = html.find("</script>", start)
        if ende < 0:
            raise ParseError("Der Nuxt-Payload war unvollständig (kein </script>).")
        self._rohtext = html[start:ende]

        kopf = re.search(r"window\.__NUXT__=\(function\(([^)]*)\)", self._rohtext)
        if kopf is None:
            raise ParseError(
                "Der Nuxt-Payload hat nicht die erwartete Form "
                "'window.__NUXT__=(function(...)'."
            )
        parameter = [p.strip() for p in kopf.group(1).split(",") if p.strip()]

        aufruf = self._rohtext.rfind("}(")
        if aufruf < 0:
            raise ParseError("Im Nuxt-Payload fehlte die Argumentliste ('}(').")
        argumenttext = self._rohtext[aufruf + 2 :].strip().rstrip(";").strip()
        if not argumenttext.endswith("))"):
            raise ParseError("Die Argumentliste des Nuxt-Payloads war nicht abgeschlossen.")
        argumente = [a.strip() for a in _split_top_level(argumenttext[:-2])]

        if len(parameter) != len(argumente):
            raise ParseError(
                f"Nuxt-Payload: {len(parameter)} Parameter, aber "
                f"{len(argumente)} Argumente — die Zuordnung wäre geraten."
            )
        self._namen = dict(zip(parameter, argumente))

    @property
    def rohtext(self) -> str:
        return self._rohtext

    def aufloesen(self, ausdruck: str, _tiefe: int = 0) -> str:
        """Löse einen minifizierten Namen zu seinem Wert auf."""
        ausdruck = ausdruck.strip()
        if _tiefe > 10:
            raise ParseError(f"Namensauflösung im Nuxt-Payload dreht sich im Kreis: {ausdruck!r}")
        if re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", ausdruck) and ausdruck in self._namen:
            return self.aufloesen(self._namen[ausdruck], _tiefe + 1)
        return ausdruck

    def zahl(self, ausdruck: str, bezeichnung: str) -> float | None:
        """Löse einen Ausdruck auf und lies ihn als Zahl.

        Gibt None zurück, wenn die Seite dort ausdrücklich nichts stehen hat
        (``null``/``undefined``) — das ist ein legitimer Zustand, kein Fehler.
        """
        wert = self.aufloesen(ausdruck)
        if wert in ("null", "undefined", "void 0", ""):
            return None
        if not re.fullmatch(r"-?(?:\d+\.?\d*|\.\d+)", wert):
            raise ParseError(
                f"{bezeichnung}: erwartete eine Zahl, fand {wert!r}. "
                "heizpellets24.de hat vermutlich das Datenformat geändert."
            )
        return float(wert)

    def text(self, ausdruck: str, bezeichnung: str) -> str:
        """Löse einen Ausdruck auf und lies ihn als Zeichenkette.

        Für die Währung. Ein leerer oder fehlender Wert ist hier **kein**
        legitimer Zustand: ohne Währung wäre der Preis daneben eine Zahl ohne
        Einheit, und die einzige Möglichkeit, sie zu beschriften, wäre Raten.
        """
        wert = self.aufloesen(ausdruck)
        if len(wert) >= 2 and wert[0] == wert[-1] and wert[0] in "\"'":
            wert = wert[1:-1]
        wert = wert.strip()
        if not wert or wert in ("null", "undefined", "void 0"):
            raise ParseError(
                f"{bezeichnung}: die Seite nennt keine Währung. Ohne sie wäre "
                "der Preis eine Zahl ohne Einheit."
            )
        return wert


def _pruefe_plausibel(preis: float, waehrung: str, bezeichnung: str) -> float:
    """Lass offensichtlichen Parse-Müll nicht als Preis durchgehen."""
    if not PLAUSIBEL_MIN <= preis <= PLAUSIBEL_MAX:
        raise ParseError(
            f"{bezeichnung}: {preis} {waehrung}/1.000 kg liegt außerhalb des "
            f"plausiblen Bereichs ({PLAUSIBEL_MIN:.0f}–{PLAUSIBEL_MAX:.0f}). "
            "Das ist mit hoher Wahrscheinlichkeit kein Preis, sondern ein "
            "Parse-Fehler — der Wert wird deshalb verworfen."
        )
    return preis


# --------------------------------------------------------------------------
# Öffentliche Parser
# --------------------------------------------------------------------------


def parse_bundesland(html: str, bezeichnung: str = "Bundesland") -> Regionalpreise:
    """Lies lose Ware und Sackware aus einer Bundesland-Seite.

    Die Seite liefert unter ``pricing.localPrices`` ein Objekt je Produkt-ID.
    Gilt gleichermaßen für die deutschen und die österreichischen
    Bundeslandseiten — nachgemessen am 09.08.2026 über alle 16 + 9 Seiten.
    """
    payload = NuxtPayload(html)
    treffer = re.search(r"localPrices:\{(.*?)\},selectedGroups", payload.rohtext, re.DOTALL)
    if treffer is None:
        raise ParseError(
            f"{bezeichnung}: kein 'localPrices'-Block im Nuxt-Payload. "
            "Auf Landesebene gibt es diesen Block nicht — wurde "
            "versehentlich die falsche Seite abgerufen?"
        )

    eintraege: dict[int, tuple[str, str, str]] = {}
    for produkt_id, inhalt in re.findall(r'"(\d+)":\{(.*?)\}', treffer.group(1)):
        preis = re.search(r"price:([^,}]+)", inhalt)
        aenderung = re.search(r"changePercent:([^,}]+)", inhalt)
        waehrung = re.search(r"currency:([^,}]+)", inhalt)
        if preis is None or waehrung is None:
            continue
        eintraege[int(produkt_id)] = (
            preis.group(1),
            aenderung.group(1) if aenderung else "null",
            waehrung.group(1),
        )

    if not eintraege:
        raise ParseError(
            f"{bezeichnung}: der Block 'localPrices' war leer. So liefert "
            "heizpellets24 die Landesseite aus — für Regionalpreise muss eine "
            "Bundesland-Seite abgerufen werden."
        )
    if PRODUCT_ID_LOSE not in eintraege:
        raise ParseError(
            f"{bezeichnung}: keine Preisangabe für lose Ware "
            f"(Produkt-ID {PRODUCT_ID_LOSE}) in 'localPrices'. Gefundene "
            f"Produkt-IDs: {sorted(eintraege)}."
        )

    def lies(produkt_id: int, name: str) -> Preis | None:
        roh_preis, roh_aenderung, roh_waehrung = eintraege[produkt_id]
        preis = payload.zahl(roh_preis, f"{bezeichnung}/{name}: Preis")
        # Die Seite trägt 0 ein, wenn es für die Region kein Angebot gibt
        # (z.B. Big Bags). Das ist "keine Daten", nicht "kostenlos".
        if preis is None or preis == 0:
            return None
        waehrung = payload.text(roh_waehrung, f"{bezeichnung}/{name}: Währung")
        return Preis(
            preis_pro_tonne=_pruefe_plausibel(preis, waehrung, f"{bezeichnung}/{name}"),
            waehrung=waehrung,
            aenderung_prozent_woche=payload.zahl(
                roh_aenderung, f"{bezeichnung}/{name}: Wochenänderung"
            ),
        )

    lose = lies(PRODUCT_ID_LOSE, "lose Ware")
    if lose is None:
        # Kein Lesefehler, sondern eine Auskunft: die Quelle hat für diese
        # Region kein Angebot. Eigene Ausnahmeklasse, damit der Vergleich die
        # Region überspringen kann, ohne dass ein echter Formatfehler
        # dieselbe Behandlung bekäme.
        raise KeinAngebot(
            f"{bezeichnung}: die Seite führt für lose Ware keinen Preis "
            "(Wert 0 oder leer)."
        )
    sackware = lies(PRODUCT_ID_SACKWARE, "Sackware") if PRODUCT_ID_SACKWARE in eintraege else None
    return Regionalpreise(lose=lose, sackware=sackware)


def parse_landesseite(html: str, bezeichnung: str = "Landesseite") -> Landespreise:
    """Lies den Landesdurchschnitt und die Langfristwerte aus der Hauptseite.

    Gilt für ``/pelletpreise`` unter allen drei Landesdomains — nachgemessen
    am 09.08.2026 für de, at und ch.

    Sackware gibt es hier nicht: die Landesseite liefert server-seitig nur den
    Durchschnitt für lose Ware. Die Bundesland-Tabelle auf derselben Seite
    wird erst per JavaScript gefüllt und steht deshalb nicht zur Verfügung —
    sie wird hier bewusst nicht nachgebaut.
    """
    payload = NuxtPayload(html)

    treffer = re.search(
        r"pricing:\{countryAvg:\{(.*?)\},prices:", payload.rohtext, re.DOTALL
    )
    if treffer is None:
        raise ParseError(
            f"{bezeichnung}: kein 'countryAvg'-Block im Nuxt-Payload. "
            "Wurde versehentlich eine Bundesland-Seite abgerufen?"
        )
    preis_treffer = re.search(r"price:([^,}]+)", treffer.group(1))
    if preis_treffer is None:
        raise ParseError(f"{bezeichnung}: 'countryAvg' enthielt kein Feld 'price'.")
    waehrung_treffer = re.search(r"currency:([^,}]+)", treffer.group(1))
    if waehrung_treffer is None:
        raise ParseError(f"{bezeichnung}: 'countryAvg' enthielt kein Feld 'currency'.")

    preis = payload.zahl(preis_treffer.group(1), f"{bezeichnung}: Durchschnittspreis")
    if preis is None:
        raise ParseError(f"{bezeichnung}: der Durchschnittspreis war leer.")
    waehrung = payload.text(waehrung_treffer.group(1), f"{bezeichnung}: Währung")
    aenderung = re.search(r"changePercent:([^,}]+)", treffer.group(1))

    lose = Preis(
        preis_pro_tonne=_pruefe_plausibel(preis, waehrung, f"{bezeichnung}/lose Ware"),
        waehrung=waehrung,
        aenderung_prozent_woche=(
            payload.zahl(aenderung.group(1), f"{bezeichnung}: Wochenänderung")
            if aenderung
            else None
        ),
    )

    # Die Langfristwerte hängen an einer eigenen Komponente. Fehlen sie, ist
    # das kein Grund, den Abruf scheitern zu lassen — der Preis selbst steht.
    def optional(feld: str) -> float | None:
        gefunden = re.search(rf"\b{feld}:([^,}}]+)", payload.rohtext)
        if gefunden is None:
            return None
        try:
            return payload.zahl(gefunden.group(1), f"{bezeichnung}: {feld}")
        except ParseError:
            return None

    return Landespreise(
        lose=lose,
        # Schreibweise stammt aus dem Payload der Seite (inkl. Tippfehler).
        differenz_woche=optional("diffrence1W"),
        differenz_3monate=optional("diffrence3M"),
        tief_3jahre=optional("low3Y"),
        hoch_3jahre=optional("high3Y"),
        schnitt_3jahre=optional("average3Y"),
    )
