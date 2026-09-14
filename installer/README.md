# Moon Lamp Installer

Takes a Raspberry Pi Pico W from factory-fresh to a running lamp, and updates
one later. A single executable with no Python, no `pip` and no network needed —
it carries both the firmware and a MicroPython build inside it.

```
moonlamp-installer              opens the window
moonlamp-installer status       what is attached and what is on it
moonlamp-installer install      flash and set up a board
moonlamp-installer update       newest firmware, settings kept
moonlamp-installer restart      restart the lamp, change nothing
moonlamp-installer config       show the lamp's settings, change none
moonlamp-installer version      what this build carries
moonlamp-installer releases     what has been published
```

## What it does

1. Finds the board by its USB identifier, and says which state it is in —
   BOOTSEL, MicroPython, or something else entirely.
2. If MicroPython is missing, walks you through BOOTSEL and copies the UF2
   across. That really is all flashing is: the bootloader appears as a drive
   and reboots once it has a complete image.
3. Writes the firmware over the serial port.
4. Asks for Wi-Fi, location, LED count and **where pixel 0 sits, as a clock
   position** — the same way the lamp's own web page asks.
5. Restarts the lamp, finds its address and offers to open it.

### What the bootloader can and cannot tell us

`INFO_UF2.TXT` on the BOOTSEL drive names the chip family, and that is checked
before anything is written: a UF2 carries a family id and the bootloader
silently discards blocks that do not match, so flashing an RP2040 build onto a
Pico 2 does nothing at all and the board just never comes back. Refusing up
front with an explanation is far kinder than that silence.

What it cannot tell us is whether the board has a radio. An RP2040 bootloader
reports `Board-ID: RPI-RP2` for a Pico and a Pico W alike, so any attempt to
spot the W there raises a false alarm on every Pico W there is. That question is
therefore settled afterwards, by asking the running MicroPython whether
`network` imports — and if it does not, the installer says so plainly, because
a lamp without Wi-Fi never gets the time and sits in demo mode for ever.

The update path compares what is on the board against both the copy inside the
installer and the newest release on GitHub, and offers whichever is newer.
Settings are never touched by an update.

### Settings are read before they are written

The settings form is pre-filled with sensible defaults, and defaults are
precisely what must not land on a lamp that is already configured. So the
current `config.json` is read off the board as soon as one with firmware is
found, the form shows those values, and **only fields you actually changed are
written back**. A confirmation lists them by name before anything is sent.

A blank field never means "erase this". That matters most for the password: it
would otherwise take the lamp off the network on a stray save, and the mistake
would only show up minutes later when the clock failed to set.

`moonlamp-installer config` prints what is on the lamp and changes nothing.

"Save and restart" restarts the lamp even when nothing needed writing. The
button names two things, and one that quietly does neither is worse than one
that does the harmless half.

## Why it does not use mpremote

`provision.py` drives `mpremote` as a subprocess, which is fine from a source
checkout and impossible once frozen: in a one-file build `sys.executable` is
the executable itself, so `[sys.executable, "-m", "mpremote"]` relaunches the
installer. [`device.py`](moonlamp_installer/device.py) therefore speaks the
MicroPython raw REPL protocol directly. It is about 150 lines and has the
pleasant side effect of removing a moving dependency from a tool whose entire
job is to work on a machine we know nothing about.

## Building

```bat
python -m pip install pyinstaller pyserial
python installer\build.py
```

The result is `installer/dist/moonlamp-installer.exe`, around 11 MB. The
firmware is staged into the package first rather than referenced in place, so
an executable always carries exactly what was in the repository when it was
built — an installer that quietly picked up a half-edited working tree would be
worse than none.

`--onedir` builds a folder instead of a single file. That starts faster and is
flagged less often by antivirus software, at the cost of not being one file.

### About the antivirus problem

Unsigned one-file PyInstaller executables are routinely flagged by Windows
SmartScreen and sometimes quarantined outright by antivirus software. This is
not a rare edge case, and for a tool that writes firmware to hardware it is a
bad first impression. The only reliable fix is a code signing certificate
(200–400 € a year). Without one, expect to tell people to click through
"Windows protected your PC", which is itself poor advice to be giving.

The `--onedir` build and a plain ZIP are flagged noticeably less often.

## Testing

```bat
python installer\tests\test_installer.py
```

Runs without a Pico. It covers version comparison, the release archive format,
update decisions when GitHub is unreachable, and the REPL file transfer against
a fake serial port — that last one caught a real bug where the read loop
discarded whatever arrived in the same packet as the token it was waiting for,
which is exactly how a real device answers.

It also checks that the installer's copy of the clock-position conversion still
matches the firmware's. The installer cannot import the firmware at runtime —
it is what puts it there — so that conversion is duplicated on purpose, and the
test is what stops the copy drifting.

## Requirements from source

Python 3.7 or newer and `pyserial`. tkinter for the window, which ships with
Python on Windows and macOS; on Linux it is usually a separate package
(`python3-tk`). Without it the console commands still work.
