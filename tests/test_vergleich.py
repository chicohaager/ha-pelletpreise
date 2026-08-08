"""Tests für den Bundesland-Vergleich.

Die gefährliche Aussage dieses Moduls ist „X ist das günstigste Bundesland".
Sie ist nur so viel wert wie die Vollständigkeit der Menge, über die sie
getroffen wurde — fehlt ein Land, könnte genau das gefehlt haben, das gewonnen
hätte. Deshalb steht hier mehr Negativprüfung als Positivprüfung.
"""

from __future__ import annotations

import pytest

from pelletpreise.const import BUNDESLAENDER  # noqa: E402
from pelletpreise.vergleich import bilde_vergleich  # noqa: E402


def vollstaendig(**abweichungen: float | None) -> dict[str, float | None]:
    """Alle 16 Bundesländer mit 400,00 €/t, einzelne davon abweichend."""
    preise: dict[str, float | None] = dict.fromkeys(BUNDESLAENDER, 400.00)
    unbekannt = set(abweichungen) - set(BUNDESLAENDER)
    assert not unbekannt, f"Kein Bundesland: {sorted(unbekannt)}"
    preise.update(abweichungen)
    return preise


def test_guenstigstes_und_teuerstes_bundesland():
    vergleich = bilde_vergleich(
        vollstaendig(bayern=388.10, hamburg=455.90, sachsen=401.00)
    )
    assert vergleich is not None
    assert vergleich.guenstigste.name == "Bayern"
    assert vergleich.guenstigste.euro_pro_tonne == 388.10
    assert vergleich.teuerste.name == "Hamburg"
    assert vergleich.teuerste.euro_pro_tonne == 455.90
    assert vergleich.spanne_euro == 67.80


def test_reihenfolge_der_eingabe_aendert_das_ergebnis_nicht():
    """Gegentest gegen einen Vergleich, der einfach den ersten Eintrag nimmt."""
    preise = vollstaendig(thueringen=333.00)
    umgekehrt = dict(reversed(list(preise.items())))
    assert bilde_vergleich(preise) == bilde_vergleich(umgekehrt)
    assert bilde_vergleich(umgekehrt).guenstigste.name == "Thüringen"


def test_preise_stehen_aufsteigend_und_vollstaendig_im_attribut():
    vergleich = bilde_vergleich(vollstaendig(bayern=388.10, hamburg=455.90))
    werte = list(vergleich.preise.values())
    assert werte == sorted(werte)
    assert len(vergleich.preise) == 16
    assert list(vergleich.preise)[0] == "Bayern"
    assert list(vergleich.preise)[-1] == "Hamburg"


def test_gleichstand_wird_benannt_statt_verschwiegen():
    """Zwei Länder zum selben Preis: „das günstigste ist X" wäre die halbe Wahrheit."""
    vergleich = bilde_vergleich(vollstaendig(bayern=388.10, sachsen=388.10))
    assert vergleich.guenstigste.name == "Bayern"
    assert vergleich.gleichauf_guenstigste == ("Sachsen",)
    # Die übrigen 14 liegen alle auf 400,00 — das ist der Höchstwert und
    # gleichzeitig ein 14-facher Gleichstand.
    assert len(vergleich.gleichauf_teuerste) == 13


def test_ohne_gleichstand_bleibt_die_liste_leer():
    """Positivkontrolle: das Feld füllt sich nicht einfach immer."""
    vergleich = bilde_vergleich(
        {slug: 300.0 + i for i, slug in enumerate(sorted(BUNDESLAENDER))}
    )
    assert vergleich.gleichauf_guenstigste == ()
    assert vergleich.gleichauf_teuerste == ()


def test_bundeslaender_ohne_angebot_stehen_dabei():
    """Sackware gibt es nicht überall — das ist eine Auskunft, kein Fehler."""
    vergleich = bilde_vergleich(vollstaendig(bremen=None, saarland=None, bayern=388.10))
    assert vergleich.ohne_angebot == ("Bremen", "Saarland")
    assert len(vergleich.preise) == 14
    assert "Bremen" not in vergleich.preise


def test_weniger_als_zwei_preise_ergeben_keinen_vergleich():
    preise: dict[str, float | None] = dict.fromkeys(BUNDESLAENDER, None)
    assert bilde_vergleich(preise) is None
    preise["bayern"] = 388.10
    assert bilde_vergleich(preise) is None, "Das günstigste von einem ist keine Aussage"
    preise["sachsen"] = 402.00
    assert bilde_vergleich(preise) is not None


def test_unvollstaendige_eingabe_wird_abgelehnt():
    """Der eigentliche Zweck dieser Datei.

    Ein Vergleich über 15 Länder sähe genauso aus wie einer über 16 — nur wäre
    das Ergebnis womöglich falsch, ohne dass es jemandem auffiele.
    """
    preise = vollstaendig(bayern=388.10)
    del preise["hamburg"]
    with pytest.raises(ValueError, match="hamburg"):
        bilde_vergleich(preise)


def test_unbekanntes_bundesland_wird_abgelehnt():
    preise = vollstaendig()
    preise["tirol"] = 350.00
    with pytest.raises(ValueError, match="tirol"):
        bilde_vergleich(preise)
