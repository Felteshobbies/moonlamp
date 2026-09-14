"""Check the installer without a Pico attached.

    python installer\\tests\\test_installer.py

Everything here is either pure logic or exercised against a fake serial port,
so it runs in CI and on any machine.
"""

import io
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
REPO = os.path.abspath(os.path.join(ROOT, os.pardir))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(REPO, "firmware", "lib"))

from moonlamp_installer import device, install, releases   # noqa: E402

FAILED = []


def ok(name, cond, detail=""):
    print("  %-54s %s %s" % (name, "ok" if cond else "FAILED", detail))
    if not cond:
        FAILED.append(name)


print("1. Version comparison")

cases = [
    ("0.2", "0.1", True), ("0.1", "0.2", False),
    ("0.2", "0.2", False),
    ("0.2", "0.2-dev", True),        # a release beats its own pre-release
    ("0.2-dev", "0.2", False),
    ("0.10", "0.9", True),           # not string order
    ("1.0", "0.99", True),
    ("0.2", None, True),             # nothing installed
    ("0.2", "", True),
    (None, "0.1", False),            # nothing to offer
    ("v0.3", "0.2", True),           # tag names carry a v
]
bad = [(a, b) for a, b, want in cases if releases.is_newer(a, b) != want]
ok("is_newer agrees on every case", not bad, str(bad))

ok("0.1.9 sorts below 0.2", releases.is_newer("0.2", "0.1.9"))
ok("unparseable versions are never offered",
   not releases.is_newer("not-a-version", "0.1"))

print()
print("2. The firmware carried inside the installer")

fw = releases.bundled_firmware()
ok("every device file is present",
   sorted(fw) == sorted(releases.DEVICE_FILES),
   "%d files" % len(fw))
ok("main.py is written last", releases.DEVICE_FILES[-1] == "main.py")
ok("the version can be read out of it",
   releases.version_of(fw) is not None, str(releases.version_of(fw)))

# The bundled set must be exactly what the release archive ships, or an
# installer and a downloaded update would put different things on the board.
try:
    from moonlight import VERSION as fw_version
    ok("bundled version matches the firmware package",
       releases.version_of(fw) == fw_version, fw_version)
except ImportError:
    ok("firmware package importable for comparison", False, "not on the path")

uf2 = releases.bundled_uf2()
ok("a MicroPython build is bundled", uf2 is not None,
   os.path.basename(uf2) if uf2 else "missing")
ok("it is a W build -- the lamp needs Wi-Fi for its clock",
   bool(uf2) and "_W" in os.path.basename(uf2).upper(),
   os.path.basename(uf2) if uf2 else "")

print()
print("3. Clock positions match the firmware exactly")

# The installer cannot import the firmware at runtime -- it is what installs it
# -- so the conversion is duplicated. This is the guard against that copy
# drifting away from the original.
try:
    from moonlight import render
    bad = [h for h in range(1, 13)
           if install.clock_to_angle(h) != render.clock_to_angle(h)]
    ok("clock_to_angle is identical to the firmware's", not bad, str(bad))
    bad = [a for a in range(0, 360, 5)
           if install.angle_to_clock(a) != render.angle_to_clock(a)]
    ok("angle_to_clock is identical to the firmware's", not bad, str(bad))
    ok("the default is 6 o'clock",
       install.clock_to_angle(6) == render.CALIBRATION_ANGLE == 270.0)
except ImportError:
    ok("firmware render module importable", False, "not on the path")

print()
print("4. Release archives are read the way they are built")

# Build an archive shaped like make_release.py's output and read it back
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    for name in releases.DEVICE_FILES:
        z.writestr("moonlamp-firmware-9.9/" + name, fw[name])
    z.writestr("moonlamp-firmware-9.9/README.md", b"not a device file")

saved = releases._get
releases._get = lambda url, accept=None: buf.getvalue()
try:
    got = releases.download_firmware("http://example.invalid/x.zip")
    ok("every device file comes back out", sorted(got) ==
       sorted(releases.DEVICE_FILES), "%d files" % len(got))
    ok("contents survive the round trip", got == fw)
    ok("files that do not belong on the device are left out",
       "README.md" not in got)
finally:
    releases._get = saved

# An archive missing a file must be refused rather than half-installed
buf2 = io.BytesIO()
with zipfile.ZipFile(buf2, "w") as z:
    for name in releases.DEVICE_FILES[:-1]:
        z.writestr("x/" + name, b"x")
releases._get = lambda url, accept=None: buf2.getvalue()
try:
    releases.download_firmware("http://example.invalid/x.zip")
    ok("an incomplete archive is refused", False, "it was accepted")
except releases.ReleaseError as exc:
    ok("an incomplete archive is refused", "main.py" in str(exc), str(exc))
finally:
    releases._get = saved

print()
print("5. Update decisions")


def _offline(*a, **k):
    raise releases.ReleaseError("no connection to GitHub: test")


saved = releases.latest_release
releases.latest_release = _offline
try:
    rel, why = install.check_for_update("0.0.1")
    ok("an old board is still updated from the bundle when offline",
       rel is not None and rel["asset"] is None, str(why))
    rel, why = install.check_for_update(releases.bundled_version())
    ok("an up-to-date board reports the outage rather than an update",
       rel is None and "connection" in why, str(why))
finally:
    releases.latest_release = saved

releases.latest_release = lambda pre=False: {
    "version": "99.0", "asset": "http://example.invalid/x.zip",
    "name": "test", "notes": "", "prerelease": False}
try:
    rel, why = install.check_for_update("0.1")
    ok("GitHub wins when it has something newer than the bundle",
       rel["version"] == "99.0" and why == "github", str(why))
finally:
    releases.latest_release = saved

print()
print("6. The REPL protocol, against a fake port")


class FakeSerial(object):
    """Answers like a MicroPython raw REPL, and records what was written."""

    def __init__(self, *a, **k):
        self.written = b""
        self.pending = b""

    def write(self, data):
        self.written += data
        if data == b"\x01":
            self.pending += b"raw REPL; CTRL-B to exit\r\n>"
        elif data.endswith(b"\x04"):
            # OK, no output, no error, prompt
            self.pending += b"OK\x04\x04>"
        return len(data)

    def read(self, n=1):
        out, self.pending = self.pending[:n], self.pending[n:]
        return out

    def reset_input_buffer(self):
        self.pending = b""

    def close(self):
        pass


class FakeSerialModule(object):
    Serial = FakeSerial


sys.modules["serial"] = FakeSerialModule()

pico = device.Pico("FAKE")
pico.enter_raw()
payload = bytes(bytearray(range(256))) * 9        # 2304 bytes, spans chunks
pico.put(payload, "lib/moonlight/render.py")
sent = pico.ser.written

ok("the file is opened for writing in binary",
   b"open('lib/moonlight/render.py','wb')" in sent)
ok("parent directories are created first",
   b"os.mkdir('lib')" in sent and b"os.mkdir('lib/moonlight')" in sent)

import binascii                                   # noqa: E402
chunks = sent.count(b"a2b_base64")
expected = (len(payload) + device.CHUNK - 1) // device.CHUNK
ok("the payload is split into chunks", chunks == expected,
   "%d chunks for %d bytes" % (chunks, len(payload)))

# Reassemble what the device would have received and compare it to the source
rebuilt = b""
for piece in sent.split(b"a2b_base64(")[1:]:
    literal = piece.split(b"))")[0]
    rebuilt += binascii.a2b_base64(eval(literal))
ok("what arrives is byte-identical to what was sent", rebuilt == payload,
   "%d of %d bytes" % (len(rebuilt), len(payload)))
ok("the file handle is closed and cleaned up",
   b"_f.close()" in sent and b"del _f" in sent)

print()
print("7. Board identification")

ok("only 0x0005 is treated as MicroPython",
   device.RP_PIDS[0x0005] == "MicroPython" and device.PID_MICROPYTHON == 0x0005)
ok("BOOTSEL is 0x0003", device.PID_BOOTSEL == 0x0003)
ok("'Raspberry Pi Pico W' reads as a W board",
   device.board_wants_wifi_build({"Model": "Raspberry Pi Pico W"}))
ok("'Raspberry Pi Pico' does not",
   not device.board_wants_wifi_build({"Model": "Raspberry Pi Pico"}))

print()
if FAILED:
    print("FAILED: %d checks -> %s" % (len(FAILED), ", ".join(FAILED)))
    raise SystemExit(1)
print("All checks passed.")
