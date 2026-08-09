"""Vergleich der Bundesländer — wo ist es gerade am günstigsten?

Die Landesseite zeigt zwar eine Bundesland-Tabelle, liefert sie aber
**nicht** mit aus: im Nuxt-Payload steht unter ``pricing`` nur der eigene
Landesdurchschnitt (``countryAvg``) und derselbe Wert noch einmal unter
``prices``; ``localPrices`` ist dort leer. Die Tabelle füllt JavaScript später
nach. Wer den günstigsten Preis wissen will, muss die Bundesland-Seiten
einzeln lesen (Deutschland 16, Österreich 9) — deshalb ist dieser Vergleich
abschaltbar und standardmäßig aus.

Dieses Modul rechnet nur, es ruft nichts ab: es bekommt die Preise und
bestimmt daraus die Extreme. Bewusst ohne Home-Assistant-Abhängigkeit, damit
die Auswahlregel offline prüfbar bleibt. Es kennt auch keine Währung — es
sortiert Zahlen, und die Beschriftung passiert dort, wo die gelesene Währung
vorliegt.

Zwei Fallen, gegen die hier ausdrücklich abgesichert wird:

* **Unvollständigkeit.** Fehlt auch nur ein Bundesland, ist „das günstigste"
  eine Behauptung über eine Menge, die man gar nicht kennt — der fehlende
  Eintrag könnte genau der gesuchte sein. ``bilde_vergleich`` nimmt deshalb
  nur eine vollständige Zuordnung an und lehnt jede andere laut ab.
* **Gleichstand.** Zwei Bundesländer können denselben gerundeten Preis haben.
  Dann wäre „das günstigste ist X" die halbe Wahrheit; die anderen stehen
  deshalb im Feld ``gleichauf`` und landen als Attribut am Sensor.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Rang:
    """Ein Bundesland mit seinem Preis."""

    slug: str
    name: str
    preis_pro_tonne: float


@dataclass(frozen=True)
class Vergleich:
    """Das Ergebnis eines Bundesland-Vergleichs für **eine** Warenart."""

    guenstigste: Rang
    teuerste: Rang

    gleichauf_guenstigste: tuple[str, ...]
    """Weitere Bundesländer mit exakt demselben niedrigsten Preis."""

    gleichauf_teuerste: tuple[str, ...]
    """Weitere Bundesländer mit exakt demselben höchsten Preis."""

    preise: dict[str, float]
    """Alle Bundesländer mit Preis, aufsteigend sortiert (Name → Preis/t)."""

    ohne_angebot: tuple[str, ...]
    """Bundesländer, für die die Quelle diese Warenart nicht führt.

    Das ist eine Eigenschaft der Quelle, kein Abruffehler: Sackware wird nicht
    überall angeboten, und für lose Ware gibt es das ebenfalls (Vorarlberg am
    09.08.2026). Die Angabe gehört an den Sensor, damit „günstigstes
    Bundesland" nicht so aussieht, als wären alle im Rennen gewesen.
    """

    @property
    def spanne(self) -> float:
        """Abstand zwischen teuerstem und günstigstem Bundesland."""
        return round(self.teuerste.preis_pro_tonne - self.guenstigste.preis_pro_tonne, 2)


def bilde_vergleich(
    preise: Mapping[str, float | None], regionen: Mapping[str, str]
) -> Vergleich | None:
    """Bestimme günstigstes und teuerstes Bundesland.

    ``preise`` muss **alle** Slugs aus ``regionen`` enthalten; ``None`` steht
    für „dort gibt es dafür kein Angebot". Fehlende oder unbekannte Slugs sind
    ein Programmfehler und werfen ``ValueError`` — ein Vergleich über eine
    zufällige Teilmenge wäre eine Auskunft, die niemand nachprüfen kann.

    ``regionen`` wird übergeben und nicht importiert: der Vergleich gibt es in
    zwei Ländern mit verschiedenen Listen, und eine hier fest verdrahtete
    Liste würde beim österreichischen Vergleich stillschweigend die falsche
    Vollständigkeit prüfen.

    Rückgabe ``None``, wenn weniger als zwei Bundesländer einen Preis haben:
    „das günstigste von einem" ist keine Aussage, und der Sensor bleibt dann
    lieber ohne Wert.
    """
    erwartet = set(regionen)
    gegeben = set(preise)
    if gegeben != erwartet:
        fehlend = sorted(erwartet - gegeben)
        unbekannt = sorted(gegeben - erwartet)
        raise ValueError(
            f"Bundeslandvergleich braucht alle {len(erwartet)} Bundesländer. "
            f"Fehlend: {fehlend or '—'}; unbekannt: {unbekannt or '—'}."
        )

    mit_preis = [
        Rang(slug=slug, name=regionen[slug], preis_pro_tonne=float(wert))
        for slug, wert in preise.items()
        if wert is not None
    ]
    ohne_angebot = tuple(
        sorted(regionen[slug] for slug, wert in preise.items() if wert is None)
    )
    if len(mit_preis) < 2:
        return None

    # Zweites Sortierkriterium ist der Name: ohne es hinge die Auswahl bei
    # Gleichstand an der Reihenfolge des Abrufs und wechselte scheinbar
    # zufällig hin und her.
    sortiert = sorted(mit_preis, key=lambda r: (r.preis_pro_tonne, r.name))
    guenstigste = sortiert[0]
    teuerste = sortiert[-1]

    return Vergleich(
        guenstigste=guenstigste,
        teuerste=teuerste,
        gleichauf_guenstigste=tuple(
            r.name
            for r in sortiert[1:]
            if r.preis_pro_tonne == guenstigste.preis_pro_tonne
        ),
        gleichauf_teuerste=tuple(
            r.name
            for r in sortiert[:-1]
            if r.preis_pro_tonne == teuerste.preis_pro_tonne
        ),
        preise={r.name: r.preis_pro_tonne for r in sortiert},
        ohne_angebot=ohne_angebot,
    )
