# Pelletpreise für Home Assistant

Holt die aktuellen Marktpreise für Holzpellets von heizpellets24 und legt sie
als Sensoren an — für **Deutschland**, **Österreich** und die **Schweiz**, je
Land insgesamt oder für ein einzelnes Bundesland, mit **lose Ware** und
**Sackware** getrennt.

| Land | Quelle | Regionen | Währung |
| --- | --- | --- | --- |
| Deutschland | [heizpellets24.de](https://www.heizpellets24.de/pelletpreise) | Deutschland + 16 Bundesländer | € |
| Österreich | [heizpellets24.at](https://www.heizpellets24.at/pelletpreise) | Österreich + 9 Bundesländer | € |
| Schweiz | [heizpellets24.ch](https://www.heizpellets24.ch/pelletpreise) | nur Schweiz — [warum keine Kantone](#warum-die-schweiz-ohne-kantone-kommt) | CHF |

![Dashboard-Karten](docs/dashboard.png)

## Was die Integration liefert

Pro eingerichteter Region entsteht ein Gerät mit diesen Sensoren. „W" steht für
die Währung des Landes — € oder CHF, siehe [Währung](#währung).

| Sensor | Einheit | Gilt für |
| --- | --- | --- |
| Lose Ware | W/t | alle Regionen |
| Lose Ware pro kg | W/kg | alle Regionen |
| Lose Ware Gesamtpreis ¹ | W | alle Regionen |
| Lose Ware Änderung zur Vorwoche | % | alle Regionen |
| Sackware | W/t | nur Bundesländer |
| Sackware pro kg | W/kg | nur Bundesländer |
| Sackware Gesamtpreis | W | nur Bundesländer |
| Sackware Änderung zur Vorwoche | % | nur Bundesländer |
| Lose Ware Tiefstpreis / Höchstpreis (beobachtet) ² | W/t | alle Regionen |
| Sackware Tiefstpreis / Höchstpreis (beobachtet) ² | W/t | nur Bundesländer |
| Tiefstwert / Höchstwert / Durchschnitt 3 Jahre | W/t | nur Landesebene |
| Differenz zu vor 3 Monaten | W/t | nur Landesebene |
| Günstigstes / teuerstes Bundesland (lose, Sackware) ³ | W/t | nur DE / AT |

¹ Als einziger Sensor enthält er die selbst eingetragene
[Einblaspauschale](#einblaspauschale) — sofern eine eingetragen ist.
² Eigene Aufzeichnung dieser Installation, keine Angabe der Quelle — siehe
[Tiefst- und Höchstpreise](#tiefst--und-höchstpreise).
³ Muss unter *Konfigurieren* eingeschaltet werden — siehe
[Bundesländer vergleichen](#bundesländer-vergleichen).

„Landesebene" heißt Deutschland, Österreich oder Schweiz; „Bundesländer" sind
die 16 deutschen und die 9 österreichischen. Die Schweiz hat bei dieser Quelle
keine brauchbare Regionalebene, deshalb entstehen dort weder Sackware- noch
Vergleichssensoren — die Begründung steht unter
[Warum die Schweiz ohne Kantone kommt](#warum-die-schweiz-ohne-kantone-kommt).

Mehrere Regionen parallel sind möglich, auch über Ländergrenzen hinweg —
einfach die Integration mehrfach hinzufügen. Alle Preise verstehen sich
**inklusive Mehrwertsteuer und Lieferung**; bei loser Ware kommt
herstellerseitig die Einblaspauschale hinzu. Die lässt sich bei der Einrichtung
eintragen und fließt dann in den Sensor *Lose Ware Gesamtpreis* ein — siehe
[Einblaspauschale](#einblaspauschale).

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

> In der HACS-Übersicht steht statt des Symbols ein Platzhalter. Das ist
> normal: HACS holt die Symbole aus dem zentralen Katalog
> brands.home-assistant.io, in dem selbst installierte Integrationen nicht
> stehen. Home Assistant selbst zeigt das mitgelieferte Symbol (ab 2026.3) —
> unter *Einstellungen → Geräte & Dienste → Pelletpreise*.

## Einrichtung

Der Dialog hat zwei Schritte. Zuerst das **Land**, danach:

- **Region** — die Landesebene oder eines ihrer Bundesländer.
- **Bestellmenge** — wirkt **ausschließlich** auf die hochgerechneten
  Gesamtpreise. Der Marktpreis je Tonne ändert sich dadurch nicht.
- **Einblaspauschale** — was der eigene Händler je Lieferung fürs Einblasen
  berechnet. Vorgabe 0.

Das Land steht bewusst voran und nicht als 28. Zeile in einer gemeinsamen
Regionsliste: dort stünden „Salzburg" und „Sachsen" direkt untereinander, und
ein Verklicken ergäbe keinen Fehler, sondern klaglos den Preis des falschen
Landes — im Fall der Schweiz sogar in einer anderen Währung.

Alles lässt sich später über **Konfigurieren** am Eintrag ändern; die Änderung
wirkt sofort, ohne Neustart. Das Land nicht: es steckt in der Region, und eine
andere Region ist ein anderer Eintrag. In den Einträgen für Deutschland und
Österreich steht unter *Konfigurieren* zusätzlich der Schalter
[Bundesländer vergleichen](#bundesländer-vergleichen).

Die Einrichtung ruft die Seite wirklich einmal ab und legt den Eintrag nur an,
wenn ein Preis herauskommt. Führt eine Region gerade keinen (das kommt vor —
Vorarlberg am 09.08.2026), steht der Grund im Dialog, statt dass ein Eintrag
mit dauerhaft leeren Sensoren entsteht.

## Währung

Deutschland und Österreich rechnen in Euro, die Schweiz in Franken. Die
Sensoren eines Schweizer Eintrags tragen deshalb `CHF/t`, `CHF/kg` und `CHF`,
und jeder Sensor führt die Währung zusätzlich im Attribut `waehrung` — wer
Attribute in einer Vorlage weiterrechnet, sieht sonst nicht, was er vor sich
hat.

Zwei Dinge sind dabei Absicht:

- **Es wird nicht umgerechnet.** Ein in Euro umgerechneter Frankenpreis wäre
  kein Preis der Quelle mehr, sondern das Produkt aus zwei Zahlen — und der
  Wechselkurs wäre eine zweite Fehlerquelle mit eigenem Ausfallverhalten. Wer
  vergleichen will, kann das in einer Vorlage mit einem Kurs seiner Wahl tun.
- **Die Währung wird gelesen, nicht angenommen.** Sie steht im Seiten-Payload
  (`currency`), wird von dort übernommen und gegen die für das Land erwartete
  geprüft. Weicht sie ab, bricht der Abruf ab und die Sensoren bleiben leer.
  Das klingt streng, ist aber der einzige Weg: 522 sieht als Eurobetrag genau
  so plausibel aus wie als Frankenbetrag, und ein falsch beschrifteter Preis
  fiele niemandem auf.

### Einblaspauschale

heizpellets24 schreibt unter seine Preise: *„Preis inkl. MwSt. und Lieferung
(lose Pellets **zzgl.** Einblaspauschale)"* — wortgleich auf allen drei
Landesseiten. Die Pauschale ist im Marktpreis also **nicht** enthalten, und die
Quelle nennt keinen Betrag, weil er je Händler verschieden ist. Deshalb steht
hier keine Voreinstellung außer 0: eine „übliche" Zahl wäre geraten und stünde
am Ende ununterscheidbar im Gesamtpreis.

(proPellets Austria beziffert die durchschnittliche Einblaspauschale in
Österreich mit ca. 53,80 € je Zustellung. Auch das bleibt bewusst keine
Vorgabe: es ist der Durchschnitt eines Verbands und nicht der Betrag, der auf
der eigenen Rechnung steht.)

Wer seinen Betrag einträgt, bekommt ihn **einmal je Bestellung** auf den
Gesamtpreis der losen Ware gerechnet:

| | mit 0 € | mit 45 € |
| --- | --- | --- |
| Lose Ware | 400,38 €/t | 400,38 €/t |
| Lose Ware pro kg | 0,4004 €/kg | 0,4004 €/kg |
| **Lose Ware Gesamtpreis** (6.000 kg) | **2.402,28 €** | **2.447,28 €** |
| Sackware Gesamtpreis (6.000 kg) | 2.867,16 € | 2.867,16 € |

Drei Dinge sind dabei Absicht:

- **Nur der Gesamtpreis der losen Ware ändert sich.** Die Werte je Tonne und je
  Kilogramm bleiben unangetastet — das sind Marktpreise der Quelle, keine
  Rechnung. Wäre die Pauschale dort eingemischt, spränge der Preisverlauf,
  sobald jemand seine Bestellmenge ändert.
- **Sackware bekommt sie nicht.** Die kommt auf Paletten und wird nicht
  eingeblasen. Ist eine Pauschale eingetragen, sagt der Sackware-Sensor das im
  Attribut `hinweis_einblaspauschale` ausdrücklich dazu.
- **Der eigene Anteil bleibt sichtbar.** Der Sensor *Lose Ware Gesamtpreis*
  führt `warenwert_eur` und `einblaspauschale_eur` getrennt auf, und
  `berechnung` schreibt dazu, dass die Pauschale selbst eingetragen wurde und
  nicht von heizpellets24 stammt.

Bestehende Einrichtungen ändern sich nicht: ohne Eintrag steht die Pauschale
auf 0, und der Gesamtpreis bleibt auf den Cent derselbe wie vorher.

## Tiefst- und Höchstpreise

Die Sensoren mit **(beobachtet)** halten den niedrigsten und den höchsten
Preis fest, den *diese Installation selbst gesehen hat* — je Region und
getrennt für lose Ware und Sackware. Sie kosten keinen zusätzlichen Abruf und
sind ab der Einrichtung da.

Wichtig ist, was sie **nicht** sind: eine Angabe von heizpellets24. Die
Quelle führt Tief- und Höchstwerte ausschließlich auf ihren Landesseiten
und nur über drei Jahre; für die Bundesländer gibt es dort nichts dergleichen
(nachgemessen für Deutschland und Österreich — der Live-Test
`test_die_bundeslandseiten_fuehren_keine_langfristwerte` prüft genau das, mit
der jeweiligen Landesseite als Gegenprobe). Deshalb steht „(beobachtet)" im Namen
und in den Attributen:

- `beobachtet_seit` — seit wann aufgezeichnet wird. Ohne diese Angabe ist der
  Wert nicht deutbar: 380 €/t nach drei Tagen heißt etwas anderes als 380 €/t
  nach zwei Jahren.
- `gesehen_am` — wann der Rekord **zuerst** erreicht wurde. Bleibt bei
  gleichem Preis stehen, statt täglich mitzuwandern.

Der Wert überdauert Neustarts und auch Ausfälle der Quelle. Führt die Quelle
für ein Bundesland gerade keine Sackware, bleibt der bisherige Rekord stehen —
er war einmal wahr und wird es nicht dadurch weniger.

Zum Neuanfangen gibt es den Dienst **`pelletpreise.extremwerte_zuruecksetzen`**
(*Entwicklerwerkzeuge → Aktionen*, oder am Sensor selbst). Er verwirft die
Aufzeichnung der angesprochenen Sensoren und beginnt beim aktuellen Preis von
vorn.

## Warum die Schweiz ohne Kantone kommt

Die Quelle hat 26 Kantonsseiten. Angeboten werden sie hier trotzdem nicht —
nicht aus Bequemlichkeit, sondern weil nachgemessen wurde, was auf ihnen steht.
Am 09.08.2026 über alle 26 Seiten:

- **14 Kantone** führen gar keinen Preis (Wert 0) — darunter Genf, Luzern,
  Tessin, Waadt, Wallis, Zug und Graubünden.
- Die **übrigen 12** führen ausnahmslos exakt die Landeszahl: 522,12 CHF/t für
  lose Ware und 504,04 CHF/t für Sackware — dieselben Zahlen, die auch
  `/pelletpreise` selbst nennt.

Eine Kantonsauswahl anzubieten hieße also, eine Auflösung vorzutäuschen, die es
nicht gibt: die Hälfte der Einträge wäre dauerhaft „nicht verfügbar", die
andere Hälfte zeigte denselben Wert wie „Schweiz", und ein Kantonsvergleich
wäre ein zwölffacher Gleichstand. Das ist derselbe Grund, aus dem die
Integration auch keine Postleitzahl abfragt.

Weil Sackware bei dieser Quelle ausschließlich auf Bundesland-Seiten steht,
gibt es für die Schweiz folgerichtig auch keinen Sackware-Sensor. Der
Landesdurchschnitt, die Wochenänderung, die Drei-Jahres-Werte und die
beobachteten Extremwerte gibt es sehr wohl.

Der Live-Test `test_die_kantonsseiten_fuehren_keinen_eigenen_preis` misst das
weiter nach — mit den deutschen Bundesländern als Gegenprobe, damit ein
kaputter Test nicht wie ein Befund aussieht. Schlägt er eines Tages fehl, weil
die Kantone eigene Preise bekommen haben, ist das eine gute Nachricht und der
Anlass, sie einzutragen.

## Bundesländer vergleichen

In den Einträgen für **Deutschland** und **Österreich** lassen sich unter
*Konfigurieren* zwei Sensorpaare zuschalten: **günstigstes** und **teuerstes
Bundesland**, je für lose Ware und Sackware. Der Zustand ist der Preis je
Tonne, das Bundesland steht im Attribut `bundesland` — dazu die vollständige
Liste aller Länderpreise (`preise_je_bundesland`), die Spanne
(`spanne_pro_tonne`), ein etwaiger Gleichstand (`gleichauf`) und die Länder
ohne Angebot (`ohne_angebot`).

Der Vergleich ist **standardmäßig aus**, und das aus einem handfesten Grund:
die Landesseite liefert ihre Bundesland-Tabelle nicht mit (die füllt JavaScript
nach), also müssen alle Landesseiten einzeln geholt werden. Das sind **16
zusätzliche Abrufe je Aktualisierung in Deutschland und 9 in Österreich** —
Last auf einer fremden Website, die niemand ungefragt bekommt. Im Schweizer
Eintrag gibt es den Schalter gar nicht: ohne Regionen wäre nichts zu
vergleichen.

Schlägt eine der Seiten **fehl**, bleiben beide Sensoren ohne Wert und der
Grund steht im Protokoll. „Das günstigste von 15" wäre eine Aussage über eine
Menge, die gar nicht vollständig geprüft wurde — und sähe genauso aus wie das
echte Ergebnis.

Etwas anderes ist eine Region, für die die Quelle **keinen Preis führt**. Das
ist ihre Auskunft und kein Fehlschlag: der Vergleich kommt zustande, und die
Region steht am Sensor unter `ohne_angebot`. In Österreich war das am
09.08.2026 Vorarlberg — günstigstes Bundesland Wien mit 407,00 €/t, teuerstes
Oberösterreich mit 433,48 €/t, verglichen wurden acht von neun.

Der Landesdurchschnitt ist übrigens **nicht** der Mittelwert der
Bundeslandwerte: die Quelle bildet ihn nach eigener Angabe je Postleitzahl.
Beide Zahlen liegen nah beieinander (Deutschland am 08.08.2026: 406,51 €/t
gegenüber 406,16 €/t), sind aber nicht dasselbe.

## Wie genau sind die Zahlen?

Diese Integration liest exakt das, was heizpellets24 auf seinen öffentlichen
Preisseiten anzeigt. Dazu gerechnet wird genau eine Zahl, und nur wenn du sie
selbst einträgst: die [Einblaspauschale](#einblaspauschale). Fünf Punkte sind
wichtig:

- **Der Preis ist ein Marktdurchschnitt, kein Angebot.** Die Quelle bildet ihn
  je Region aus dem günstigsten Händlerangebot je Postleitzahl.
- **Bezugsgröße ist eine Gesamtabnahme von 6.000 kg.** Der Gesamtpreis wird von
  dort aus **linear** auf deine Menge hochgerechnet. Echte Angebote sind
  mengenabhängig: kleinere Bestellungen sind je Tonne teurer. Der Sensor sagt
  das in seinen Attributen (`berechnung`) dazu — nimm die Zahl als
  Größenordnung, nicht als Kalkulation.
- **Die Einblaspauschale ist deine Zahl, nicht die der Quelle.** Sie steht
  deshalb im Sensor getrennt neben dem Warenwert und wird im Attribut
  `berechnung` als eigene Eingabe benannt — damit sie später niemand für einen
  gelesenen Marktwert hält.
- **Feiner als Bundesland geht es nicht.** Eine Postleitzahl wird bewusst
  *nicht* abgefragt: die Quelle liefert auf ihren öffentlichen Seiten keine
  PLZ-genauen Preise, und eine PLZ, die nichts bewirkt, würde eine Genauigkeit
  vortäuschen, die es nicht gibt.
- **Einzelne Händlerangebote gibt es nicht.** Damit ist auch keine Spanne
  „günstigster bis teuerster Anbieter" möglich und keine echte
  Einblaspauschale: die öffentliche Seite nennt je Region nur eine Zahl und
  keinen Pauschalbetrag, und die Endpunkte mit den Angeboten sperrt die
  `robots.txt` von heizpellets24 für alle Clients.

Geht bei der Quelle etwas kaputt oder ändert sich das Seitenformat, werden die
Sensoren **nicht verfügbar** und die Integration meldet im Protokoll, welcher
Teil der Seite gefehlt hat. Es wird in keinem Fall ein Ersatz- oder Altwert
angezeigt — ein falscher Preis wäre schlimmer als gar keiner.

## Dashboard-Karten

Fertige Karten zum Einfügen liegen unter [`dashboard/`](dashboard/):

- [`karte-bundesland.yaml`](dashboard/karte-bundesland.yaml) — lose Ware und Sackware, dazu die beobachteten Extremwerte
- [`karte-deutschland.yaml`](dashboard/karte-deutschland.yaml) — Bundesdurchschnitt, Drei-Jahres-Einordnung und Bundesland-Vergleich

Die Entitäts-IDs darin sind **Beispiele**. Home Assistant bildet sie bei der
**ersten** Registrierung aus dem übersetzten Sensornamen und ändert sie danach
nie wieder. Zwei Abweichungen sind deshalb normal:

- Ältere Einrichtungen behalten die Namen von damals — dort kann derselbe
  Sensor `sensor.pelletpreise_deutschland_lose_tonne` heißen, wo eine heute
  angelegte Installation `sensor.pelletpreise_deutschland_lose_ware` hat.
- Ist das Gerät einem Bereich zugeordnet, steht dessen Name vorn:
  `sensor.sonstiges_pelletpreise_deutschland_lose_ware`.

Die eigenen IDs stehen unter *Einstellungen → Geräte & Dienste → Pelletpreise →
Gerät* oder in den Entwicklerwerkzeugen unter *Zustände*.

Der Preisverlauf füllt sich erst mit der Zeit und reicht nur so weit zurück,
wie der Recorder Daten aufbewahrt (Standardeinstellung: 10 Tage).

## Aktualisierung

Alle 12 Stunden. Die Quelle aktualisiert einmal täglich — häufigeres Abrufen
brächte keine neuen Daten und würde eine fremde Website ohne Nutzen belasten.
Pro Region und Abruf ist es genau **eine** Anfrage; nur mit eingeschaltetem
[Bundesland-Vergleich](#bundesländer-vergleichen) kommen im Deutschland-Eintrag
16 und im Österreich-Eintrag 9 weitere dazu, gedrosselt auf vier gleichzeitig.

Verwendet werden ausschließlich die regulären, öffentlichen Preisseiten, die
`robots.txt` für alle Clients freigibt — für alle drei Landesdomains einzeln
geprüft. Die dort gesperrten Datenendpunkte (`/ajaxcontent/`,
`/JsonHandler.ashx`, `/ChartHandler.ashx`) werden bewusst nicht angefasst.

## Umstieg von 2.2.0

Bestehende deutsche Einträge laufen unverändert weiter: die Regionsslugs, die
Entitäts-IDs, die `unique_id`s und die aufgezeichneten Extremwerte bleiben, wie
sie sind. Eine Migration ist nicht nötig, ein Neustart genügt.

Drei **Sensor-Attribute** haben allerdings neue Namen, weil die alten in der
Schweiz gelogen hätten — `warenwert_eur` an einem Frankenbetrag ist keine
Kleinigkeit, sondern eine falsche Angabe an genau der Stelle, an der jemand
nachrechnet:

| bis 2.2.0 | ab 2.3.0 |
| --- | --- |
| `warenwert_eur` | `warenwert` |
| `einblaspauschale_eur` | `einblaspauschale` |
| `spanne_eur_pro_tonne` | `spanne_pro_tonne` |

Dazu kommen an **jedem** Sensor zwei neue Attribute: `land` und `waehrung`.
Wer die alten Namen in einer Vorlage oder einer Automation benutzt, muss dort
nachziehen; die Zustandswerte selbst und alle übrigen Attribute sind
unverändert. In der Diagnosedatei sind die entsprechenden Felder ebenfalls
umbenannt (`lose_euro_pro_tonne` → `lose_pro_tonne` und so weiter).

## Fehler melden

Bitte über *Einstellungen → Geräte & Dienste → Pelletpreise → Dreipunktmenü →
**Diagnose herunterladen*** die Diagnosedatei anhängen. Sie enthält den letzten
Fehlertext und die gelesenen Werte, aber keine persönlichen Daten — die
Integration braucht weder Zugangsdaten noch eine Adresse.

## Entwicklung

```bash
python -m pytest              # Offline-Tests gegen gespeicherte Seiten
python -m pytest -m live      # zusätzlich gegen die echte Website

pip install pytest-homeassistant-custom-component   # braucht Python 3.13
python -m pytest tests/test_sensoren_ha.py -o asyncio_mode=auto
```

Die Offline-Tests prüfen den Parser gegen echte, abgespeicherte Seiten — die
erwarteten Zahlen stammen aus der im Browser gerenderten Tabelle der Quelle.
Dazu kommen Negativtests: kaputte, leere und falsche Seiten müssen zu einem
klaren Fehler führen und dürfen keinen Wert liefern.

Der Live-Test ruft alle drei Landesseiten, die 16 deutschen und die 9
österreichischen Bundesländer sowie alle 26 Schweizer Kantone ab und schlägt
an, sobald sich das Seitenformat, die Währung oder die Bezugsmenge ändert. Er
läuft zusätzlich wöchentlich in der GitHub-Action, damit so eine Änderung
auffällt, bevor jemand ein Ticket aufmacht.

Die dritte Suite (`tests/test_sensoren_ha.py`) startet ein echtes Home
Assistant und prüft, was die beiden anderen nicht sehen können: ob die
Entitäten überhaupt entstehen, ob der beobachtete Rekord einen Neustart
übersteht, ob der Dienst zum Zurücksetzen greift und ob ein fehlgeschlagener
Bundesland-Abruf wirklich zu „nicht verfügbar" führt statt zu einem
Teilergebnis. Ohne das Zusatzpaket überspringt sie sich.

## Lizenz

MIT — siehe [LICENSE](LICENSE).

Die Preisdaten stammen von heizpellets24.de, heizpellets24.at und
heizpellets24.ch. Dieses Projekt steht in keiner Verbindung zu HeizPellets24.
