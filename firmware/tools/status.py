r"""Query the lamp: Wi-Fi, configuration, networks in range.

    python firmware\tools\status.py                 find the port automatically
    python firmware\tools\status.py --port COM5
    python firmware\tools\status.py --scan          also scan for networks

Note: this interrupts the program running on the Pico. It is restarted at the
end unless --no-reset is given.
"""

import argparse
import os
import subprocess
import sys
import tempfile

RP_VID = 0x2E8A
MICROPYTHON_PID = 0x0005

DEVICE_SNIPPET = '''
import network, json, os, sys

STATUS = {0: "IDLE", 1: "CONNECTING", 2: "WRONG_PASSWORD", 3: "GOT_IP",
          -1: "LINK_DOWN", -2: "LINK_JOIN", -3: "LINK_BADAUTH",
          -4: "LINK_NOTFOUND", -5: "LINK_FAIL"}

print("Files in flash")
try:
    print("   ", sorted(os.listdir()))
except Exception as e:
    print("    error:", e)

print("Firmware")
try:
    sys.path.insert(0, "/lib")
    from moonlight import VERSION
    print("    Version   :", VERSION)
except Exception as e:
    print("    unknown, no moonlight package found:", e)

print("Configuration")
cfg = {}
try:
    with open("config.json") as fh:
        cfg = json.load(fh)
    pw = cfg.get("password", "")
    print("    SSID      :", repr(cfg.get("ssid")))
    print("    Password  :", ("set, %d characters" % len(pw)) if pw else "empty")
    print("    Hostname  :", repr(cfg.get("hostname")))
    print("    Location  :", cfg.get("latitude"), "/", cfg.get("longitude"))
    print("    Program   :", cfg.get("program"), " brightness:", cfg.get("brightness"))
    print("    LEDs      :", cfg.get("led_count"), "on pin", cfg.get("led_pin"),
          " offset", cfg.get("led_offset"))
except Exception as e:
    print("    no config.json:", e)

print("Wi-Fi station")
w = network.WLAN(network.STA_IF)
print("    active    :", w.active())
print("    connected :", w.isconnected())
try:
    s = w.status()
    print("    status    :", s, STATUS.get(s, "?"))
except Exception as e:
    print("    status    :", e)
if w.isconnected():
    ip, mask, gw, dns = w.ifconfig()
    print("    IP        :", ip)
    print("    Gateway   :", gw, " DNS:", dns)
    try:
        print("    RSSI      :", w.status("rssi"), "dBm")
    except Exception:
        pass
    print("    Interface : http://" + ip + "/")

ap = network.WLAN(network.AP_IF)
if ap.active():
    print("Setup portal active")
    try:
        print("    SSID      :", ap.config("essid"))
        print("    IP        :", ap.ifconfig()[0], " -> http://192.168.4.1/")
    except Exception as e:
        print("   ", e)

try:
    import time
    print("Clock (UTC):", time.localtime())
except Exception:
    pass
'''

SCAN_SNIPPET = '''
print("Networks in range")
try:
    if not w.active():
        w.active(True)
    want = (cfg.get("ssid") or "").lower()
    for n in sorted(w.scan(), key=lambda x: -x[3])[:10]:
        ssid = n[0].decode("utf8", "ignore")
        mark = "  <- matches the configuration" if ssid.lower() == want else ""
        if ssid.lower() == want and ssid != cfg.get("ssid"):
            mark = "  <- WARNING: different upper/lower case!"
        print("    %-28s channel %2d  %4d dBm%s" % (ssid, n[2], n[3], mark))
except Exception as e:
    print("    scan failed:", e)
'''


def find_port():
    try:
        import serial.tools.list_ports as lp
    except ImportError:
        return None
    for p in lp.comports():
        if p.vid == RP_VID and p.pid == MICROPYTHON_PID:
            return p.device
    for p in lp.comports():
        if p.vid == RP_VID:
            sys.stderr.write("Found %s with USB 2E8A:%04X -- that is not "
                             "MicroPython.\n" % (p.device, p.pid))
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--scan", action="store_true",
                    help="also list the networks in range")
    ap.add_argument("--no-reset", action="store_true",
                    help="do not restart the program afterwards")
    args = ap.parse_args()

    port = args.port or find_port()
    if not port:
        raise SystemExit("No Pico running MicroPython found. "
                         "Give the port with --port.")
    print("Pico on %s\n" % port)

    code = DEVICE_SNIPPET + (SCAN_SNIPPET if args.scan else "")
    fd, tmp = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w") as fh:
        fh.write(code)
    try:
        res = subprocess.run([sys.executable, "-m", "mpremote",
                              "connect", port, "run", tmp],
                             capture_output=True, text=True)
        sys.stdout.write(res.stdout)
        if res.returncode != 0:
            sys.stderr.write(res.stderr)
            raise SystemExit(res.returncode)
    finally:
        os.unlink(tmp)

    if not args.no_reset:
        print("\nRestarting the program.")
        subprocess.run([sys.executable, "-m", "mpremote",
                        "connect", port, "reset"], capture_output=True)


if __name__ == "__main__":
    main()
