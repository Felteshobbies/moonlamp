"""Console front end.

Everything the window can do, without the window -- useful over SSH, in a
workshop, and for anyone who would rather see what is happening.

    moonlamp-installer                 guided install, asks as it goes
    moonlamp-installer status          what is attached and what is on it
    moonlamp-installer update          newest firmware onto an installed board
    moonlamp-installer install --port COM5 --ssid Net --password secret
"""

import argparse
import os
import sys

from . import device
from . import install
from . import releases

BAR = 34


def report(stage, done, total, text):
    if done is not None and total:
        filled = int(BAR * done / float(total))
        sys.stdout.write("\r  %-13s [%s%s] %3d %%  %-24s"
                         % (stage, "#" * filled, "." * (BAR - filled),
                            100 * done / total, text[:24]))
        if done >= total:
            sys.stdout.write("\n")
    else:
        sys.stdout.write("\r  %-13s %-58s\n" % (stage, text))
    sys.stdout.flush()


def _print_bundled():
    uf2 = releases.bundled_uf2()
    print("  Bundled     : firmware %s%s"
          % (releases.bundled_version(),
             ", MicroPython " + os.path.basename(uf2) if uf2 else
             ", no MicroPython build"))


def cmd_status(args):
    state = install.survey(report)
    print()
    if not state["boards"] and not state["bootsel_drive"]:
        _print_bundled()
        print()
        print("No Raspberry Pi board found on USB.")
        print("If one is plugged in, it may need a data cable rather than a")
        print("charging cable -- those look identical and carry no data.")
        return 1
    for port, pid, what in state["boards"]:
        print("  %-10s USB 2E8A:%04X  %s" % (port, pid, what))
    if state["bootsel_drive"]:
        info = state["board_info"]
        print("  %-10s BOOTSEL drive, board %s"
              % (state["bootsel_drive"], info.get("Board-ID", "unknown")))
    if state["micropython"]:
        print("  MicroPython : %s" % state["micropython"])
        print("  Wi-Fi       : %s" % ("yes" if state.get("wifi") else
                                      "no radio -- this is not a W board"))
    if state["firmware"]:
        print("  Firmware    : %s" % state["firmware"])
        rel, why = install.check_for_update(state["firmware"],
                                            args.prereleases)
        if rel:
            print("  Update      : %s available (%s)" % (rel["version"], why))
        else:
            print("  Update      : %s" % why)
    elif state["repl_port"]:
        print("  Firmware    : not installed")
    _print_bundled()
    return 0


def _ensure_board(args):
    """Get to a board with MicroPython on it, flashing if need be."""
    port = args.port or device.find_repl_port()
    if port:
        return port

    drive = device.find_bootsel_drive()
    if not drive:
        print()
        print("No board with MicroPython found. To put it there:")
        print("  1. Unplug the Pico")
        print("  2. Hold BOOTSEL down and plug it back in, still holding")
        print("  3. Release -- a drive called RPI-RP2 appears")
        print()
        print("Waiting for that drive ...")
        drive = device.wait_for_bootsel(120.0)
        if not drive:
            raise SystemExit("gave up waiting for a board in BOOTSEL mode")
    return install.flash_micropython(args.uf2, drive, report)


def _settings_from_args(args):
    out = {}
    for key, val in (("ssid", args.ssid), ("password", args.password),
                     ("hostname", args.hostname),
                     ("latitude", args.lat), ("longitude", args.lon),
                     ("utc_offset", args.utc_offset),
                     ("led_count", args.leds), ("led_pin", args.led_pin)):
        if val is not None:
            out[key] = val
    if args.pixel_clock is not None:
        out["led_offset"] = install.clock_to_angle(args.pixel_clock)
    return out


def cmd_install(args):
    port = _ensure_board(args)
    files = releases.bundled_firmware()
    if args.online:
        rel = releases.latest_release(args.prereleases)
        if rel and releases.is_newer(rel["version"],
                                     releases.version_of(files)):
            print("  fetching firmware %s from GitHub" % rel["version"])
            files = install.fetch_firmware(rel)
    install.install_firmware(port, files, report)

    settings = _settings_from_args(args)
    if settings:
        install.write_config(port, settings, report=report)
    elif not args.code_only:
        print()
        print("  No Wi-Fi given, so setup happens on a phone:")
        print("    power the lamp, join the network 'Moon Lamp Setup',")
        print("    then open http://192.168.4.1")
    install.restart(port, report)
    print()
    print("Done.")
    return 0


def cmd_update(args):
    port = args.port or device.find_repl_port()
    if not port:
        raise SystemExit("no board with MicroPython found -- run 'install'")
    state = install.survey()
    installed = state.get("firmware")
    print("  installed: %s" % (installed or "nothing"))

    rel, why = install.check_for_update(installed, args.prereleases)
    if not rel and not args.force:
        print("  %s" % why)
        return 0
    if rel:
        print("  updating to %s (%s)" % (rel["version"], why))
        files = install.fetch_firmware(rel)
    else:
        print("  forcing a reinstall of the bundled firmware")
        files = releases.bundled_firmware()

    install.install_firmware(port, files, report)
    install.restart(port, report)
    print()
    print("Done. The configuration was left untouched.")
    return 0


def cmd_config(args):
    """Show what is on the lamp, without changing any of it."""
    port = args.port or device.find_repl_port()
    if not port:
        raise SystemExit("no board with MicroPython found")
    cfg = install.read_config(port)
    if not cfg:
        print("  The lamp has no config.json yet.")
        return 0
    for key in sorted(cfg):
        val = cfg[key]
        if key == "password":
            val = ("set, %d characters" % len(val)) if val else "empty"
        elif key == "led_offset":
            val = "%g deg -- %d o'clock" % (val, install.angle_to_clock(val))
        print("  %-12s: %s" % (key, val))
    return 0


def cmd_releases(args):
    for rel in releases.list_releases(args.prereleases):
        mark = " (pre-release)" if rel["prerelease"] else ""
        print("  %-10s %s%s" % (rel["version"], rel["name"] or "", mark))
        if not rel["asset"]:
            print("             no firmware archive attached")
    return 0


def cmd_version(args):
    """What this build is and what it carries. Touches no hardware."""
    from . import VERSION
    print("  moonlamp-installer %s" % VERSION)
    _print_bundled()
    return 0


def build_parser():
    ap = argparse.ArgumentParser(
        prog="moonlamp-installer",
        description="Install and update the moon lamp firmware on a Pico W.")
    ap.add_argument("--version", action="store_true",
                    help="show what this build carries and exit")
    ap.add_argument("--port", help="serial port, e.g. COM5 or /dev/ttyACM0")
    ap.add_argument("--prereleases", action="store_true",
                    help="also consider pre-releases on GitHub")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("status", help="what is attached and what is on it")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("install", help="flash and set up a board")
    p.add_argument("--uf2", help="MicroPython UF2 to use instead of the "
                                 "bundled one")
    p.add_argument("--online", action="store_true",
                   help="take the newest firmware from GitHub")
    p.add_argument("--code-only", action="store_true",
                   help="do not touch config.json")
    p.add_argument("--ssid")
    p.add_argument("--password")
    p.add_argument("--hostname")
    p.add_argument("--lat", type=float)
    p.add_argument("--lon", type=float)
    p.add_argument("--utc-offset", type=int)
    p.add_argument("--leds", type=int)
    p.add_argument("--led-pin", type=int)
    p.add_argument("--pixel-clock", type=int, metavar="HOUR",
                   help="where pixel 0 sits, read as a clock face: "
                        "12 top, 3 right, 6 bottom, 9 left")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("update", help="newest firmware, settings kept")
    p.add_argument("--force", action="store_true",
                   help="reinstall even when nothing is newer")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("version", help="what this build carries")
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("config", help="show the lamp's settings, change none")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("releases", help="what has been published")
    p.set_defaults(func=cmd_releases)
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if getattr(args, "version", False):
        return cmd_version(args)
    if not getattr(args, "func", None):
        args = ap.parse_args((argv or []) + ["status"])
    try:
        return args.func(args)
    except (device.DeviceError, releases.ReleaseError) as exc:
        sys.stderr.write("\n%s\n" % exc)
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\ninterrupted\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
