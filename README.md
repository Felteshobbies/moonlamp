# Moon Lamp

A 3D-printed wall lamp that shows the **real, current phase of the moon**.

**Firmware is developed with the help from AI-**

**Printable files:** [Moon Wall Lamp with Moonphase Simulation](https://www.printables.com/model/1840057-moon-wall-lamp-with-moonphase-simulation)

A ring of RGBW LEDs lights the moon relief from the side. The relief is domed —
it rises 20 mm towards the centre — so light entering from one side is blocked
from reaching the other. That turns a brightness gradient into an actual
terminator, and the crater rims catch light beyond the shadow line exactly the
way they do in photographs of the real moon.

A Raspberry Pi Pico W computes sun and moon positions on the device and drives
the ring. No cloud service, no API key; Wi-Fi is used only to set the clock.

> **Status:** the lamp works. The firmware runs on hardware, and the optical
> and astronomical parts are covered by tests that run on a PC without any
> hardware attached. See [Status](#status) for what is still rough.

---

## Why the dome matters

The original design has a flat relief. With a flat disc, the far side of the
moon still receives about **10 %** of the light from the LEDs opposite — the
disc gets dimmer towards the far edge, but it never goes dark, so every phase
reads as "full moon, unevenly lit".

With the 20 mm dome, the shadow side drops below **0.01 %**. That is the whole
trick, and it is what makes phases legible.

The profile is conical rather than a spherical cap, which turned out to be
better on two counts: the shadow edge is sharper, and a cone is a
[developable surface][dev] — so an already printed flat relief can in principle
be warmed and formed into it, which a spherical cap cannot.

[dev]: https://en.wikipedia.org/wiki/Developable_surface

Those figures come from an optical simulation of the real relief: the STL is
rasterised into a height field, point lights are placed on the ring, and shadows
are cast with a horizon sweep per LED. The dome height, the profile and the
`ARC_TABLE` in the firmware were all chosen from that, not guessed.

---

## Repository layout

| | |
|---|---|
| [`firmware/`](firmware/) | MicroPython for the Pico W: ephemeris, rendering, dithering, PIO LED driver, web interface |
| [`installer/`](installer/) | A single executable that flashes a blank Pico and updates it later |
| [`cad/`](cad/) | FreeCAD sources of the revised frame and the PrusaSlicer projects |
| [`models/`](models/) | Where to get the printable files — **the STLs are not in git**, see [models/README.md](models/README.md) |

The model files are deliberately kept out of version control: together they are
about 1.3 GB and four of them are over GitHub's 100 MB per-file limit. They are
distributed through Printables instead.

---

## The lamp

### Parts

| Part | Notes |
|---|---|
| Raspberry Pi **Pico W** | The W matters — Wi-Fi is needed for the clock |
| SK6812 **RGBW** strip | Roughly 1.35 m. The white channel keeps the moon white; RGB-only looks dirty on grey relief and draws about three times the current |
| 5 V / 4 A supply | 40 RGBW LEDs draw 2.9 A at full white, far less in normal use |
| 74AHCT125 level shifter | **Not optional** — the Pico drives 3.3 V, the strip expects 0.7 × VDD |
| 330 Ω resistor | In series at the level shifter output |
| 1000 µF capacitor | Across the supply at the first LED |
| 3 momentary buttons | Optional — program, brighter, dimmer |

At 33 mm pitch, **40 LEDs** fill the r = 209 mm ring: 1313 mm of circumference
leaves a 26 mm gap at the seam. 39 would leave a visible 59 mm.

Feed 5 V in at **two points**, at the seam and opposite it. That halves the
copper path from 1.31 m to 0.65 m; otherwise the far side is visibly warmer in
white. Pico and strip grounds must be connected.

### Programs

| | | |
|---|---|---|
| P0 | Demo | Every state at speed, one lunation per minute. Needs neither network nor clock |
| P1 | Moon phase | The current phase, visible around the clock |
| P2 | Real moon | Like P1, but only while the moon is actually above your horizon; brightness and colour follow its altitude |
| P3 | Colour cycle | Full moon with a slowly drifting tint, white still carrying it |
| P4 | Night light | The dimmest warm white the hardware can hold across the whole ring |
| P5 | Manual | Moon phase and an explicit red/green/blue/white mix, by hand |
| P6 | Spectrum | The whole colour wheel at full saturation, one turn every seven minutes |
| P7 | Rainbow | The entire spectrum around the ring at once, turning. Everything the strip can do |

Earthshine on the dark side is simulated as well, and a red moon can be
scheduled for eclipse dates.

### Setting it up

On first boot the Pico opens its own Wi-Fi network and serves a setup page —
no cable needed after flashing. After that there is a web interface for
program, brightness, earthshine, ring geometry and output mode.

```bat
python -m pip install mpremote

REM copy the code, then configure from a phone
python firmware\tools\provision.py --port COM5

REM or preset everything right away
python firmware\tools\provision.py --port COM5 --ssid MyNetwork ^
    --password secret --lat 51.2 --lon 6.8 --leds 40
```

Details, wiring and the full parameter list: [firmware/README.md](firmware/README.md).

**Or use the installer.** A single executable takes a factory-fresh Pico all
the way to a running lamp: it flashes MicroPython, writes the firmware, asks for
Wi-Fi and where pixel 0 sits, and opens the lamp in your browser. It carries
everything it needs, so no Python, no `pip` and no network are required. The
same tool updates the lamp later, pulling newer firmware from this repository's
releases. See [installer/README.md](installer/README.md).

Either way it is no rocket science, but some experience with microcontrollers
and electronics is helpful.

---

## Tests

Everything that does not need hardware is tested on a PC:

```bat
python firmware\tests\test_ephemeris.py   REM astronomy against known quantities
python firmware\tests\test_render.py      REM arc shape, colour, dithering
python firmware\tests\test_system.py      REM time zones, config, PIO bit timing
python firmware\tests\test_web.py         REM HTTP parsing, form and route consistency
```

The ephemeris is checked against equinoxes and solstices, the synodic month,
perigee and apogee distances, and the fact that a full moon culminates at
midnight. Long-term drift over 20 years is 0.01 days per lunation.

---

## Status

* The firmware runs on real hardware. Wi-Fi, the web interface, the PIO driver
  and the buttons all work.
* **Temporal dithering over DMA** is implemented but has not been field-tested.
  It is off by default and the lamp falls back to the blocking output path if
  DMA is unavailable.
* There is no over-the-air update yet; new code goes in over USB.
* The installer executable is unsigned, so Windows SmartScreen will warn about
  it. Code signing is the only real fix and costs money; until then the folder
  build and the ZIP are flagged less often than the single file.

---

## License

Two licenses, because this repository holds two different kinds of work:

* **Software** (`firmware/`) — [MIT](LICENSE).
* **Models** (`cad/`, `models/`) — [CC BY-NC-SA 4.0](LICENSE-MODELS.md),
  inherited from the original design.

The lamp is a remix of **Illuminated Moon Wall Lamp** by
[DazedDice](https://www.printables.com/@DazedDice), by way of the
[remix](https://www.printables.com/model/1015789-illuminated-moon-wall-lamp-remix)
by [deimosfr](https://www.printables.com/@deimosfr_1155564). Full attribution
in [LICENSE-MODELS.md](LICENSE-MODELS.md).
