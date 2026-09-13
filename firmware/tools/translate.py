"""One-off helper: translate the German strings in the firmware to English.

Kept in the repository because the project went international mid-way; running
it again on already-translated files is a no-op, and every mapping that no
longer matches is reported instead of failing silently.

    python firmware/tools/translate.py            check only
    python firmware/tools/translate.py --apply    write the files
"""

import argparse
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))


def rules(path):
    """Return the (old, new) pairs for one file."""
    return MAP.get(path, [])


MAP = {}


def add(path, pairs):
    MAP[path] = pairs


# --------------------------------------------------------------- web.py

add("firmware/lib/moonlight/web.py", [
    ('"""Kleiner HTTP-Server: Einrichtungsportal und Bedienoberflaeche.\n\n'
     'Nicht blockierend -- `poll()` wird aus der Hauptschleife aufgerufen und kehrt\n'
     'sofort zurueck, wenn nichts anliegt. So laeuft die Bildausgabe mit konstanter\n'
     'Bildrate weiter, waehrend jemand die Seite bedient.\n"""',
     '"""Small HTTP server: setup portal and control page.\n\n'
     'Non-blocking -- `poll()` is called from the main loop and returns\n'
     'immediately when nothing is pending, so the frame rate stays constant\n'
     'while someone is using the page.\n"""'),

    ('"""Alles rausschreiben, auch wenn send() nur einen Teil nimmt."""',
     '"""Write everything out, even if send() only accepts part of it."""'),

    ('"""Die vollstaendige Anfrage lesen, nicht nur das erste Paket.\n\n'
     '        Browser schicken Kopf und Rumpf eines POST regelmaessig in getrennten\n'
     '        TCP-Segmenten. Wer nur einmal recv() aufruft, bekommt haeufig nur den\n'
     '        Kopf; das Formular kommt dann leer an und es wird nichts gespeichert.\n'
     '        Deshalb erst bis zum Ende des Kopfes lesen, dann Content-Length\n'
     '        auswerten und den Rumpf vollstaendig nachholen.\n        """',
     '"""Read the complete request, not just the first packet.\n\n'
     '        Browsers routinely send the head and the body of a POST in separate\n'
     '        TCP segments. Calling recv() once often yields only the head; the\n'
     '        form then arrives empty and nothing gets saved. So: read to the end\n'
     '        of the head, look at Content-Length, then pull in the rest.\n'
     '        """'),

    ('"""Eine wartende Anfrage bearbeiten, falls vorhanden."""',
     '"""Serve one pending request, if there is one."""'),

    ('            # Bytes, nicht str: MicroPython schluckt str, CPython nicht -- und\n'
     '            # ohne diesen Unterschied bemerkt man den Fehler erst am Geraet.',
     '            # Bytes, not str: MicroPython accepts str, CPython does not --\n'
     '            # without that difference the bug only shows up on the device.'),

    ('            # Der REPL ist am Geraet die einzige Diagnosemoeglichkeit\n'
     '            print("HTTP-Fehler:", exc)',
     '            # The REPL is the only place to see anything on the device\n'
     '            print("HTTP error:", exc)'),

    ('("ssid", "WLAN-Name", "text"),', '("ssid", "Wi-Fi network", "text"),'),
    ('("password", "Passwort", "password"),', '("password", "Password", "password"),'),
    ('("latitude", "Breite (Nord positiv)", "text"),',
     '("latitude", "Latitude (north positive)", "text"),'),
    ('("longitude", "Laenge (Ost positiv)", "text"),',
     '("longitude", "Longitude (east positive)", "text"),'),
    ('("utc_offset", "Zeitzone (Stunden zu UTC)", "text"),',
     '("utc_offset", "Time zone (hours from UTC)", "text"),'),
    ('("led_count", "Anzahl LEDs", "text"),',
     '("led_count", "Number of LEDs", "text"),'),
    ('("led_offset", "Winkel von Pixel 0 (Grad)", "text"),',
     '("led_offset", "Angle of pixel 0 (degrees)", "text"),'),

    ('"title": "Mondlampe einrichten",', '"title": "Moon lamp setup",'),
    ('"<h1>Mondlampe einrichten</h1>"', '"<h1>Moon lamp setup</h1>"'),
    ('"<button type=\'submit\'>Speichern und neu starten</button>"',
     '"<button type=\'submit\'>Save and restart</button>"'),
    ('"<p class=\'hint\'>Standort wird nur f&uuml;r das Programm "\n'
     '                 "<b>Echter Mond</b> gebraucht. Der Winkel von Pixel&nbsp;0 "\n'
     '                 "l&auml;sst sich auch am Ger&auml;t einstellen: Programmtaste "\n'
     '                 "lange dr&uuml;cken.</p>"',
     '"<p class=\'hint\'>Wi-Fi names are case sensitive. The location is "\n'
     '                 "only needed for the <b>Real moon</b> program. The angle of "\n'
     '                 "pixel&nbsp;0 can also be set on the device: press and hold "\n'
     '                 "the program button.</p>"'),

    ('    "Alle Modi im Zeitraffer, ein Monat in einer Minute. Braucht weder Netz noch Uhrzeit.",\n'
     '    "Die aktuelle Mondphase, rund um die Uhr sichtbar.",\n'
     '    "Wie P1, aber nur wenn der Mond wirklich am Himmel steht. Helligkeit und Farbe folgen seiner Hoehe.",\n'
     '    "Vollmond mit langsam wanderndem Farbton.",\n'
     '    "Dunkelstmoegliches warmes Weiss auf dem ganzen Ring.",\n'
     '    "Azimut, Beleuchtungsgrad und Waerme von Hand.",',
     '    "Every mode at high speed, a whole month in a minute. Needs neither network nor clock.",\n'
     '    "The current moon phase, visible around the clock.",\n'
     '    "Like P1, but only while the moon is actually up. Brightness and colour follow its altitude.",\n'
     '    "Full moon with a slowly drifting hue.",\n'
     '    "The dimmest possible warm white across the whole ring.",\n'
     '    "Azimuth, illuminated fraction and warmth set by hand.",'),

    ('"""Bedienoberflaeche mit allem, was das Geraet ueber sich weiss.\n\n'
     '    `info` ist ein Dict, das main.py fuellt -- die Seite selbst rechnet nichts,\n'
     '    damit sie die Bildrate nicht stoert.\n    """',
     '"""Control page showing everything the device knows about itself.\n\n'
     '    `info` is a dict filled in by main.py -- the page computes nothing\n'
     '    itself, so that loading it does not disturb the frame rate.\n    """'),

    ('"<h1>Mondlampe</h1>"', '"<h1>Moon lamp</h1>"'),
    ('"<h2>Programm</h2><div class=\'progs\'>%s</div>"',
     '"<h2>Program</h2><div class=\'progs\'>%s</div>"'),
    ('"<h2>Helligkeit</h2><div class=\'chips\'>%s</div>"',
     '"<h2>Brightness</h2><div class=\'chips\'>%s</div>"'),
    ('"<h2>Manuell &mdash; schaltet auf P5</h2>"',
     '"<h2>Manual &mdash; switches to P5</h2>"'),
    ('"<label>Beleuchtungsgrad <output>%d&nbsp;%%</output>"',
     '"<label>Illuminated fraction <output>%d&nbsp;%%</output>"'),
    ('"<label>Richtung<select name=\'waxing\'>"',
     '"<label>Direction<select name=\'waxing\'>"'),
    ('"<option value=\'1\'%s>zunehmend &ndash; Licht von rechts</option>"',
     '"<option value=\'1\'%s>waxing &ndash; lit from the right</option>"'),
    ('"<option value=\'0\'%s>abnehmend &ndash; Licht von links</option>"',
     '"<option value=\'0\'%s>waning &ndash; lit from the left</option>"'),
    ('"<label>W&auml;rme <output>%d&nbsp;%%</output>"',
     '"<label>Warmth <output>%d&nbsp;%%</output>"'),
    ('"<button type=\'submit\'>&Uuml;bernehmen</button></form>"',
     '"<button type=\'submit\'>Apply</button></form>"'),
    ('"<h2>Ger&auml;t</h2><div class=\'chips\'>"',
     '"<h2>Device</h2><div class=\'chips\'>"'),
    ('"<a class=\'chip\' href=\'/calibrate\'>Winkel kalibrieren</a>"',
     '"<a class=\'chip\' href=\'/calibrate\'>Calibrate angle</a>"'),
    ('"<a class=\'chip\' href=\'/reboot\'>Neu starten</a>"',
     '"<a class=\'chip\' href=\'/reboot\'>Restart</a>"'),
    ('"<a class=\'chip warn\' href=\'/forget\'>WLAN vergessen</a></div>"',
     '"<a class=\'chip warn\' href=\'/forget\'>Forget Wi-Fi</a></div>"'),
    ('"<p class=\'hint\'>Die Seite aktualisiert sich alle 30&nbsp;Sekunden. "\n'
     '        "Der Winkel von Pixel&nbsp;0 l&auml;sst sich auch am Ger&auml;t "\n'
     '        "einstellen: Programmtaste lange dr&uuml;cken.</p>"',
     '"<p class=\'hint\'>This page refreshes every 30&nbsp;seconds. The angle "\n'
     '        "of pixel&nbsp;0 can also be set on the device: press and hold the "\n'
     '        "program button.</p>"'),

    ('return _PAGE % {"title": "Mondlampe", "body": body,',
     'return _PAGE % {"title": "Moon lamp", "body": body,'),
    ('<html lang="de">', '<html lang="en">'),
])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--file", help="only this path, relative to the repo root")
    args = ap.parse_args()

    total_missing = 0
    for rel in sorted(MAP):
        if args.file and args.file != rel:
            continue
        path = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.exists(path):
            print("%-42s MISSING FILE" % rel)
            continue
        src = io.open(path, encoding="utf-8").read()
        done = missing = 0
        for old, new in MAP[rel]:
            if old in src:
                src = src.replace(old, new)
                done += 1
            elif new in src:
                pass                      # already translated
            else:
                missing += 1
                print("   no match: %r" % (old[:70],))
        total_missing += missing
        print("%-42s %2d replaced, %d unmatched" % (rel, done, missing))
        if args.apply and done:
            io.open(path, "w", encoding="utf-8", newline="\n").write(src)

    if total_missing:
        print("\n%d mappings did not match -- check before relying on this."
              % total_missing)
        return 1
    print("\nAll mappings matched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
