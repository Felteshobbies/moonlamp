# Mondlampe — Firmware für Raspberry Pi Pico W

Steuert einen SK6812-RGBW-Ring im Rahmen der gewölbten Mondlampe. Berechnet die
echte Mondphase aus NTP-Zeit, bildet sie auf Lichtbogen und Farbe ab und lässt
sich über drei Taster oder eine Weboberfläche bedienen.

> **Nicht auf Hardware getestet.** Ich hatte beim Schreiben keinen Pico zur
> Verfügung. Astronomie, Bildaufbau, Dithering, Zeitzone und Konfiguration sind
> dagegen reines Python und am PC gegen bekannte Größen geprüft — siehe
> [Tests](#tests). Ungetestet sind die MicroPython-spezifischen Teile:
> PIO-Treiber, WLAN, Taster-GPIO, HTTP-Server.

---

## Hardware

| Teil | Wert |
|---|---|
| Controller | Raspberry Pi Pico **W** (WLAN wird für NTP gebraucht) |
| LED-Streifen | SK6812 RGBW, GRBW-Reihenfolge, 30 mm Teilung |
| LED-Zahl | 44 auf dem Ring (r = 209 mm, Umfang 1313 mm, 8,2° pro LED) |
| Pegelwandler | 74AHCT125 oder 74AHCT14 — **zwingend** |
| Datenleitung | 330 Ω in Reihe, direkt am Pegelwandler |
| Puffer | 1000 µF über die Streifenversorgung an der ersten LED |
| Netzteil | 5 V/5 A bei SK6812 (44 × 4 × 18 mA ≈ 3,2 A) |

**Der Pegelwandler ist kein Luxus.** Der Pico gibt 3,3 V aus, die WS28xx-Familie
will als High-Pegel etwa 0,7 × VDD. Ohne Wandler läuft es oft — aber
temperaturabhängig und unzuverlässig.

Bei 5 V **an zwei Stellen einspeisen**: am Stoß und am gegenüberliegenden Punkt
des Rings. Das halbiert den Kupferweg von 1,31 m auf 0,65 m, sonst wird die
abgewandte Seite im Weiß sichtbar wärmer.

Masse von Pico und Streifen zwingend verbinden.

### Standardbelegung (in `config.json` änderbar)

| Signal | GPIO |
|---|---|
| LED-Daten | 16 |
| Taster Programm | 12 |
| Taster heller | 13 |
| Taster dunkler | 14 |

Taster gegen Masse, interne Pull-ups sind aktiv — keine externen Widerstände nötig.

---

## Installation

MicroPython für den Pico W flashen (UF2 von micropython.org), dann:

```bat
python -m pip install mpremote

REM Nur Code kopieren, Einrichtung danach am Handy
python firmware\tools\provision.py --port COM5

REM Oder alles gleich vorbelegen
python firmware\tools\provision.py --port COM5 ^
    --ssid MeinWLAN --password geheim ^
    --lat 51.2 --lon 6.8 --utc-offset 1
```

### Erstkonfiguration am Handy

Ohne gültige WLAN-Daten — oder wenn beim Einschalten die **Programmtaste
gehalten** wird — spannt der Pico ein eigenes Netz auf:

1. Mit dem WLAN `Mondlampe-Setup` verbinden
2. `http://192.168.4.1` aufrufen
3. Formular ausfüllen, speichern, die Lampe startet neu

Der Ring atmet währenddessen langsam blau, damit der Zustand erkennbar ist.

Nach dem Verbinden blinkt die **letzte Stelle der IP-Adresse** als Lichtpunkte
auf dem Ring — so findet man die Lampe auch ohne Router-Oberfläche. Der Hostname
wird per DHCP gesetzt; `mondlampe.local` funktioniert je nach Router, unter
Windows ohne Bonjour oft nicht.

---

## Bedienung

| Taste | kurz | lang |
|---|---|---|
| Programm | nächstes Programm, quittiert durch N Lichtpunkte | Kalibrierung des Winkel-Offsets |
| heller | eine Helligkeitsstufe hoch | |
| dunkler | eine Stufe runter | |

Helligkeitsstufen: 0,3 % / 1 % / 3 % / 10 % / 30 % / 100 %. Logarithmisch, weil
linear unten unbrauchbar und oben verschwendet wäre.

### Winkel-Offset kalibrieren

Wo Pixel 0 nach dem Kleben physisch sitzt, weiß nur der, der geklebt hat. Ohne
diesen Wert zeigt die Sichel in die falsche Richtung.

Programmtaste lang drücken → ein einzelner Punkt leuchtet. Mit heller/dunkler
dreht er sich um den Ring. Auf **unten** stellen, Programmtaste erneut drücken.
Gespeichert wird 10 s später (Flash-Schonung).

### Programme

| | Name | Braucht Netz | Braucht Standort |
|---|---|---|---|
| P0 | Demo — alle Zustände im Zeitraffer, Lunation in 60 s | nein | nein |
| P1 | Mondphase — Echtzeitphase, immer sichtbar | ja | nein |
| P2 | Echter Mond — nur wenn er wirklich am Himmel steht | ja | ja |
| P3 | Farbwechsel — Vollmond mit wanderndem Farbton | nein | nein |
| P4 | Nachtlicht — warmes Restlicht, ganzer Ring | nein | nein |
| P5 | Manuell — Azimut, Phase und Farbe über die Weboberfläche | nein | nein |

**P2** blendet mit der Mondhöhe auf (unter −2° aus, ab +8° voll), färbt tief
stehenden Mond wärmer und dunkler, hoch stehenden kühler, und dimmt bei
Tageslicht auf 8 % — der Mond steht tagsüber oft am Himmel, ist dann aber kaum
zu sehen.

Ohne Netz oder ohne Zeit fällt P1 und P2 auf den Demomodus zurück, statt dunkel
zu bleiben.

**Roter Mond:** Finsternistermine als Datumsliste `"YYYY-MM-DD"` unter
`eclipses` in die `config.json` eintragen. Echte Finsternisse zu rechnen wäre auf
dem Pico machbar, träte aber selten auf; die Rötung bei Horizontnähe in P2
passiert dagegen jede Nacht und nutzt den RGBW-Streifen genauso.

---

## Wie es funktioniert

```
config.json  ──┐
NTP ── Zeit ───┤
               ├──► Ephemeride ──► Programm ──► Renderer ──► Dither ──► PIO ──► SK6812
Taster ────────┤     Phase,        P0…P5       44 Pixel     8 Bit
HTTP ──────────┘     Höhe                      16 Bit
```

### Ephemeride (`lib/moonlight/ephemeris.py`)

Keplerbahn plus die größten Störterme nach Paul Schlyter. Genauigkeit rund
2 Bogenminuten, gemessene Langzeitdrift **−0,01 Tage in 20 Jahren**.

### Renderer (`lib/moonlight/render.py`)

Das Kernstück ist `ARC_TABLE`: welcher Lichtbogen welchen scheinbaren
Beleuchtungsgrad erzeugt. Diese Tabelle ist **nicht geraten**, sondern am
Höhenfeld des echten Reliefs ausgemessen (`tests/calibrate_arc.py`) und trifft
den Zielwert über den ganzen Bereich auf ±0,005.

Wichtig dabei: **echte Sicheln sind möglich.** Die Schattengrenze liegt bei jedem
einzelnen Azimut zwar am Kuppelscheitel, also auf der Scheibenmitte — aber durch
den 1/d²-Abfall ist die zugewandte Seite keineswegs gleichmäßig hell. Ein
schmaler Bogen beleuchtet nur einen Keil am Rand, und der wirkt wie eine Sichel.
Gemessen: 8° Bogen ergeben 9 % scheinbare Beleuchtung.

Die Bogenkanten sind weich, und die Rampe ist mindestens einen LED-Abstand breit.
Sonst würde beim Weiterlaufen der Phase alle paar Stunden eine ganze LED hart
dazuspringen — im Demomodus sähe man 44 Stufen statt einer wandernden Kante.

**Erdschein:** die unbeleuchtete Seite ist genau die komplementäre Phase und wird
von den gegenüberliegenden LEDs auf 1,8 % kühl angehoben. Das aschgraue
Mondlicht ist ein reales Phänomen und das Einzige, was die Kuppelgeometrie nicht
von selbst kann.

**Farbe:** der W-Kanal trägt die Grundhelligkeit, RGB nur die Färbung. Aus RGB
gemischtes Weiß wäre auf grauem Relief schmutzig und bräuchte etwa das Dreifache
an Strom.

### Dithering (`lib/moonlight/dither.py`)

Die interessantesten Zustände liegen ganz unten — Erdschein bei 1,8 %,
Nachtlicht bei wenigen Prozent. Naiv auf 8 Bit gerundet landet man bei
Zählerständen von 2 bis 5, wo die Stufen sichtbar werden und das Weiß beim
Dimmen die Farbe wechselt.

Statt zeitlichem Dithern bei hoher Bildrate (das bräuchte DMA: 44 Pixel × 32 Bit
dauern 1,76 ms, bei 400 Hz wären das 70 % Rechenzeit) läuft hier **räumliches**
Dithern entlang des Rings mit langsam wanderndem Startpunkt. Benachbarte LEDs
beleuchten stark überlappende Bereiche der Mondscheibe — rundet man eine hoch und
die nächste runter, mittelt sich das auf der Oberfläche weg, ganz ohne
Zeitkomponente. Damit flimmert prinzipbedingt nichts, und 60 Hz genügen.

Gemessener Restfehler in den unteren Stufen: **0,02 statt 0,50 einer 8-Bit-Stufe.**

Sichtbar bliebe das Muster nur direkt vor den LEDs im äußersten Ring — und den
verdeckt die Frontlippe des Rahmens ohnehin.

---

## Tests

Alle laufen am PC mit CPython, ohne Pico:

```bat
python firmware\tests\test_ephemeris.py     REM Astronomie gegen bekannte Größen
python firmware\tests\test_render.py        REM Bildaufbau, Farbe, Dithering
python firmware\tests\test_system.py        REM Zeitzone, Konfiguration, Programme
```

`test_ephemeris.py` prüft unter anderem Tagundnachtgleichen und Sonnenwenden auf
0,01° genau, die Perigäums-/Apogäumsdistanz, die Streuung der Lunationen gegen
die reale Bandbreite 29,27–29,83 d, die Langzeitdrift über 40 Jahre, und dass
der Vollmond um Mitternacht kulminiert.

Zwei Skripte brauchen zusätzlich numpy und die Werkzeuge aus `Moon/tools`:

```bat
python firmware\tests\calibrate_arc.py      REM ARC_TABLE neu ausmessen
python firmware\tests\preview_firmware.py   REM Firmware-Ausgabe als Bild rendern
```

`preview_firmware.py` schließt die Kette: echtes Datum → Ephemeride →
`render.phase_frame()` → 44 RGBW-Werte → optisches Modell der Lampe → Bild. Was
dort zu sehen ist, ist durchgerechnet, nicht illustriert.

---

## Wenn etwas nicht geht

| Symptom | Ursache |
|---|---|
| Falsche Farben | Bytereihenfolge — `leds.py` schreibt GRBW; bei anderen Streifen dort tauschen |
| Erste LEDs gehen, weiter hinten Müll | Pegelwandler fehlt oder Masse nicht verbunden |
| Weiß wird zur abgewandten Seite hin gelblich | Spannungsabfall, zweite Einspeisung fehlt |
| Sichel zeigt in die falsche Richtung | Winkel-Offset kalibrieren, ggf. `led_clockwise` umstellen |
| Lampe bleibt im Demomodus | Keine NTP-Zeit — WLAN prüfen |
| Portal kommt nicht | Programmtaste beim Einschalten gedrückt halten |

## Bedienoberflaeche im Browser

Nach dem Einbuchen erreichbar unter der IP, die `status.py` nennt, z. B.
`http://192.168.178.58/`. Die Seite aktualisiert sich alle 30 Sekunden selbst
und passt sich dem hellen bzw. dunklen Systemdesign an.

Angezeigt werden: laufendes Programm, Helligkeit, Signalstaerke, IP, Ortszeit
und Datum, Mondphase mit Alter und Entfernung sowie die Hoehe des Mondes ueber
dem Horizont. Bedienen lassen sich Programmwahl, Helligkeitsstufe und der
Manuellmodus P5 mit Beleuchtungsgrad, Richtung und Waerme.

Drei Geraeteaktionen sitzen am Seitenende:

| Link | Wirkung |
|---|---|
| Winkel kalibrieren | startet denselben Modus wie langes Druecken der Programmtaste |
| Neu starten | Softreset |
| WLAN vergessen | loescht die Zugangsdaten und oeffnet wieder das Einrichtungsportal |

Die Seite rechnet selbst nichts: `main.py` sammelt die Werte in `build_info()`
und reicht sie fertig weiter, damit ein Seitenaufruf die Bildrate nicht stoert.

Zum Anpassen des Aussehens ohne Geraet liegt ein gerendertes Muster in
`tests/control_page_sample.html`.

## Status auslesen

```bat
python firmware	ools\status.py            :: Port wird selbst gesucht
python firmware	ools\status.py --scan     :: zusaetzlich Netze in Reichweite
```

Zeigt Konfiguration, WLAN-Status im Klartext, IP, Gateway, RSSI, die URL der
Bedienoberflaeche und die gestellte Uhrzeit. Der Aufruf unterbricht kurz das
laufende Programm und startet es danach neu (`--no-reset` unterdrueckt das).

Die Statuscodes des CYW43 sind ohne Uebersetzung nicht zu gebrauchen:

| Code | Bedeutung |
|---|---|
| `3` | IP erhalten, alles gut |
| `-1` | Verbindung getrennt |
| `-2` | Anmeldung laeuft &mdash; bleibt hier stehen, wenn die SSID nicht passt |
| `-3` | Anmeldung abgelehnt, meist das Passwort |
| `-4` | Netz nicht gefunden |

**WLAN-Namen sind gross-/kleinschreibungsempfindlich.** `zora` und `Zora` sind
zwei verschiedene Netze. Tippt man sich im Portal dabei um, bleibt die Station
auf `-2` stehen, was wie ein Passwortproblem aussieht. `connect()` erkennt das
inzwischen selbst: findet es beim Scan ein Netz, das nur in der Schreibweise
abweicht, korrigiert es die Konfiguration und verbindet erneut. Im REPL steht
dann:

```
WLAN: kein Erfolg, Status -2 (Anmeldung laeuft)
WLAN: in Reichweite heisst das Netz 'Zora', nicht 'zora' -- korrigiere und speichere
WLAN: verbunden als 192.168.178.58 , -36 dBm -> http://192.168.178.58/
```

Live mitlesen geht mit `mpremote connect COM5 repl` (mit Ctrl-D neu starten).

## Wenn der Upload nicht klappt

`provision.py` prüft vorab, ob am Port überhaupt ein MicroPython-REPL antwortet,
und nennt sonst den Grund. Der mit Abstand häufigste Fall bei einem neuen Board:

**Auf dem Pico ist noch gar kein MicroPython.** Ein fabrikneuer oder mit dem
C-SDK bespielter Pico meldet sich zwar am USB, hat aber keinen REPL, mit dem
`mpremote` reden könnte. An der USB-Kennung lässt sich das ablesen:

| USB-Kennung | Bedeutung |
|---|---|
| `2E8A:0003` | BOOTSEL-Modus, Laufwerk `RPI-RP2` |
| `2E8A:0005` | **MicroPython** — nur damit funktioniert der Upload |
| `2E8A:000A` | Programm mit dem C-SDK, kein MicroPython |

MicroPython aufspielen:

1. Pico vom USB trennen
2. BOOTSEL gedrückt halten und dabei einstecken
3. Laufwerk `RPI-RP2` erscheint. `INFO_UF2.TXT` darin nennt das Board, falls
   unklar ist, welches gerade steckt
4. `micropython/RPI_PICO_W-*.uf2` auf das Laufwerk kopieren
5. Der Pico startet neu und meldet sich als `2E8A:0005`

Für WLAN zwingend die **W-Variante** (`RPI_PICO_W`, bei einem Pico 2 W
`RPI_PICO2_W`) — ohne W fehlt der Funktreiber, und `import network` schlägt fehl.

Angeschlossene Boards auflisten:

```bat
python -c "import serial.tools.list_ports as l; [print(p.device, hex(p.vid or 0), p.description) for p in l.comports()]"
```
