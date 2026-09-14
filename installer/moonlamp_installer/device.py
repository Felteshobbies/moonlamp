"""Talking to the Pico: find it, flash MicroPython, push files.

This speaks the MicroPython raw REPL protocol directly instead of driving
`mpremote` as a subprocess. Two reasons, and the first one is decisive:

* Frozen into a single executable, `sys.executable` is the executable itself,
  so `[sys.executable, "-m", "mpremote"]` -- which is how provision.py does it
  -- relaunches the installer instead of running mpremote. There is no clean
  way around that short of speaking the protocol.
* It removes a moving dependency from a tool whose whole job is to work on a
  machine we know nothing about.

The protocol is small and has been stable for years:

    Ctrl-C  interrupt whatever is running
    Ctrl-A  enter raw REPL, device answers "raw REPL; CTRL-B to exit"
    <code> Ctrl-D    device answers "OK", then output, 0x04, errors, 0x04, ">"
    Ctrl-B  back to the friendly REPL
    Ctrl-D  (friendly REPL) soft reset

Globals survive between submissions, which is what makes chunked file writes
possible without holding a whole file in the device's RAM.
"""

import binascii
import glob
import os
import sys
import time

# USB IDs of the RP2040/RP2350 family. Only 0x0005 has a REPL to talk to.
RP_VID = 0x2E8A
PID_BOOTSEL = 0x0003
PID_MICROPYTHON = 0x0005
RP_PIDS = {
    PID_BOOTSEL: "BOOTSEL mode, waiting for a UF2",
    0x0004: "PicoProbe",
    PID_MICROPYTHON: "MicroPython",
    0x000A: "a program built with the C SDK, no MicroPython",
}

CTRL_A = b"\x01"
CTRL_B = b"\x02"
CTRL_C = b"\x03"
CTRL_D = b"\x04"

# Bytes of file content per submission. Base64 expands this by 4/3, and the
# device holds one chunk plus its decoded form at once, so a few kB is the
# sensible ceiling on a board with ~150 kB of free RAM.
#
# Every chunk is a full round trip, so this is the main lever on transfer time:
# the 87 kB of firmware takes 86 round trips at 1 kB and 22 at 4 kB.
CHUNK = 4096


class DeviceError(Exception):
    pass


# --------------------------------------------------------------- discovery

def list_boards():
    """Every attached RP2040/RP2350 board, as (port, pid, description)."""
    try:
        import serial.tools.list_ports as lp
    except ImportError:
        raise DeviceError("pyserial is missing: python -m pip install pyserial")
    out = []
    for p in lp.comports():
        if p.vid == RP_VID:
            out.append((p.device, p.pid, RP_PIDS.get(p.pid, "unknown")))
    return out


def find_repl_port():
    """Port of the first board that is running MicroPython, or None."""
    for port, pid, _ in list_boards():
        if pid == PID_MICROPYTHON:
            return port
    return None


def _candidate_mounts():
    """Places a removable volume can turn up, per platform."""
    if sys.platform.startswith("win"):
        return ["%s:\\" % chr(c) for c in range(ord("A"), ord("Z") + 1)]
    out = []
    for pattern in ("/Volumes/*", "/media/*", "/media/*/*",
                    "/run/media/*/*", "/mnt/*"):
        out.extend(glob.glob(pattern))
    return out


def find_bootsel_drive():
    """The RPI-RP2 drive, identified by INFO_UF2.TXT rather than by its name.

    The volume label is not reliable -- it differs between the RP2040 and the
    RP2350 bootloaders -- but every RP2 bootloader drive carries INFO_UF2.TXT,
    and that file also names the board, which is how we can tell a Pico W from
    a plain Pico before flashing the wrong build onto it.
    """
    for root in _candidate_mounts():
        info = os.path.join(root, "INFO_UF2.TXT")
        try:
            if os.path.isfile(info):
                return root
        except OSError:
            continue
    return None


def read_board_info(drive):
    """Parse INFO_UF2.TXT into a dict. Empty when it cannot be read."""
    out = {}
    try:
        with open(os.path.join(drive, "INFO_UF2.TXT"), "r") as fh:
            for line in fh:
                if ":" in line:
                    k, v = line.split(":", 1)
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def board_family(info):
    """Chip family from INFO_UF2.TXT: "rp2350", "rp2040", or None.

    This is the one thing the bootloader genuinely tells us. It does *not*
    reveal whether a board has a radio: an RP2040 bootloader reports
    "Board-ID: RPI-RP2" for a Pico and a Pico W alike, so any attempt to spot
    the W here produces a false alarm on every Pico W there is. Whether Wi-Fi
    exists can only be established once MicroPython is running -- see
    Pico.has_wifi().

    The family does matter, though: a UF2 carries a family id and the
    bootloader silently drops blocks that do not match, so flashing across
    families is harmless but does nothing, and the board simply never comes
    back. Far better to say so before the copy.
    """
    text = " ".join(info.values()).lower()
    if "2350" in text:
        return "rp2350"
    if "rp2" in text:
        return "rp2040"
    return None


def uf2_family(path):
    """Which family a UF2 is built for, from its name."""
    name = os.path.basename(path).upper()
    if "PICO2" in name or "RP2350" in name:
        return "rp2350"
    return "rp2040"


def copy_uf2(uf2_path, drive, progress=None):
    """Copy a UF2 onto the bootloader drive.

    That really is the whole flashing procedure: the RP2 bootloader presents
    itself as mass storage and reboots as soon as it has received a complete
    image. The write therefore ends with the drive vanishing mid-copy, and on
    Windows the flush can raise -- which is success, not failure.
    """
    total = os.path.getsize(uf2_path)
    done = 0
    dst = os.path.join(drive, os.path.basename(uf2_path))
    with open(uf2_path, "rb") as src:
        try:
            with open(dst, "wb") as out:
                while True:
                    block = src.read(65536)
                    if not block:
                        break
                    out.write(block)
                    done += len(block)
                    if progress:
                        progress(done, total)
        except OSError:
            # The device rebooted while we were writing. Expected once the
            # image is complete; a real failure shows up as a board that never
            # comes back, which wait_for_repl() reports.
            if done < total * 0.9:
                raise
    return done


def wait_for_repl(timeout=30.0, poll=0.5):
    """Wait for a board to enumerate with MicroPython on it."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        port = find_repl_port()
        if port:
            # The port appears slightly before it is ready to be opened
            time.sleep(1.0)
            return port
        time.sleep(poll)
    return None


def wait_for_bootsel(timeout=60.0, poll=0.5):
    """Wait for the user to plug the board in with BOOTSEL held."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        drive = find_bootsel_drive()
        if drive:
            return drive
        time.sleep(poll)
    return None


# ------------------------------------------------------------------ REPL

class Pico(object):
    """A connection to the MicroPython REPL on the board."""

    def __init__(self, port, baud=115200, timeout=5.0):
        try:
            import serial
        except ImportError:
            raise DeviceError(
                "pyserial is missing: python -m pip install pyserial")
        try:
            self.ser = serial.Serial(port, baud, timeout=timeout)
        except Exception as exc:
            raise DeviceError("cannot open %s: %s" % (port, exc))
        self.port = port
        self._raw = False
        # Anything read past the token we were waiting for. The device
        # sends its acknowledgement, output, errors and prompt in a
        # single packet, so discarding the remainder leaves the next
        # read on an empty stream -- which looks exactly like a board
        # that stopped answering.
        self._buf = b""

    def close(self):
        try:
            if self._raw:
                self.ser.write(CTRL_B)
            self.ser.close()
        except Exception:
            pass

    def __enter__(self):
        self.enter_raw()
        return self

    def __exit__(self, *exc):
        self.close()

    # -- protocol

    def _pull(self):
        """Read whatever the port has, blocking only until the first byte.

        pyserial's read(n) waits for n bytes or the timeout, whichever comes
        first -- it does not return early just because the device stopped
        talking. Asking for a fixed 256 therefore costs the full timeout on
        every single reply, because a reply is about ten bytes long. Over a
        firmware transfer that is the difference between a second and ten
        minutes.

        So: take what is already waiting, and only block when nothing is.
        """
        waiting = getattr(self.ser, "in_waiting", 0)
        return self.ser.read(waiting if waiting else 1)

    def _read_until(self, token, timeout=10.0):
        """Read up to and including `token`, keeping whatever followed it."""
        deadline = time.time() + timeout
        while True:
            idx = self._buf.find(token)
            if idx >= 0:
                end = idx + len(token)
                out, self._buf = self._buf[:end], self._buf[end:]
                return out
            if time.time() > deadline:
                raise DeviceError("timed out waiting for %r; got %r"
                                  % (token, self._buf[-120:]))
            chunk = self._pull()
            if chunk:
                self._buf += chunk

    def enter_raw(self):
        """Interrupt whatever is running and enter the raw REPL."""
        self.ser.write(CTRL_C + CTRL_C)
        time.sleep(0.1)
        self.ser.reset_input_buffer()
        self._buf = b""
        self.ser.write(CTRL_A)
        self._read_until(b"raw REPL; CTRL-B to exit\r\n>")
        self._raw = True

    def exec_(self, code, timeout=15.0):
        """Run a snippet, return its stdout. Raises on a device traceback."""
        if not self._raw:
            self.enter_raw()
        if isinstance(code, str):
            code = code.encode()
        self.ser.write(code + CTRL_D)
        ack = self._read_until(b"OK", timeout=timeout)
        if b"OK" not in ack:
            raise DeviceError("device did not accept the submission")
        out = self._read_until(CTRL_D, timeout=timeout)[:-1]
        err = self._read_until(CTRL_D, timeout=timeout)[:-1]
        # The prompt that follows; consumed so it cannot be mistaken for output
        try:
            self._read_until(b">", timeout=2.0)
        except DeviceError:
            pass
        if err.strip():
            raise DeviceError(err.decode("utf-8", "replace").strip())
        return out.decode("utf-8", "replace")

    def eval_(self, expr, timeout=10.0):
        return self.exec_("print(repr(%s))" % expr, timeout).strip()

    def reset(self):
        """Leave the raw REPL and soft-reset, so main.py starts."""
        try:
            self.ser.write(CTRL_B)
            time.sleep(0.1)
            self.ser.write(CTRL_D)
            self._raw = False
            time.sleep(0.3)
        except Exception:
            pass

    # -- filesystem

    def makedirs(self, path):
        """Create a directory and its parents, ignoring ones already there."""
        parts = [p for p in path.split("/") if p]
        so_far = ""
        for p in parts:
            so_far = so_far + "/" + p if so_far else p
            self.exec_("import os\ntry:\n os.mkdir(%r)\nexcept OSError:\n pass"
                       % so_far)

    def put(self, data, remote, progress=None):
        """Write bytes to a file on the device, in chunks.

        Base64 rather than a bytes literal: repr() of arbitrary bytes contains
        quotes and backslashes that have to survive a round trip through the
        REPL, and base64 sidesteps the whole question at a cost of a third more
        traffic.
        """
        if isinstance(data, str):
            data = data.encode()
        if "/" in remote:
            self.makedirs(remote.rsplit("/", 1)[0])
        self.exec_("import binascii\n_f=open(%r,'wb')" % remote)
        try:
            for i in range(0, len(data), CHUNK):
                piece = binascii.b2a_base64(data[i:i + CHUNK]).strip()
                self.exec_("_f.write(binascii.a2b_base64(%r))" % piece)
                if progress:
                    progress(min(i + CHUNK, len(data)), len(data))
        finally:
            self.exec_("_f.close()\ndel _f")

    def put_file(self, local, remote, progress=None):
        with open(local, "rb") as fh:
            self.put(fh.read(), remote, progress)

    def listdir(self, path="/"):
        try:
            return eval(self.eval_("__import__('os').listdir(%r)" % path))
        except Exception:
            return []

    def exists(self, path):
        return self.eval_(
            "__import__('os').stat(%r) and True" % path).strip() == "True"

    def read_text(self, path):
        self.exec_("_f=open(%r)" % path)
        try:
            return eval(self.eval_("_f.read()"))
        finally:
            self.exec_("_f.close()\ndel _f")

    # -- what is installed

    def firmware_version(self):
        """VERSION from the moonlight package, or None when not installed."""
        try:
            out = self.exec_(
                "import sys\n"
                "sys.path.insert(0,'/lib')\n"
                "try:\n"
                " from moonlight import VERSION\n"
                " print(VERSION)\n"
                "except Exception:\n"
                " print('')")
            return out.strip() or None
        except DeviceError:
            return None

    def has_wifi(self):
        """Is there a radio driver on this board?

        The only dependable way to tell a Pico from a Pico W. The bootloader
        cannot say, and the lamp needs Wi-Fi for its clock, so a board without
        it runs the demo program for ever and nothing on the ring explains why.
        """
        probe = "\n".join((
            "try:",
            " import network",
            " network.WLAN",
            " print('yes')",
            "except Exception:",
            " print('no')",
        ))
        try:
            return self.exec_(probe).strip() == "yes"
        except DeviceError:
            return False

    def micropython_version(self):
        try:
            return eval(self.eval_("__import__('sys').version"))
        except Exception:
            return None
