r"""Push firmware and configuration to the Pico (PC side).

Needs `mpremote`:  python -m pip install mpremote

    python firmware	ools\provision.py --port COM5 --ssid MyNetwork \n        --password secret --lat 51.2 --lon 6.8

Without --ssid only the code is copied; initial setup then happens on a
phone through the setup portal (power up the Pico, join the Wi-Fi network
"Moon Lamp Setup", then open http://192.168.4.1).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.abspath(os.path.join(HERE, os.pardir))

FILES = [
    ("main.py", "main.py"),
    ("lib/moonlight/__init__.py", "lib/moonlight/__init__.py"),
    ("lib/moonlight/buttons.py", "lib/moonlight/buttons.py"),
    ("lib/moonlight/config.py", "lib/moonlight/config.py"),
    ("lib/moonlight/dither.py", "lib/moonlight/dither.py"),
    ("lib/moonlight/ephemeris.py", "lib/moonlight/ephemeris.py"),
    ("lib/moonlight/leds.py", "lib/moonlight/leds.py"),
    ("lib/moonlight/programs.py", "lib/moonlight/programs.py"),
    ("lib/moonlight/render.py", "lib/moonlight/render.py"),
    ("lib/moonlight/timeutil.py", "lib/moonlight/timeutil.py"),
    ("lib/moonlight/web.py", "lib/moonlight/web.py"),
]


def mpremote(port, *args):
    cmd = [sys.executable, "-m", "mpremote"]
    if port:
        cmd += ["connect", port]
    cmd += list(args)
    print("  $ " + " ".join(cmd[2:]))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stdout + res.stderr)
        raise SystemExit("mpremote failed: %s" % " ".join(args))
    return res.stdout


# USB IDs of the RP2040/RP2350 family. The key point: only 0x0005 is
# MicroPython. Anything else has no REPL for mpremote to talk to.
RP_VID = 0x2E8A
RP_PIDS = {
    0x0003: "BOOTSEL mode (RPI-RP2 mass storage)",
    0x0004: "PicoProbe",
    0x0005: "MicroPython",
    0x000A: "program built with the C SDK (not MicroPython)",
}


def list_pico_ports():
    """Every attached RP2040/RP2350 board with its USB ID."""
    try:
        import serial.tools.list_ports as lp
    except ImportError:
        return None
    out = []
    for p in lp.comports():
        if p.vid == RP_VID:
            out.append((p.device, p.pid, RP_PIDS.get(p.pid, "unbekannt")))
    return out


def preflight(port):
    """Check that a MicroPython REPL really answers on that port.

    Without this the first copy command fails with a traceback from deep
    inside mpremote, and you go looking in the wrong place.
    """
    found = list_pico_ports()
    if found is not None:
        if not found:
            print("No Raspberry Pi board found on USB (VID 2E8A).")
        for dev, pid, what in found:
            print("  %-8s USB 2E8A:%04X  %s" % (dev, pid, what))

    cmd = [sys.executable, "-m", "mpremote"]
    if port:
        cmd += ["connect", port]
    cmd += ["eval", "1"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        return

    uf2 = os.path.join(FW, "micropython")
    files = sorted(f for f in os.listdir(uf2)) if os.path.isdir(uf2) else []
    print()
    print("No MicroPython REPL answered. Most likely MicroPython is not")
    print("installed on the Pico yet. This is how to put it there:")
    print()
    print("  1. Unplug the Pico from USB")
    print("  2. Hold the BOOTSEL button down while plugging it back in")
    print("  3. A drive named RPI-RP2 appears. It contains INFO_UF2.TXT --")
    print("     that file names the board, in case you are unsure which one it is.")
    if files:
        print("  4. Copy this file onto that drive:")
        for f in files:
            print("       %s" % os.path.join(uf2, f))
    else:
        print("  4. Copy a MicroPython UF2 for your board from micropython.org")
    print("  5. The Pico reboots and enumerates as 2E8A:0005.")
    print("     Then run this script again.")
    print()
    print("Important: for Wi-Fi use the RPI_PICO_W or RPI_PICO2_W build,")
    print("not the one without the W -- otherwise the radio driver is missing.")
    raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port, e.g. COM5 or /dev/ttyACM0")
    ap.add_argument("--ssid")
    ap.add_argument("--password", default="")
    ap.add_argument("--hostname", default="moonlamp")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--utc-offset", type=int, default=1)
    ap.add_argument("--leds", type=int, default=40)
    ap.add_argument("--led-offset", type=float, default=270.0,
                    help="angle of pixel 0; 270 = 6 o'clock, the default")
    ap.add_argument("--led-pin", type=int, default=16)
    ap.add_argument("--code-only", action="store_true",
                    help="only copy the code, leave config.json untouched")
    args = ap.parse_args()

    preflight(args.port)

    print("Creating directories")
    for d in (":lib", ":lib/moonlight"):
        try:
            mpremote(args.port, "fs", "mkdir", d)
        except SystemExit:
            pass          # already there

    print("Copying code")
    for src, dst in FILES:
        local = os.path.join(FW, src.replace("/", os.sep))
        if not os.path.exists(local):
            raise SystemExit("missing: %s" % local)
        mpremote(args.port, "fs", "cp", local, ":" + dst)

    if not args.code_only and args.ssid:
        print("Writing configuration")
        cfg = {
            "ssid": args.ssid,
            "password": args.password,
            "hostname": args.hostname,
            "utc_offset": args.utc_offset,
            "led_count": args.leds,
            "led_offset": args.led_offset,
            "led_pin": args.led_pin,
        }
        if args.lat is not None:
            cfg["latitude"] = args.lat
        if args.lon is not None:
            cfg["longitude"] = args.lon
        fd, tmp = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(cfg, fh)
        try:
            mpremote(args.port, "fs", "cp", tmp, ":config.json")
        finally:
            os.unlink(tmp)
    elif not args.code_only:
        print("No --ssid given: initial setup happens through the portal.")
        print("  Power up the Pico, join the Wi-Fi network 'Moon Lamp Setup',")
        print("  then open http://192.168.4.1")

    print("Restarting")
    mpremote(args.port, "reset")
    print("Done.")


if __name__ == "__main__":
    main()
