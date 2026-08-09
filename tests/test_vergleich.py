"""Tests für den Bundesland-Vergleich.

Die gefährliche Aussage dieses Moduls ist „X ist das günstigste Bundesland".
Sie ist nur so viel wert wie die Vollständigkeit der Menge, über die sie
getroffen wurde — fehlt ein Land, könnte genau das gefehlt haben, das gewonnen
hätte. Deshalb steht hier mehr Negativprüfung als Positivprüfung.
"""

from __future__ import annotations

import pytest

from pelletpreise.const import BUNDESLAENDER_AT, BUNDESLAENDER_DE  # noqa: E402
from pelletpreise.vergleich import bilde_vergleich  # noqa: E402


def bilde(preise, regionen=BUNDESLAENDER_DE):
    """Kurzform: die Vollständigkeitsliste ist in fast jedem Test dieselbe.

    Sie steht trotzdem als Argument am Modul und nicht als Import darin — es
    gibt sie in zwei Größen (16 und 9), und eine fest verdrahtete Liste würde
    beim österreichischen Vergleich die falsche Vollständigkeit prüfen.
    """
    return bilde_vergleich(preise, regionen)


def vollstaendig(**abweichungen: float | None) -> dict[str, float | None]:
    """Alle 16 Bundesländer mit 400,00 €/t, einzelne davon abweichend."""
    preise: dict[str, float | None] = dict.fromkeys(BUNDESLAENDER_DE, 400.00)
    unbekannt = set(abweichungen) - set(BUNDESLAENDER_DE)
    assert not unbekannt, f"Kein Bundesland: {sorted(unbekannt)}"
    preise.update(abweichungen)
    return preise


def test_guenstigstes_und_teuerstes_bundesland():
    vergleich = bilde(
        vollstaendig(bayern=388.10, hamburg=455.90, sachsen=401.00)
    )
    assert vergleich is not None
    assert vergleich.guenstigste.name == "Bayern"
    assert vergleich.guenstigste.preis_pro_tonne == 388.10
    assert vergleich.teuerste.name == "Hamburg"
    assert vergleich.teuerste.preis_pro_tonne == 455.90
    assert vergleich.spanne == 67.80


def test_reihenfolge_der_eingabe_aendert_das_ergebnis_nicht():
    """Gegentest gegen einen Vergleich, der einfach den ersten Eintrag nimmt."""
    preise = vollstaendig(thueringen=333.00)
    umgekehrt = dict(reversed(list(preise.items())))
    assert bilde(preise) == bilde(umgekehrt)
    assert bilde(umgekehrt).guenstigste.name == "Thüringen"


def test_preise_stehen_aufsteigend_und_vollstaendig_im_attribut():
    vergleich = bilde(vollstaendig(bayern=388.10, hamburg=455.90))
    werte = list(vergleich.preise.values())
    assert werte == sorted(werte)
    assert len(vergleich.preise) == 16
    assert list(vergleich.preise)[0] == "Bayern"
    assert list(vergleich.preise)[-1] == "Hamburg"


def test_gleichstand_wird_benannt_statt_verschwiegen():
    """Zwei Länder zum selben Preis: „das günstigste ist X" wäre die halbe Wahrheit."""
    vergleich = bilde(vollstaendig(bayern=388.10, sachsen=388.10))
    assert vergleich.guenstigste.name == "Bayern"
    assert vergleich.gleichauf_guenstigste == ("Sachsen",)
    # Die übrigen 14 liegen alle auf 400,00 — das ist der Höchstwert und
    # gleichzeitig ein 14-facher Gleichstand.
    assert len(vergleich.gleichauf_teuerste) == 13


def test_ohne_gleichstand_bleibt_die_liste_leer():
    """Positivkontrolle: das Feld füllt sich nicht einfach immer."""
    vergleich = bilde(
        {slug: 300.0 + i for i, slug in enumerate(sorted(BUNDESLAENDER_DE))}
    )
    assert vergleich.gleichauf_guenstigste == ()
    assert vergleich.gleichauf_teuerste == ()


def test_bundeslaender_ohne_angebot_stehen_dabei():
    """Sackware gibt es nicht überall — das ist eine Auskunft, kein Fehler."""
    vergleich = bilde(vollstaendig(bremen=None, saarland=None, bayern=388.10))
    assert vergleich.ohne_angebot == ("Bremen", "Saarland")
    assert len(vergleich.preise) == 14
    assert "Bremen" not in vergleich.preise


def test_weniger_als_zwei_preise_ergeben_keinen_vergleich():
    preise: dict[str, float | None] = dict.fromkeys(BUNDESLAENDER_DE, None)
    assert bilde(preise) is None
    preise["bayern"] = 388.10
    assert bilde(preise) is None, "Das günstigste von einem ist keine Aussage"
    preise["sachsen"] = 402.00
    assert bilde(preise) is not None


def test_unvollstaendige_eingabe_wird_abgelehnt():
    """Der eigentliche Zweck dieser Datei.

    Ein Vergleich über 15 Länder sähe genauso aus wie einer über 16 — nur wäre
    das Ergebnis womöglich falsch, ohne dass es jemandem auffiele.
    """
    preise = vollstaendig(bayern=388.10)
    del preise["hamburg"]
    with pytest.raises(ValueError, match="hamburg"):
        bilde(preise)


def test_unbekanntes_bundesland_wird_abgelehnt():
    preise = vollstaendig()
    preise["tirol"] = 350.00
    with pytest.raises(ValueError, match="tirol"):
        bilde(preise)


# ---------------------------------------------------------------------------
# Österreich — dieselbe Regel, andere Liste
# ---------------------------------------------------------------------------


def test_oesterreich_vergleicht_neun_bundeslaender():
    preise: dict[str, float | None] = dict.fromkeys(BUNDESLAENDER_AT, 420.00)
    preise["wien"] = 407.00
    preise["oberoesterreich"] = 433.48
    vergleich = bilde(preise, BUNDESLAENDER_AT)
    assert vergleich.guenstigste.name == "Wien"
    assert vergleich.teuerste.name == "Oberösterreich"
    assert len(vergleich.preise) == 9


def test_deutsche_liste_am_oesterreichischen_vergleich_wird_abgelehnt():
    """Die Positivkontrolle zur Liste als Argument.

    Ohne sie könnte `bilde_vergleich` weiterhin gegen die deutschen 16 prüfen,
    und alle Tests oben blieben grün — der österreichische Vergleich würde
    dann still gegen die falsche Vollständigkeit laufen.
    """
    preise: dict[str, float | None] = dict.fromkeys(BUNDESLAENDER_AT, 420.00)
    with pytest.raises(ValueError, match="tirol"):
        bilde(preise, BUNDESLAENDER_DE)


def test_vorarlberg_ohne_preis_verhindert_den_vergleich_nicht():
    """Am 09.08.2026 führte Vorarlberg keinen Preis für lose Ware.

    Das ist eine Auskunft der Quelle und kein Grund, die Aussage über die
    übrigen acht Bundesländer zu verwerfen — Vorarlberg gehört sichtbar unter
    `ohne_angebot`.
    """
    preise: dict[str, float | None] = dict.fromkeys(BUNDESLAENDER_AT, 420.00)
    preise["vorarlberg"] = None
    preise["wien"] = 407.00
    vergleich = bilde(preise, BUNDESLAENDER_AT)
    assert vergleich.ohne_angebot == ("Vorarlberg",)
    assert vergleich.guenstigste.name == "Wien"
    assert "Vorarlberg" not in vergleich.preise
