"""German -> English replacements for firmware/main.py.

Applied by translate.py. Kept separate because it is a plain data table.
"""

PAIRS = [
    ('"""Mondlampe -- Hauptschleife.\n\n'
     'Ablauf beim Start:\n'
     '  1. Konfiguration laden. Fehlt das WLAN oder wird beim Einschalten die\n'
     '     Programmtaste gehalten, oeffnet der Pico ein eigenes Netz und zeigt das\n'
     '     Einrichtungsformular.\n'
     '  2. Ins WLAN einbuchen, Zeit per NTP stellen, IP als Zahl auf dem Ring blinken.\n'
     '  3. Danach laeuft die Schleife mit fester Bildrate: Taster abfragen,\n'
     '     Frame rechnen, dithern, ausgeben, nebenbei HTTP bedienen.\n\n'
     'Ohne Netz oder ohne Zeit laeuft die Lampe weiter -- dann faellt sie auf den\n'
     'Demomodus zurueck, statt dunkel zu bleiben.\n"""',
     '"""Moon lamp -- main loop.\n\n'
     'Startup sequence:\n'
     '  1. Load the configuration. If Wi-Fi is missing, or the program button is\n'
     '     held down at power-on, the Pico opens its own network and shows the\n'
     '     setup form.\n'
     '  2. Join the Wi-Fi, set the clock over NTP, blink the IP on the ring.\n'
     '  3. From then on the loop runs at a fixed frame rate: poll the buttons,\n'
     '     compute a frame, dither it, emit it, and serve HTTP alongside.\n\n'
     'Without a network or without a clock the lamp keeps running -- it falls\n'
     'back to demo mode rather than staying dark.\n"""'),

    ('SAVE_DELAY_MS = 10_000        # Flash erst schreiben, wenn Ruhe eingekehrt ist\n'
     'AP_NAME = "Mondlampe-Setup"',
     'SAVE_DELAY_MS = 10_000        # only write to flash once things have settled\n'
     'AP_NAME = "Moon Lamp Setup"'),

    ('# --------------------------------------------------------------- Rueckmeldung',
     '# ------------------------------------------------------------------ Feedback'),
    ('"""`count` Lichtpunkte kurz aufblitzen lassen -- Rueckmeldung ohne Display."""',
     '"""Flash `count` points of light -- feedback without a display."""'),
    ('"""Letzte Stelle der IP als Punkte -- damit man den Pico ohne Router findet."""',
     '"""Last octet of the IP as blinks -- so the Pico can be found without a router."""'),
    ('# ------------------------------------------------------------------ Netzwerk',
     '# ------------------------------------------------------------------- Network'),

    ('# Klartext zu den Statuscodes des CYW43. Ohne das steht im REPL nur "-2",\n'
     '# und man weiss nicht, ob das Passwort falsch ist oder das Netz fehlt.',
     '# Plain text for the CYW43 status codes. Without this the REPL just shows\n'
     '# "-2", and you cannot tell a wrong password from a missing network.'),

    ('    0: "bereit", 1: "verbindet", 2: "Passwort falsch", 3: "IP erhalten",',
     '    0: "idle", 1: "connecting", 2: "wrong password", 3: "got IP",'),
    ('    -1: "Verbindung getrennt", -2: "Anmeldung laeuft",',
     '    -1: "link down", -2: "joining",'),
    ('    -3: "Anmeldung abgelehnt (Passwort?)", -4: "Netz nicht gefunden",',
     '    -3: "join rejected (password?)", -4: "network not found",'),
    ('    -5: "Verbindung fehlgeschlagen",', '    -5: "connection failed",'),
    ('WLAN_STATUS.get(s, "unbekannt")', 'WLAN_STATUS.get(s, "unknown")'),

    ('"""Nach einem Netz suchen, das nur in der Gross-/Kleinschreibung abweicht.\n\n'
     '    WLAN-Namen sind gross-/kleinschreibungsempfindlich. Vertippt man sich dabei\n'
     '    im Einrichtungsformular, bleibt die Station stumm auf "Anmeldung laeuft"\n'
     '    stehen -- ein Fehlerbild, das nach einem Passwortproblem aussieht.\n    """',
     '"""Look for a network that differs only in upper/lower case.\n\n'
     '    Wi-Fi names are case sensitive. Get that wrong in the setup form and the\n'
     '    station sits silently at "joining" -- a symptom that looks exactly like a\n'
     '    password problem.\n    """'),

    ('print("  Scan nicht moeglich:", exc)', 'print("  scan not possible:", exc)'),
    ('print("WLAN: verbinde mit %r ..." % ssid)',
     'print("Wi-Fi: connecting to %r ..." % ssid)'),
    ('print("WLAN: kein Erfolg, Status %s" % _status_text(wlan))',
     'print("Wi-Fi: no luck, status %s" % _status_text(wlan))'),
    ('            print("WLAN: in Reichweite heisst das Netz %r, nicht %r -- "\n'
     '                  "korrigiere und speichere" % (real, ssid))',
     '            print("Wi-Fi: in range this network is called %r, not %r -- "\n'
     '                  "correcting and saving" % (real, ssid))'),
    ('print("WLAN: Speichern fehlgeschlagen:", exc)',
     'print("Wi-Fi: saving failed:", exc)'),
    ('            print("WLAN: %r ist nicht in Reichweite. Gefunden: %s"\n'
     '                  % (ssid, ", ".join(found) if found else "nichts"))',
     '            print("Wi-Fi: %r is not in range. Found: %s"\n'
     '                  % (ssid, ", ".join(found) if found else "nothing"))'),
    ('print("WLAN: verbunden als %s%s -> http://%s/" % (ip, rssi, ip))',
     'print("Wi-Fi: connected as %s%s -> http://%s/" % (ip, rssi, ip))'),
    ('    print("WLAN: aufgegeben, Status %s -- die Lampe laeuft im Demomodus weiter"\n'
     '          % _status_text(wlan))',
     '    print("Wi-Fi: giving up, status %s -- the lamp continues in demo mode"\n'
     '          % _status_text(wlan))'),

    ('"""Einrichtungsmodus: eigenes WLAN, Formular, danach Neustart."""',
     '"""Setup mode: own network, form, then restart."""'),

    ('        # Leeres Formular heisst: der Rumpf der Anfrage kam nicht an. Das darf\n'
     '        # nicht stillschweigend als "gespeichert" durchgehen, sonst startet die\n'
     '        # Lampe ohne Zugangsdaten neu und niemand weiss warum.',
     '        # An empty form means the request body never arrived. That must not\n'
     '        # pass silently as "saved", or the lamp restarts without credentials\n'
     '        # and nobody knows why.'),
    ('print("Portal: POST /save ohne Formulardaten")',
     'print("Portal: POST /save with no form data")'),
    ('                    web.portal_page(cfg, "Die Formulardaten sind nicht "\n'
     '                                         "angekommen. Bitte noch einmal senden."))',
     '                    web.portal_page(cfg, "The form data did not arrive. "\n'
     '                                         "Please submit again."))'),
    ('cfg["password"] = query["password"]      # darf leer sein (offenes Netz)',
     'cfg["password"] = query["password"]      # may be empty (open network)'),
    ('web.portal_page(cfg, "Ohne WLAN-Namen geht es nicht."))',
     'web.portal_page(cfg, "A Wi-Fi network name is required."))'),
    ('        # Gegenlesen: nur wenn es wirklich im Dateisystem steht, wird neu\n'
     '        # gestartet. Sonst landet man in einer Endlosschleife aus Portal,\n'
     '        # Speichern und Neustart.',
     '        # Read back: only restart if it really landed in the filesystem.\n'
     '        # Otherwise you end up in an endless loop of portal, save, restart.'),
    ('print("Portal: config.json liess sich nicht schreiben")',
     'print("Portal: could not write config.json")'),
    ('                    web.portal_page(cfg, "Speichern fehlgeschlagen -- "\n'
     '                                         "Dateisystem des Pico pruefen."))',
     '                    web.portal_page(cfg, "Saving failed -- check the Pico\'s "\n'
     '                                         "filesystem."))'),
    ('print("Portal: gespeichert fuer SSID %r, Neustart" % cfg["ssid"])',
     'print("Portal: saved for SSID %r, restarting" % cfg["ssid"])'),
    ('                web.portal_page(cfg, "Gespeichert fuer \'%s\'. Die Lampe startet "\n'
     '                                     "neu und verbindet sich." % cfg["ssid"]))',
     '                web.portal_page(cfg, "Saved for \'%s\'. The lamp will restart "\n'
     '                                     "and connect." % cfg["ssid"]))'),

    ('        # Langsames Atmen signalisiert den Einrichtungsmodus',
     '        # A slow breathing pulse signals setup mode'),
    ('    # Programmtaste beim Einschalten gehalten -> Einrichtungsmodus erzwingen',
     '    # Program button held at power-on -> force setup mode'),
    ('        print("Zeit: %s" % ("per NTP gestellt" if have_time\n'
     '                            else "NTP fehlgeschlagen, Demomodus"))',
     '        print("Clock: %s" % ("set over NTP" if have_time\n'
     '                             else "NTP failed, demo mode"))'),

    ('"""Kurzfassung fuer die Kopfzeile der Bedienseite."""',
     '"""Short summary for the header of the control page."""'),
    ('return "kein WLAN &ndash; Demomodus"', 'return "no Wi-Fi &ndash; demo mode"'),
    ('parts = ["verbunden mit %s" % cfg["ssid"], wlan.ifconfig()[0]]',
     'parts = ["connected to %s" % cfg["ssid"], wlan.ifconfig()[0]]'),
    ('parts.append("Zeit per NTP" if have_time else "keine Zeit")',
     'parts.append("clock via NTP" if have_time else "no clock")'),

    ('"""Alles zusammentragen, was die Seite anzeigt.\n\n'
     '        Bewusst hier und nicht in web.py: die Seite soll nichts rechnen, damit\n'
     '        ein Seitenaufruf die Bildrate nicht stoert.\n        """',
     '"""Gather everything the page displays.\n\n'
     '        Deliberately here and not in web.py: the page should compute nothing,\n'
     '        so that loading it does not disturb the frame rate.\n        """'),

    ('facts = [("Programm", "P%d %s" % (cfg["program"],',
     'facts = [("Program", "P%d %s" % (cfg["program"],'),
    ('                 ("Helligkeit", "%.1f %%"', '                 ("Brightness", "%.1f %%"'),
    ('facts.append(("Signal", "%d dBm" % wlan.status("rssi")))',
     'facts.append(("Signal", "%d dBm" % wlan.status("rssi")))'),
    ('facts.append(("Ortszeit", "%02d:%02d" % (lt[3], lt[4])))',
     'facts.append(("Local time", "%02d:%02d" % (lt[3], lt[4])))'),
    ('facts.append(("Datum", "%02d.%02d.%04d" % (lt[2], lt[1], lt[0])))',
     'facts.append(("Date", "%04d-%02d-%02d" % (lt[0], lt[1], lt[2])))'),
    ('                facts.append(("Mondphase", "%.0f %% %s"\n'
     '                              % (p["illum"] * 100,\n'
     '                                 "zunehmend" if p["waxing"] else "abnehmend")))',
     '                facts.append(("Moon phase", "%.0f %% %s"\n'
     '                              % (p["illum"] * 100,\n'
     '                                 "waxing" if p["waxing"] else "waning")))'),
    ('                facts.append(("Mondalter", "%.1f Tage"',
     '                facts.append(("Moon age", "%.1f days"'),
    ('facts.append(("Entfernung", "%.0f km" % p["dist_km"]))',
     'facts.append(("Distance", "%.0f km" % p["dist_km"]))'),
    ('                facts.append(("Mondhoehe", "%+.1f Grad %s"\n'
     '                              % (alt, "ueber dem Horizont" if alt > 0\n'
     '                                 else "unter dem Horizont")))',
     '                facts.append(("Moon altitude", "%+.1f deg %s"\n'
     '                              % (alt, "above the horizon" if alt > 0\n'
     '                                 else "below the horizon")))'),
    ('facts.append(("Ephemeride", "Fehler: %s" % exc))',
     'facts.append(("Ephemeris", "error: %s" % exc))'),
    ('facts.append(("Uhrzeit", "nicht gestellt"))',
     'facts.append(("Clock", "not set"))'),
    ('facts.append(("Laufzeit", "%d min" % int((time.time() - boot_at) / 60)))',
     'facts.append(("Uptime", "%d min" % int((time.time() - boot_at) / 60)))'),

    ('                    "<p>Neustart laeuft ...</p>")',
     '                    "<p>Restarting ...</p>")'),
    ('                    "<!DOCTYPE html><meta charset=\'utf-8\'><p>WLAN vergessen. "\n'
     '                    "Die Lampe startet neu und oeffnet das Einrichtungsportal "\n'
     '                    "\'Mondlampe-Setup\'.</p>")',
     '                    "<!DOCTYPE html><meta charset=\'utf-8\'><p>Wi-Fi forgotten. "\n'
     '                    "The lamp will restart and open the setup portal "\n'
     '                    "\'Moon Lamp Setup\'.</p>")'),

    ('        # Aus dem Web angestossene Aktionen im Schleifentakt ausfuehren',
     '        # Carry out web-triggered actions in step with the loop'),
    ('            # Ein einzelner Punkt, der mit den Helligkeitstasten wandert:\n'
     '            # so wird er auf die tatsaechliche Einbaulage gedreht.',
     '            # A single point that moves with the brightness buttons: that is\n'
     '            # how it gets turned to match the actual mounting position.'),
]
