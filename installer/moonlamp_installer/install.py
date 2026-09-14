"""The actual procedures, independent of how they are driven.

Both the console and the window call into here, so the two can never drift
apart in what they do -- only in how they ask.

Progress is reported through a callback taking (stage, done, total, text).
Anything may be None except the stage.
"""

import json
import time

from . import device
from . import releases


def clock_to_angle(hour):
    """Clock position -> the angle the firmware stores in led_offset.

    Deliberately a copy of render.clock_to_angle rather than an import: the
    installer must run without the firmware package on the path, since it is
    what puts it there. tests/test_installer.py compares the two so the copy
    cannot drift.
    """
    return (90.0 - 30.0 * (int(hour) % 12)) % 360.0


def angle_to_clock(angle):
    """The inverse, for showing an existing configuration."""
    h = int(round((90.0 - float(angle)) / 30.0)) % 12
    return 12 if h == 0 else h


class Step(object):
    DETECT = "detect"
    MICROPYTHON = "micropython"
    FIRMWARE = "firmware"
    CONFIG = "config"
    RESTART = "restart"


def _say(report, stage, text, done=None, total=None):
    if report:
        report(stage, done, total, text)


# --------------------------------------------------------------- surveying

def survey(report=None):
    """What is attached, and what state is it in?

    Returned as a dict rather than printed, because the window needs the same
    answer the console does.
    """
    boards = device.list_boards()
    drive = device.find_bootsel_drive()
    out = {
        "boards": boards,
        "bootsel_drive": drive,
        "board_info": device.read_board_info(drive) if drive else {},
        "repl_port": device.find_repl_port(),
        "firmware": None,
        "micropython": None,
    }
    _say(report, Step.DETECT, "%d board(s) on USB" % len(boards))
    if out["repl_port"]:
        try:
            pico = device.Pico(out["repl_port"])
            try:
                pico.enter_raw()
                out["firmware"] = pico.firmware_version()
                out["micropython"] = pico.micropython_version()
            finally:
                pico.close()
        except device.DeviceError as exc:
            out["error"] = str(exc)
    return out


# ------------------------------------------------------------ MicroPython

def flash_micropython(uf2_path=None, drive=None, report=None, timeout=60.0):
    """Copy a MicroPython UF2 onto a board waiting in BOOTSEL mode.

    Returns the serial port it comes back on. The caller is responsible for
    getting the board into BOOTSEL in the first place -- that needs a human
    holding a button, which no amount of software can do.
    """
    uf2_path = uf2_path or releases.bundled_uf2()
    if not uf2_path:
        raise device.DeviceError(
            "no MicroPython build bundled; fetch one from micropython.org")

    drive = drive or device.wait_for_bootsel(timeout)
    if not drive:
        raise device.DeviceError(
            "no board in BOOTSEL mode appeared. Unplug the Pico, hold BOOTSEL "
            "down, plug it back in while still holding, then release.")

    info = device.read_board_info(drive)
    board = info.get("Board-ID") or info.get("Model") or "unknown board"
    _say(report, Step.MICROPYTHON, "found %s on %s" % (board, drive))

    if info and not device.board_wants_wifi_build(info) and "_W" in uf2_path:
        _say(report, Step.MICROPYTHON,
             "warning: %s does not look like a W variant, but the build is "
             "for one. Wi-Fi will not work." % board)

    def prog(done, total):
        _say(report, Step.MICROPYTHON, "writing MicroPython", done, total)

    device.copy_uf2(uf2_path, drive, prog)
    _say(report, Step.MICROPYTHON, "waiting for the board to come back")
    port = device.wait_for_repl(timeout=40.0)
    if not port:
        raise device.DeviceError(
            "the board did not come back with MicroPython on it. If it is a "
            "Pico 2, it needs the RPI_PICO2_W build instead.")
    _say(report, Step.MICROPYTHON, "MicroPython is running on %s" % port)
    return port


# --------------------------------------------------------------- firmware

def install_firmware(port, files=None, report=None):
    """Write a firmware file set to the board."""
    files = files or releases.bundled_firmware()
    version = releases.version_of(files) or "unknown"
    total = sum(len(v) for v in files.values())
    written = [0]

    pico = device.Pico(port)
    try:
        pico.enter_raw()
        # In the order releases.DEVICE_FILES gives them: main.py last, so an
        # interrupted install leaves a board that still boots the old one.
        for name in releases.DEVICE_FILES:
            data = files[name]

            def prog(done, size, name=name):
                _say(report, Step.FIRMWARE, name,
                     written[0] + done, total)

            pico.put(data, name, prog)
            written[0] += len(data)
            _say(report, Step.FIRMWARE, name, written[0], total)
    finally:
        pico.close()
    _say(report, Step.FIRMWARE, "firmware %s installed" % version, total, total)
    return version


def read_config(port):
    """The config.json already on the board, or {} when there is none."""
    pico = device.Pico(port)
    try:
        pico.enter_raw()
        try:
            return json.loads(pico.read_text("config.json"))
        except Exception:
            return {}
    finally:
        pico.close()


def write_config(port, settings, merge=True, report=None):
    """Write config.json, keeping any keys the caller did not mention."""
    cfg = read_config(port) if merge else {}
    cfg.update({k: v for k, v in settings.items() if v is not None})
    pico = device.Pico(port)
    try:
        pico.enter_raw()
        pico.put(json.dumps(cfg).encode(), "config.json")
    finally:
        pico.close()
    _say(report, Step.CONFIG, "settings written")
    return cfg


def restart(port, report=None):
    pico = device.Pico(port)
    try:
        pico.enter_raw()
        pico.reset()
    finally:
        pico.close()
    _say(report, Step.RESTART, "the lamp is restarting")
    time.sleep(1.0)


# ------------------------------------------------------------------ update

def check_for_update(installed, include_prereleases=False):
    """Is there a published release newer than what is on the board?

    Returns (release_or_None, reason). The bundled copy counts too: an
    installer downloaded last month may well be newer than the board.
    """
    bundled = releases.bundled_version()
    best, source = None, None
    if releases.is_newer(bundled, installed):
        best, source = {"version": bundled, "asset": None,
                        "name": "bundled with this installer",
                        "notes": "", "prerelease": False}, "bundled"
    try:
        rel = releases.latest_release(include_prereleases)
    except releases.ReleaseError as exc:
        return best, ("offline: %s" % exc) if best else str(exc)
    if rel and releases.is_newer(rel["version"], installed):
        if not best or releases.is_newer(rel["version"], best["version"]):
            best, source = rel, "github"
    if not best:
        return None, "the board is already on the newest version"
    return best, source


def fetch_firmware(release):
    """File set for a release from check_for_update()."""
    if release.get("asset"):
        return releases.download_firmware(release["asset"])
    return releases.bundled_firmware()
