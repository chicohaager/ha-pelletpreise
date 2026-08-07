# Pelletpreise für Home Assistant

Holt die aktuellen Marktpreise für Holzpellets von [heizpellets24.de](https://www.heizpellets24.de/pelletpreise)
und legt sie als Sensoren an — für Deutschland insgesamt oder für ein einzelnes
Bundesland, mit **lose Ware** und **Sackware** getrennt.

![Dashboard-Karten](docs/dashboard.png)

## Was die Integration liefert

Pro eingerichteter Region entsteht ein Gerät mit diesen Sensoren:

| Sensor | Einheit | Gilt für |
| --- | --- | --- |
| Lose Ware | €/t | alle Regionen |
| Lose Ware pro kg | €/kg | alle Regionen |
| Lose Ware Gesamtpreis | € | alle Regionen |
| Lose Ware Änderung zur Vorwoche | % | alle Regionen |
| Sackware | €/t | nur Bundesländer |
| Sackware pro kg | €/kg | nur Bundesländer |
| Sackware Gesamtpreis | € | nur Bundesländer |
| Sackware Änderung zur Vorwoche | % | nur Bundesländer |
| Tiefstwert / Höchstwert / Durchschnitt 3 Jahre | €/t | nur Deutschland |
| Differenz zu vor 3 Monaten | €/t | nur Deutschland |

Mehrere Regionen parallel sind möglich — einfach die Integration mehrfach
hinzufügen. Alle Preise verstehen sich **inklusive Mehrwertsteuer und
Lieferung**; bei loser Ware kommt herstellerseitig die Einblaspauschale hinzu.

## Installation

### Über HACS (empfohlen)

1. HACS → Dreipunktmenü → **Benutzerdefinierte Repositories**
2. Repository: `https://github.com/chicohaager/ha-pelletpreise`, Kategorie: **Integration**
3. „Pelletpreise" herunterladen, Home Assistant neu starten
4. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Pelletpreise**

### Von Hand

Den Ordner `custom_components/pelletpreise` in das Konfigurationsverzeichnis
von Home Assistant kopieren (dorthin, wo auch `configuration.yaml` liegt), dann
neu starten.

Benötigt **Home Assistant 2025.3 oder neuer**.

## Einrichtung

Im Dialog werden zwei Dinge abgefragt:

- **Region** — „Deutschland" oder eines der 16 Bundesländer.
- **Bestellmenge** — wirkt **ausschließlich** auf die hochgerechneten
  Gesamtpreise. Der Marktpreis je Tonne ändert sich dadurch nicht.

Beides lässt sich später über **Konfigurieren** am Eintrag ändern; die Menge
wirkt sofort, ohne Neustart.

## Wie genau sind die Zahlen?

Diese Integration liest exakt das, was heizpellets24.de auf seinen öffentlichen
Preisseiten anzeigt, und rechnet nichts dazu. Drei Punkte sind trotzdem wichtig:

- **Der Preis ist ein Marktdurchschnitt, kein Angebot.** Die Quelle bildet ihn
  je Region aus dem günstigsten Händlerangebot je Postleitzahl.
- **Bezugsgröße ist eine Gesamtabnahme von 6.000 kg.** Der Gesamtpreis wird von
  dort aus **linear** auf deine Menge hochgerechnet. Echte Angebote sind
  mengenabhängig: kleinere Bestellungen sind je Tonne teurer. Der Sensor sagt
  das in seinen Attributen (`berechnung`) dazu — nimm die Zahl als
  Größenordnung, nicht als Kalkulation.
- **Feiner als Bundesland geht es nicht.** Eine Postleitzahl wird bewusst
  *nicht* abgefragt: die Quelle liefert auf ihren öffentlichen Seiten keine
  PLZ-genauen Preise, und eine PLZ, die nichts bewirkt, würde eine Genauigkeit
  vortäuschen, die es nicht gibt.

Geht bei der Quelle etwas kaputt oder ändert sich das Seitenformat, werden die
Sensoren **nicht verfügbar** und die Integration meldet im Protokoll, welcher
Teil der Seite gefehlt hat. Es wird in keinem Fall ein Ersatz- oder Altwert
angezeigt — ein falscher Preis wäre schlimmer als gar keiner.

## Dashboard-Karten

Fertige Karten zum Einfügen liegen unter [`dashboard/`](dashboard/):

- [`karte-bundesland.yaml`](dashboard/karte-bundesland.yaml) — lose Ware und Sackware nebeneinander
- [`karte-deutschland.yaml`](dashboard/karte-deutschland.yaml) — Bundesdurchschnitt mit Drei-Jahres-Einordnung

Die Entitäts-IDs darin sind **Beispiele**. Home Assistant vergibt sie abhängig
vom Gerätenamen und davon, ob das Gerät einem Bereich zugeordnet ist. Die
eigenen IDs stehen unter *Einstellungen → Geräte & Dienste → Pelletpreise →
Gerät* oder in den Entwicklerwerkzeugen unter *Zustände*.

Der Preisverlauf füllt sich erst mit der Zeit und reicht nur so weit zurück,
wie der Recorder Daten aufbewahrt (Standardeinstellung: 10 Tage).

## Aktualisierung

Alle 12 Stunden. Die Quelle aktualisiert einmal täglich — häufigeres Abrufen
brächte keine neuen Daten und würde eine fremde Website ohne Nutzen belasten.
Pro Region und Abruf ist es genau **eine** Anfrage.

Verwendet werden ausschließlich die regulären, öffentlichen Preisseiten, die
`robots.txt` von heizpellets24.de für alle Clients freigibt. Die dort gesperrten
Datenendpunkte werden bewusst nicht angefasst.

## Fehler melden

Bitte über *Einstellungen → Geräte & Dienste → Pelletpreise → Dreipunktmenü →
**Diagnose herunterladen*** die Diagnosedatei anhängen. Sie enthält den letzten
Fehlertext und die gelesenen Werte, aber keine persönlichen Daten — die
Integration braucht weder Zugangsdaten noch eine Adresse.

## Entwicklung

```bash
python -m pytest              # Offline-Tests gegen gespeicherte Seiten
python -m pytest -m live      # zusätzlich gegen die echte Website
```

Die Offline-Tests prüfen den Parser gegen echte, abgespeicherte Seiten — die
erwarteten Zahlen stammen aus der im Browser gerenderten Tabelle der Quelle.
Dazu kommen Negativtests: kaputte, leere und falsche Seiten müssen zu einem
klaren Fehler führen und dürfen keinen Wert liefern.

Der Live-Test ruft alle 16 Bundesländer plus Deutschland ab und schlägt an,
sobald sich das Seitenformat ändert. Er läuft zusätzlich wöchentlich in der
GitHub-Action, damit so eine Änderung auffällt, bevor jemand ein Ticket
aufmacht.

## Lizenz

MIT — siehe [LICENSE](LICENSE).

Die Preisdaten stammen von heizpellets24.de. Dieses Projekt steht in keiner
Verbindung zu HeizPellets24.
