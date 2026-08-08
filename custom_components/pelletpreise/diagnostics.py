"""Diagnosedaten für Fehlerberichte.

Bewusst ohne personenbezogene Angaben: die Integration ruft eine öffentliche
Preisseite ab, es gibt keine Zugangsdaten, keine Adresse und keine
Postleitzahl. Was hier steht, kann bedenkenlos an ein Ticket gehängt werden.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import PelletpreiseConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PelletpreiseConfigEntry
) -> dict[str, Any]:
    """Liefere den Zustand eines Eintrags."""
    coordinator = entry.runtime_data
    daten = coordinator.data

    diagnose: dict[str, Any] = {
        "region": coordinator.region,
        "quelle": coordinator.url,
        "bestellmenge_kg": coordinator.menge,
        # Gehört in jeden Fehlerbericht: ohne diesen Wert lässt sich ein
        # gemeldeter Gesamtpreis nicht nachrechnen, und ein "zu hoher Preis"
        # sähe nach einem Parser-Fehler aus, obwohl er eingetragen wurde.
        "einblaspauschale_eur": coordinator.einblaspauschale,
        "letzter_abruf_erfolgreich": coordinator.last_update_success,
    }
    if not coordinator.last_update_success:
        # Genau diese Meldung braucht ein Fehlerbericht: sie benennt, welcher
        # Teil der Seite sich geändert hat.
        diagnose["letzter_fehler"] = str(coordinator.last_exception)

    if daten is not None:
        diagnose["werte"] = {
            "lose_euro_pro_tonne": daten.lose.euro_pro_tonne,
            "lose_aenderung_prozent_woche": daten.lose.aenderung_prozent_woche,
            # Beide Zahlen nebeneinander, damit im Ticket sofort sichtbar ist,
            # welcher Anteil gelesen und welcher hinzugerechnet wurde.
            "lose_warenwert_eur": daten.warenwert(daten.lose),
            "lose_gesamt_eur": daten.gesamtpreis(daten.lose, mit_einblaspauschale=True),
            "sackware_euro_pro_tonne": (
                daten.sackware.euro_pro_tonne if daten.sackware else None
            ),
            "sackware_aenderung_prozent_woche": (
                daten.sackware.aenderung_prozent_woche if daten.sackware else None
            ),
            "langfrist": (
                {
                    "differenz_woche_euro": daten.langfrist.differenz_woche_euro,
                    "differenz_3monate_euro": daten.langfrist.differenz_3monate_euro,
                    "tief_3jahre": daten.langfrist.tief_3jahre,
                    "hoch_3jahre": daten.langfrist.hoch_3jahre,
                    "schnitt_3jahre": daten.langfrist.schnitt_3jahre,
                }
                if daten.langfrist
                else None
            ),
        }
    return diagnose
