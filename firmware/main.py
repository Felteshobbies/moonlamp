"""Moon lamp -- main loop.

Startup sequence:
  1. Load the configuration. If Wi-Fi is missing, or the program button is
     held down at power-on, the Pico opens its own network and shows the
     setup form.
  2. Join the Wi-Fi, set the clock over NTP, blink the IP on the ring.
  3. From then on the loop runs at a fixed frame rate: poll the buttons,
     compute a frame, dither it, emit it, and serve HTTP alongside.

Without a network or without a clock the lamp keeps running -- it falls
back to demo mode rather than staying dark.
"""

import sys
import time

sys.path.insert(0, "lib")

from moonlight import buttons as buttonsmod          # noqa: E402
from moonlight import config as configmod
from moonlight import ephemeris                       # noqa: E402            # noqa: E402
from moonlight import leds as ledsmod                # noqa: E402
from moonlight import programs                       # noqa: E402
from moonlight import render                         # noqa: E402
from moonlight import timeutil                       # noqa: E402
from moonlight import web                            # noqa: E402

SAVE_DELAY_MS = 10_000        # only write to flash once things have settled
AP_NAME = "Moon Lamp Setup"


def ticks_ms():
    return time.ticks_ms() if hasattr(time, "ticks_ms") else int(time.time() * 1000)


def ticks_diff(a, b):
    return time.ticks_diff(a, b) if hasattr(time, "ticks_diff") else a - b


# ------------------------------------------------------------------ Feedback

def flash_count(ring, cfg, count, colour=None, on_ms=180, off_ms=140):
    """Flash `count` points of light -- feedback without a display."""
    n = cfg["led_count"]
    px = colour or render.tint(0.35)
    for k in range(count):
        frame = [(0, 0, 0, 0)] * n
        idx = render.pixel_at_angle(n, render.CALIBRATION_ANGLE,
                                    cfg["led_offset"], cfg["led_clockwise"])
        for j in range(k + 1):
            frame[(idx + j * 2) % n] = px
        ring.show(frame)
        time.sleep_ms(on_ms) if hasattr(time, "sleep_ms") else time.sleep(on_ms / 1000)
        ring.show([(0, 0, 0, 0)] * n)
        time.sleep_ms(off_ms) if hasattr(time, "sleep_ms") else time.sleep(off_ms / 1000)


def show_ip(ring, cfg, ip):
    """Last octet of the IP as blinks -- so the Pico can be found without a router."""
    try:
        last = int(ip.split(".")[-1])
    except (ValueError, IndexError):
        return
    for digit in str(last):
        flash_count(ring, cfg, int(digit) if digit != "0" else 10,
                    colour=render.tint(0.3, coolness=1.0))
        time.sleep(0.4)


# ------------------------------------------------------------------- Network

def start_ap(cfg):
    import network
    ap = network.WLAN(network.AP_IF)
    ap.config(essid=AP_NAME, security=0)
    ap.active(True)
    while not ap.active():
        time.sleep(0.2)
    return ap


# Plain text for the CYW43 status codes. Without this the REPL just shows
# "-2", and you cannot tell a wrong password from a missing network.
WLAN_STATUS = {
    0: "idle", 1: "connecting", 2: "wrong password", 3: "got IP",
    -1: "link down", -2: "joining",
    -3: "join rejected (password?)", -4: "network not found",
    -5: "connection failed",
}


def _status_text(wlan):
    try:
        s = wlan.status()
    except Exception:
        return "?"
    return "%s (%s)" % (s, WLAN_STATUS.get(s, "unknown"))


def match_ssid(wlan, want):
    """Look for a network that differs only in upper/lower case.

    Wi-Fi names are case sensitive. Get that wrong in the setup form and the
    station sits silently at "joining" -- a symptom that looks exactly like a
    password problem.
    """
    try:
        found = []
        for n in wlan.scan():
            s = n[0].decode("utf8", "ignore")
            if s and s not in found:
                found.append(s)
    except Exception as exc:
        print("  scan not possible:", exc)
        return None, []
    if want in found:
        return want, found
    for s in found:
        if s.lower() == want.lower():
            return s, found
    return None, found


def connect(cfg, timeout=20):
    import network
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        wlan.config(hostname=cfg["hostname"])
    except (AttributeError, OSError, ValueError):
        pass

    ssid = cfg["ssid"]
    print("Wi-Fi: connecting to %r ..." % ssid)
    wlan.connect(ssid, cfg["password"])
    t0 = time.time()
    while not wlan.isconnected() and time.time() - t0 < timeout:
        time.sleep(0.3)

    if not wlan.isconnected():
        print("Wi-Fi: no luck, status %s" % _status_text(wlan))
        real, found = match_ssid(wlan, ssid)
        if real and real != ssid:
            print("Wi-Fi: in range this network is called %r, not %r -- "
                  "correcting and saving" % (real, ssid))
            cfg["ssid"] = real
            try:
                configmod.save(configmod.validate(cfg))
            except Exception as exc:
                print("Wi-Fi: saving failed:", exc)
            wlan.disconnect()
            time.sleep(1)
            wlan.connect(real, cfg["password"])
            t0 = time.time()
            while not wlan.isconnected() and time.time() - t0 < timeout:
                time.sleep(0.3)
        elif not real:
            print("Wi-Fi: %r is not in range. Found: %s"
                  % (ssid, ", ".join(found) if found else "nothing"))

    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        try:
            rssi = " , %d dBm" % wlan.status("rssi")
        except Exception:
            rssi = ""
        print("Wi-Fi: connected as %s%s -> http://%s/" % (ip, rssi, ip))
        return wlan

    print("Wi-Fi: giving up, status %s -- the lamp continues in demo mode"
          % _status_text(wlan))
    return None


# -------------------------------------------------------------------- Portal

def run_portal(cfg, ring):
    """Setup mode: own network, form, then restart."""
    start_ap(cfg)
    server = web.Server()
    pulse = 0.0
    state = {"done": False, "msg": ""}

    def handler(path, query):
        if path != "/save":
            return "200 OK", "text/html", web.portal_page(cfg, state["msg"])

        # An empty form means the request body never arrived. That must not
        # pass silently as "saved", or the lamp restarts without credentials
        # and nobody knows why.
        if not query:
            print("Portal: POST /save with no form data")
            return ("200 OK", "text/html",
                    web.portal_page(cfg, "The form data did not arrive. "
                                         "Please submit again."))

        for key, _, _ in web.PORTAL_FIELDS:
            if key in query and query[key] != "":
                cfg[key] = query[key]
        if "password" in query:
            cfg["password"] = query["password"]      # may be empty (open network)

        for key in ("latitude", "longitude", "led_offset"):
            try:
                cfg[key] = float(cfg[key])
            except (TypeError, ValueError):
                pass
        for key in ("utc_offset", "led_count"):
            try:
                cfg[key] = int(float(cfg[key]))
            except (TypeError, ValueError):
                pass

        if not cfg.get("ssid"):
            return ("200 OK", "text/html",
                    web.portal_page(cfg, "A Wi-Fi network name is required."))

        configmod.save(configmod.validate(cfg))
        # Read back: only restart if it really landed in the filesystem.
        # Otherwise you end up in an endless loop of portal, save, restart.
        back = configmod.load()
        if back.get("ssid") != cfg["ssid"]:
            print("Portal: could not write config.json")
            return ("200 OK", "text/html",
                    web.portal_page(cfg, "Saving failed -- check the Pico's "
                                         "filesystem."))
        print("Portal: saved for SSID %r, restarting" % cfg["ssid"])
        state["done"] = True
        return ("200 OK", "text/html",
                web.portal_page(cfg, "Saved for '%s'. The lamp will restart "
                                     "and connect." % cfg["ssid"]))

    while True:
        server.poll(handler)
        # A slow breathing pulse signals setup mode
        pulse += 0.02
        level = 0.05 + 0.05 * (1.0 + _sin(pulse)) / 2.0
        ring.show(render.solid(cfg["led_count"],
                               render.tint(level, coolness=1.0)))
        if state["done"]:
            time.sleep(1.5)
            _reset()
        time.sleep(0.02)


def _sin(x):
    import math
    return math.sin(x)


def _reset():
    try:
        import machine
        machine.reset()
    except ImportError:
        raise SystemExit(0)


# ---------------------------------------------------------------------- Main

def main():
    cfg = configmod.load()
    ring = ledsmod.Ring(cfg["led_pin"], cfg["led_count"],
                        temporal=cfg.get("temporal", False),
                        n_subframes=int(cfg.get("subframes", 8)))
    panel = buttonsmod.Panel(cfg)

    # Program button held at power-on -> force setup mode
    forced = panel.program._raw() == 0
    if forced or not configmod.configured(cfg):
        run_portal(cfg, ring)
        return

    wlan = connect(cfg)
    have_time = False
    if wlan is not None:
        have_time = timeutil.sync_ntp()
        print("Clock: %s" % ("set over NTP" if have_time
                             else "NTP failed, demo mode"))
        show_ip(ring, cfg, wlan.ifconfig()[0])
    else:
        flash_count(ring, cfg, 3, colour=render.tint(0.3, warmth=1.0))

    server = None
    if wlan is not None:
        try:
            server = web.Server()
        except OSError:
            server = None

    # Manual mode addresses the four channels directly; W alone is a plain
    # white moon, which is the sensible thing to land on when you switch to it.
    manual_state = {"illum": 0.5, "waxing": True,
                    "r": 0.0, "g": 0.0, "b": 0.0, "w": 1.0}
    def status_text():
        """Short summary for the header of the control page."""
        if wlan is None:
            return "no Wi-Fi &ndash; demo mode"
        parts = ["connected to %s" % cfg["ssid"], wlan.ifconfig()[0]]
        try:
            parts.append("%d dBm" % wlan.status("rssi"))
        except Exception:
            pass
        parts.append("clock via NTP" if have_time else "no clock")
        return " &middot; ".join(parts)

    status = {"msg": status_text()}
    dirty_at = None
    calibrating = False
    t_start = time.time()
    boot_at = time.time()
    frame_ms = int(1000 / cfg["fps"])
    last_frame = ticks_ms()
    last_sync = time.time()

    pending = {"calibrate": False, "reboot": False, "forget": False}

    def build_info():
        """Gather everything the page displays.

        Deliberately here and not in web.py: the page should compute nothing,
        so that loading it does not disturb the frame rate.
        """
        facts = [("Program", "P%d %s" % (cfg["program"],
                                          programs.NAMES[cfg["program"]])),
                 ("Brightness", "%.1f %%"
                  % (configmod.BRIGHTNESS_STEPS[cfg["brightness"]] * 100))]
        if wlan is not None:
            try:
                facts.append(("Signal", "%d dBm" % wlan.status("rssi")))
            except Exception:
                pass
            facts.append(("IP", wlan.ifconfig()[0]))
        if have_time:
            d = timeutil.utc_day_number()
            off = timeutil.local_offset_hours(cfg, d)
            lt = time.localtime(int(time.time() + off * 3600))
            facts.append(("Local time", "%02d:%02d" % (lt[3], lt[4])))
            facts.append(("Date", "%04d-%02d-%02d" % (lt[0], lt[1], lt[2])))
            try:
                p = ephemeris.moon_phase(d)
                facts.append(("Moon phase", "%.0f %% %s"
                              % (p["illum"] * 100,
                                 "waxing" if p["waxing"] else "waning")))
                facts.append(("Moon age", "%.1f days"
                              % (p["age"] * ephemeris.SYNODIC)))
                facts.append(("Distance", "%.0f km" % p["dist_km"]))
                alt, az = ephemeris.moon_altitude(d, cfg["latitude"],
                                                  cfg["longitude"])
                facts.append(("Moon altitude", "%+.1f deg %s"
                              % (alt, "above the horizon" if alt > 0
                                 else "below the horizon")))
            except Exception as exc:
                facts.append(("Ephemeris", "error: %s" % exc))
        else:
            facts.append(("Clock", "not set"))
        facts.append(("Uptime", "%d min" % int((time.time() - boot_at) / 60)))
        return {"status": status["msg"], "facts": facts,
                "manual": manual_state, "output": ring.describe()}

    def handler(path, query):
        if path == "/calibrate":
            pending["calibrate"] = True
            return "303 See Other", "text/html", _redirect()
        if path == "/reboot":
            pending["reboot"] = True
            return ("200 OK", "text/html",
                    "<!DOCTYPE html><meta charset='utf-8'>"
                    "<meta http-equiv='refresh' content='8; url=/'>"
                    "<p>Restarting ...</p>")
        if path == "/forget":
            cfg["ssid"] = ""
            cfg["password"] = ""
            configmod.save(configmod.validate(cfg))
            pending["reboot"] = True
            return ("200 OK", "text/html",
                    "<!DOCTYPE html><meta charset='utf-8'><p>Wi-Fi forgotten. "
                    "The lamp will restart and open the setup portal "
                    "'Moon Lamp Setup'.</p>")
        if path == "/set":
            if "program" in query:
                try:
                    cfg["program"] = max(0, min(programs.N_PROGRAMS - 1,
                                                int(query["program"])))
                except ValueError:
                    pass
            if "brightness" in query:
                try:
                    cfg["brightness"] = max(0, min(
                        len(configmod.BRIGHTNESS_STEPS) - 1,
                        int(query["brightness"])))
                except ValueError:
                    pass
            for key in ("illum", "r", "g", "b", "w"):
                if key in query:
                    try:
                        manual_state[key] = max(0.0, min(
                            1.0, float(query[key]) / 100.0))
                    except ValueError:
                        pass
            if "waxing" in query:
                manual_state["waxing"] = query["waxing"] not in ("0", "false")

            # --- ring geometry
            if "led_offset" in query:
                try:
                    cfg["led_offset"] = float(query["led_offset"]) % 360.0
                except ValueError:
                    pass
            if "led_clock" in query:
                # Clock position of pixel 0. Degrees remain the stored form;
                # this only names the positions the way a person would. Applied
                # after led_offset deliberately: if both ever arrive together,
                # the one the user actually looked at should win.
                try:
                    cfg["led_offset"] = render.clock_to_angle(
                        int(query["led_clock"]))
                except ValueError:
                    pass
            if "nudge" in query:
                # One LED pitch, so the ring can be turned pixel by pixel while
                # watching the lamp
                try:
                    step = 360.0 / max(1, int(cfg["led_count"]))
                    cfg["led_offset"] = ((cfg["led_offset"]
                                          + float(query["nudge"]) * step)
                                         % 360.0)
                except ValueError:
                    pass
            if "earthshine" in query:
                # Slider carries tenths of a percent
                try:
                    cfg["earthshine"] = max(0.0, min(0.2,
                                                     int(query["earthshine"])
                                                     / 1000.0))
                except ValueError:
                    pass
            if "led_clockwise" in query:
                cfg["led_clockwise"] = query["led_clockwise"] not in ("0", "false")

            if "temporal" in query or "subframes" in query:
                want = cfg.get("temporal")
                subs = int(cfg.get("subframes", 8))
                if "temporal" in query:
                    want = query["temporal"] not in ("0", "false")
                if "subframes" in query:
                    try:
                        subs = max(2, min(16, int(query["subframes"])))
                    except ValueError:
                        pass
                if want != cfg.get("temporal") or subs != cfg.get("subframes"):
                    # The DMA channel and the subframe buffers are set up once
                    # at start-up, so this takes effect after a restart.
                    cfg["temporal"] = want
                    cfg["subframes"] = subs
                    configmod.save(configmod.validate(cfg))
                    pending["reboot"] = True
                    return ("200 OK", "text/html",
                            "<!DOCTYPE html><meta charset='utf-8'>"
                            "<meta http-equiv='refresh' content='9; url=/'>"
                            "<p>Output mode changed. Restarting ...</p>")

            if "led_count" in query:
                try:
                    new_count = max(1, min(300, int(query["led_count"])))
                except ValueError:
                    new_count = cfg["led_count"]
                if new_count != cfg["led_count"]:
                    # The output buffer and the PIO state machine are set up
                    # once at start-up, so this only takes effect after a
                    # restart. Save immediately -- a reboot would drop a
                    # pending write.
                    cfg["led_count"] = new_count
                    configmod.save(configmod.validate(cfg))
                    pending["reboot"] = True
                    return ("200 OK", "text/html",
                            "<!DOCTYPE html><meta charset='utf-8'>"
                            "<meta http-equiv='refresh' content='9; url=/'>"
                            "<p>Now %d LEDs. Restarting ...</p>" % new_count)

            if "program" in query:
                pending["stop_calibrate"] = True
            pending["save"] = True
            return "303 See Other", "text/html", _redirect()
        return "200 OK", "text/html", web.control_page(cfg, build_info())

    while True:
        now = ticks_ms()
        if ticks_diff(now, last_frame) < frame_ms:
            # Between image updates: keep the subframes going and serve HTTP.
            # tick() returns immediately unless the DMA path is idle, so this
            # costs nothing on the blocking path.
            ring.tick()
            if server is not None:
                server.poll(handler)
            continue
        last_frame = now

        # Carry out web-triggered actions in step with the loop
        if pending.get("reboot"):
            time.sleep(1)
            _reset()
        if pending.pop("calibrate", False):
            calibrating = True
        if pending.pop("stop_calibrate", False):
            calibrating = False
        if pending.pop("save", False):
            dirty_at = now

        for name, kind in panel.poll(now):
            if calibrating:
                if name == "program":
                    calibrating = False
                    dirty_at = now
                elif name == "up":
                    cfg["led_offset"] = (cfg["led_offset"] + 360.0
                                         / cfg["led_count"]) % 360.0
                elif name == "down":
                    cfg["led_offset"] = (cfg["led_offset"] - 360.0
                                         / cfg["led_count"]) % 360.0
                continue

            if name == "program" and kind == buttonsmod.LONG:
                calibrating = True
                continue
            if name == "program":
                cfg["program"] = (cfg["program"] + 1) % programs.N_PROGRAMS
                flash_count(ring, cfg, cfg["program"] + 1)
                t_start = time.time()
            elif name == "up":
                cfg["brightness"] = min(len(configmod.BRIGHTNESS_STEPS) - 1,
                                        cfg["brightness"] + 1)
            elif name == "down":
                cfg["brightness"] = max(0, cfg["brightness"] - 1)
            dirty_at = now

        level = configmod.BRIGHTNESS_STEPS[cfg["brightness"]]

        if calibrating:
            # Light the LED that the current setting believes is at the
            # bottom of the ring. The brightness buttons step the offset by one
            # LED, so the point walks around; when it is really at the bottom,
            # the offset describes the mounting position correctly.
            frame = [(0, 0, 0, 0)] * cfg["led_count"]
            idx = render.pixel_at_angle(cfg["led_count"],
                                        render.CALIBRATION_ANGLE,
                                        cfg["led_offset"],
                                        cfg["led_clockwise"])
            frame[idx] = render.tint(0.5)
            ring.show(frame)
        else:
            d = timeutil.utc_day_number() if have_time else 0.0
            ring.show(programs.frame_for(cfg["program"], cfg, d, level,
                                         time.time() - t_start,
                                         manual_state, have_time))

        if dirty_at is not None and ticks_diff(now, dirty_at) > SAVE_DELAY_MS:
            configmod.save(cfg)
            dirty_at = None

        if have_time and time.time() - last_sync > 86400:
            last_sync = time.time()
            timeutil.sync_ntp(retries=1)

        if server is not None:
            server.poll(handler)


def _redirect():
    return ("<!DOCTYPE html><meta charset='utf-8'>"
            "<meta http-equiv='refresh' content='0; url=/'>")


if __name__ == "__main__":
    main()
