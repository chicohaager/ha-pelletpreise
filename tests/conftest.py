"""Gemeinsame Testeinrichtung.

Die Integration wird hier **ohne** ihr ``__init__.py`` geladen. Das ist Absicht:
``__init__.py`` importiert Home Assistant, und ein Test, der eine vollständige
HA-Installation braucht, wird in der Praxis nicht gelaufen. ``const.py``,
``parser.py`` und ``berechnung.py`` kommen bewusst ohne Framework aus — genau
damit die Logik, in der Fehler teuer sind (Preis lesen, Region zuordnen,
Gesamtpreis rechnen), jederzeit offline prüfbar bleibt.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

PAKET = Path(__file__).resolve().parents[1] / "custom_components" / "pelletpreise"

# Ein Platzhalter-Paket, damit "from pelletpreise.x import y" funktioniert,
# ohne dass das echte __init__.py ausgeführt wird.
_paket = types.ModuleType("pelletpreise")
_paket.__path__ = [str(PAKET)]
sys.modules.setdefault("pelletpreise", _paket)

# Reihenfolge zählt: ``berechnung``, ``extremwerte`` und ``vergleich``
# importieren relativ aus ``const`` bzw. ``parser``, die dafür schon in
# sys.modules stehen müssen.
for _name in ("const", "parser", "berechnung", "extremwerte", "vergleich"):
    _pfad = PAKET / f"{_name}.py"
    if not _pfad.is_file():
        raise RuntimeError(f"Modul fehlt: {_pfad}")
    _spec = importlib.util.spec_from_file_location(f"pelletpreise.{_name}", _pfad)
    _modul = importlib.util.module_from_spec(_spec)
    sys.modules[f"pelletpreise.{_name}"] = _modul
    _spec.loader.exec_module(_modul)
    setattr(_paket, _name, _modul)
