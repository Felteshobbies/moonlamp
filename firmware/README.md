# Moon Lamp — firmware for the Raspberry Pi Pico W

Drives an SK6812 RGBW ring inside the frame of the domed moon lamp. It computes
the real moon phase from NTP time, maps it to an arc of light and a colour, and
is controlled either by three buttons or from a browser.

> **State of things.** The lamp runs: Wi-Fi, the web interface, the PIO driver
> and the buttons all work on real hardware. The astronomy, frame composition,
> dithering, time zone handling and configuration are plain Python and are
> checked on a PC against known quantities — see [Tests](#tests). The one part
> that has not been through a field test is **temporal dithering over DMA**;
> it is off by default and falls back safely.

---

## Hardware

| Part | Value |
|---|---|
| Controller | Raspberry Pi Pico **W** (Wi-Fi is needed for NTP) |
| LED strip | SK6812 RGBW, GRBW byte order, 33 mm pitch |
| LED count | 40 on the ring (r = 209 mm, 1313 mm circumference, 9° per LED) |
| Level shifter | 74AHCT125 or 74AHCT14 — **mandatory** |
| Data line | 330 Ω in series, right at the level shifter |
| Buffer | 1000 µF across the strip supply at the first LED |
| Power supply | 5 V / 4 A (40 × 4 × 18 mA ≈ 2.9 A at full white) |

At 33 mm pitch, 40 LEDs leave a 26 mm gap at the seam. 39 would leave a visible
59 mm, so 40 is the count the ring wants.

**The level shifter is not a luxury.** The Pico outputs 3.3 V, and the WS28xx
family wants roughly 0.7 × VDD for a logic high. Without one it often works —
but temperature-dependently and unreliably. This is the single most common
reason a rebuild misbehaves.

Feed 5 V in at **two points**: at the seam and at the opposite point of the
ring. That halves the copper path from 1.31 m to 0.65 m; otherwise the far side
is visibly warmer in white.

The Pico and the strip must share a ground connection.

### Default pin assignment (changeable in `config.json`)

| Signal | GPIO |
|---|---|
| LED data | 16 |
| Button: program | 12 |
| Button: brighter | 13 |
| Button: dimmer | 14 |

Buttons switch to ground; the internal pull-ups are enabled, so no external
resistors are needed.

---

## Installation

Flash MicroPython for the Pico W first (UF2 from micropython.org), then:

```bat
python -m pip install mpremote

REM Copy the code only, configure from a phone afterwards
python firmware\tools\provision.py --port COM5

REM Or preset everything right away
python firmware\tools\provision.py --port COM5 ^
    --ssid MyNetwork --password secret ^
    --lat 51.2 --lon 6.8 --utc-offset 1 --leds 40
```

### First-time setup from a phone

With no valid Wi-Fi credentials — or when the **program button is held** during
power-up — the Pico opens a network of its own:

1. Join the Wi-Fi network `Moon Lamp Setup`
2. Open `http://192.168.4.1`
3. Fill in the form and save; the lamp restarts

The ring breathes slowly in blue while this is going on, so the state is
recognisable across the room.

Once connected, the **last octet of the IP address** is blinked out as points of
light on the ring — that way the lamp can be found without opening the router's
interface. The hostname is set over DHCP; whether `moonlamp.local` resolves
depends on your router, and on Windows without Bonjour it usually does not.

---

## Controls

| Button | Short press | Long press |
|---|---|---|
| Program | Next program, acknowledged by N points of light | Calibrate the angle offset |
| Brighter | One brightness step up | |
| Dimmer | One step down | |

Brightness steps: 9 % / 15 % / 25 % / 40 % / 65 % / 100 %, in *perceived*
brightness. They are spaced perceptually rather than linearly, because a linear
scale is unusable at the bottom and wasteful at the top.

The lowest step is set by the hardware, not by taste. With 8 bits per channel,
the dimmest level at which *every* LED still lights is one count — 1/255 of the
light, which is 9 % perceived. Below that the ring does not get dimmer, it
thins out into isolated lit pixels.

### Calibrating the angle offset

Where pixel 0 physically ended up after gluing is known only to whoever glued
it. Without that value the crescent points the wrong way.

Angles are measured looking at the lamp from the front: **0° is the right-hand
side, 90° the top, 180° the left, 270° the bottom.** The default is 270°,
because the cable channel leaves at the bottom and the strip's closing gap is
least visible there.

Long-press the program button, or use "Find the angle" in the browser. A single
point lights up: the LED that the current setting believes sits at the **bottom**
of the ring. Step it with brighter/dimmer, or with the ±1 LED buttons on the
page, until the lit LED really is at the bottom — then the angle is correct.
Press the program button again to leave. The value is written 10 s later, to
spare the flash.

This deliberately does not require you to know which physical LED is number 0,
which is the normal situation once the strip is in the frame.

### Programs

| | Name | Needs network | Needs location |
|---|---|---|---|
| P0 | Demo — every state at speed, one lunation in 60 s | no | no |
| P1 | Moon phase — live phase, always visible | yes | no |
| P2 | Real moon — only while it is actually in the sky | yes | yes |
| P3 | Colour cycle — full moon with a drifting hue | no | no |
| P4 | Night light — warm residual light, whole ring | no | no |
| P5 | Manual — azimuth, phase and colour from the browser | no | no |

**P2** fades in with the moon's altitude (off below −2°, full from +8°), makes a
low moon warmer and dimmer and a high one cooler, and dims to 8 % in daylight —
the moon is often up during the day but hardly visible then.

With no network or no clock, P1 and P2 fall back to demo mode rather than
sitting dark.

**Red moon:** list eclipse dates as `"YYYY-MM-DD"` strings under `eclipses` in
`config.json`. Computing real eclipses would be feasible on the Pico but would
fire rarely; the reddening near the horizon in P2 happens every night and uses
the RGBW strip in exactly the same way.

---

## How it works

```
config.json  ──┐
NTP ── time ───┤
               ├──► ephemeris ──► program ──► renderer ──► dither ──► PIO ──► SK6812
buttons ───────┤    phase,        P0…P5       40 pixels    8 bit
HTTP ──────────┘    altitude                  16 bit
```

### Ephemeris (`lib/moonlight/ephemeris.py`)

A Kepler orbit plus the largest perturbation terms, after Paul Schlyter.
Accuracy is around 2 arcminutes; measured long-term drift is **0.01 days per
lunation over 20 years**.

### Renderer (`lib/moonlight/render.py`)

The heart of it is `ARC_TABLE`: which arc of light produces which apparent
illuminated fraction. That table is **not guessed**. It was measured on the
height field of the real relief (`tests/calibrate_arc.py`) and hits the target
value to ±0.005 across the whole range.

An important finding: **real crescents are possible.** For any single azimuth
the shadow boundary does sit at the summit of the dome, i.e. across the middle
of the disc — but because of the 1/d² falloff the near side is far from evenly
lit. A narrow arc lights only a wedge at the rim, and that reads as a crescent.
Measured: an 8° arc gives 9 % apparent illumination.

The arc edges are soft, and the ramp is at least one LED pitch wide. Otherwise
a whole LED would snap in every few hours as the phase advances — in demo mode
you would see 40 discrete steps instead of a moving edge.

**Earthshine:** the unlit side is exactly the complementary phase, and is
lifted to 1.8 % coolly by the LEDs opposite. Ashen moonlight is a real
phenomenon, and the one thing the dome geometry cannot produce by itself.

**Colour:** the W channel carries the base brightness, RGB only the tint. White
mixed from RGB would look dirty on grey relief and would draw roughly three
times the current.

### Dithering (`lib/moonlight/dither.py`)

The most interesting states sit right at the bottom — earthshine at 1.8 %, the
night light at a few percent. Rounded naively to 8 bits you land on counts of 2
to 5, where the steps become visible and white shifts hue as it dims, because
all four channels round differently.

The default is **spatial** dithering around the ring. Neighbouring LEDs
illuminate heavily overlapping areas of the moon, so rounding one up and the
next one down averages out on the surface with no time component at all. The
state is rebuilt for every frame from a fixed starting index, which means a
still image produces bit-identical output frame after frame — nothing can
flicker, by construction, and 60 Hz is plenty.

Measured residual error at the low steps: **0.02 instead of 0.50 of an 8-bit
step.**

Optionally, **temporal dithering** can be switched on from the Output section
of the web page. It splits each frame into several subframes whose time average
resolves finer than a single count, which buys about three extra bits exactly
where they are needed, and makes individual LEDs fade in smoothly instead of
snapping on. That needs the DMA output path: the CPU only starts the transfer
and a DMA channel feeds the PIO FIFO, so the output costs no CPU time. If DMA
cannot be set up the lamp says so and stays on the blocking path — the setting
never takes the lamp down.

The spatial pattern would only be visible right in front of the LEDs in the
outermost ring, and the frame's front lip hides that anyway.

### LED driver (`lib/moonlight/leds.py`)

The PIO state machine generates the one-wire timing exactly and without jitter,
whatever the CPU is doing. 12 PIO cycles per bit at 10 MHz gives T0H 0.30 /
T0L 0.90 / T1H 0.60 / T1L 0.60 µs.

The obvious shortcut is to reuse the WS2812B numbers, but the SK6812 wants a
symmetric one bit; with WS2812B timing both halves sit outside the window, and
the shortest pulse — the 0.25 µs high of a zero — is the first thing a marginal
driver loses.

The transmit FIFO is joined (`JOIN_TX`), doubling it from four words to eight.
One word is one pixel and takes 38.4 µs to shift out, so the buffer grows from
154 µs to 307 µs. That matters because the strip latches after 80 µs of idle:
if the FIFO ever runs dry mid-frame, the remaining pixels are written to LED 0
onwards and the first LEDs flash.

On the blocking path the frame is pushed with interrupts disabled. That costs
about a tenth of the CPU at 60 Hz and is invisible to Wi-Fi, whereas an
underrun is immediately visible on the ring.

---

## Tests

All of these run on a PC under CPython, with no Pico attached:

```bat
python firmware\tests\test_ephemeris.py     REM astronomy against known quantities
python firmware\tests\test_render.py        REM frame composition, colour, dithering
python firmware\tests\test_system.py        REM time zone, configuration, programs
python firmware\tests\test_web.py           REM HTTP parsing, forms, routes
```

`test_ephemeris.py` checks, among other things, equinoxes and solstices to
0.01°, perigee and apogee distances, the spread of lunations against the real
range of 29.27–29.83 d, long-term drift over 20 years, and that a full moon
culminates at midnight.

`test_system.py` also parses the PIO assembly and compares the literals in it
against the timing constants in the same module, because `asm_pio()` runs its
body in a namespace of its own where module-level names are invisible. The two
therefore cannot drift apart unnoticed.

`ARC_TABLE` in `render.py` is the one thing this suite does not re-derive.
Reproducing it needs the STL of the relief, numpy, and the optical simulation
it was measured with. What the tests do check is that the values behave: the
arc grows monotonically with the illuminated fraction, the edges stay soft, and
nothing jumps as the azimuth or the phase moves.

---

## The browser interface

Once the lamp is on the network it is reachable at the IP that `status.py`
reports, e.g. `http://192.0.2.42/`. The page refreshes itself every 30
seconds and follows the light or dark system theme.

It shows the running program, brightness, signal strength, IP, local time and
date, the moon phase with its age and distance, and the moon's altitude above
the horizon. You can set the program, the brightness step, the earthshine
level, the ring geometry, the output mode, and manual mode P5 with its
illuminated fraction, direction and warmth.

Three device actions sit at the end of the page:

| Link | Effect |
|---|---|
| Find the angle | Starts the same mode as a long press on the program button |
| Restart | Soft reset |
| Forget Wi-Fi | Clears the credentials and reopens the setup portal |

The page computes nothing itself: `main.py` gathers the values in
`build_info()` and hands them over ready-made, so that loading the page does
not disturb the frame rate.

For tweaking the appearance without a device, a rendered sample sits in
`tests/control_page_sample.html`.

---

## Reading the status

```bat
python firmware\tools\status.py            REM finds the port by itself
python firmware\tools\status.py --scan     REM also lists networks in range
```

This prints the configuration, the Wi-Fi status in plain words, IP, gateway,
RSSI, the URL of the control page and the clock that was set. The call briefly
interrupts the running program and restarts it afterwards (`--no-reset`
suppresses that).

The CYW43 status codes are unusable without translation:

| Code | Meaning |
|---|---|
| `3` | Got an IP, all good |
| `-1` | Link down |
| `-2` | Joining — stays here when the SSID does not match |
| `-3` | Authentication failed, usually the password |
| `-4` | Network not found |

**Wi-Fi names are case-sensitive.** `mynetwork` and `MyNetwork` are two different
networks. Mistype that in the portal and the station sits at `-2`, which looks
like a password problem. `connect()` now catches this itself: if the scan finds
a network that differs only in spelling, it corrects the configuration and
reconnects. The REPL then shows:

```
Wi-Fi: no luck, status -2 (joining)
Wi-Fi: in range this network is called 'MyNetwork', not 'mynetwork' -- correcting and saving
Wi-Fi: connected as 192.0.2.42 , -36 dBm -> http://192.0.2.42/
```

To follow along live: `mpremote connect COM5 repl` (Ctrl-D restarts).

---

## When something does not work

| Symptom | Cause |
|---|---|
| Wrong colours | Byte order — `leds.py` writes GRBW; swap there for other strips |
| First LEDs fine, rubbish further along | Level shifter missing, or grounds not connected |
| White turns yellowish towards the far side | Voltage drop, the second feed point is missing |
| The first LEDs flash during updates | FIFO underrun — check that `JOIN_TX` is active and interrupts are disabled on the blocking path |
| Crescent points the wrong way | Calibrate the angle offset, and check `led_clockwise` |
| The lamp stays in demo mode | No NTP time — check Wi-Fi |
| The portal does not appear | Hold the program button while powering up |

### When the upload does not work

`provision.py` checks in advance whether a MicroPython REPL actually answers on
the port, and names the reason if not. By far the most common case with a new
board:

**There is no MicroPython on the Pico yet.** A factory-fresh board, or one
flashed with the C SDK, does enumerate over USB but has no REPL for `mpremote`
to talk to. The USB identifier gives it away:

| USB ID | Meaning |
|---|---|
| `2E8A:0003` | BOOTSEL mode, drive `RPI-RP2` |
| `2E8A:0005` | **MicroPython** — the upload only works with this |
| `2E8A:000A` | A program built with the C SDK, no MicroPython |

Installing MicroPython:

1. Unplug the Pico
2. Hold BOOTSEL and plug it in while holding
3. The drive `RPI-RP2` appears. `INFO_UF2.TXT` on it names the board, in case
   it is unclear which one is plugged in
4. Copy the `RPI_PICO_W-*.uf2` build onto the drive
5. The Pico restarts and enumerates as `2E8A:0005`

For Wi-Fi you need the **W variant** (`RPI_PICO_W`, or `RPI_PICO2_W` on a
Pico 2 W) — without the W there is no radio driver and `import network` fails.
The build this was developed against is `RPI_PICO_W-20260824-v1.29.0.uf2`; get
it from [micropython.org/download](https://micropython.org/download/).

List the attached boards:

```bat
python -c "import serial.tools.list_ports as l; [print(p.device, hex(p.vid or 0), p.description) for p in l.comports()]"
```
