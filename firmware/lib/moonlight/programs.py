"""The lamp's programs.

Each program is handed the current moment and returns a 16-bit frame. Pure
Python, so every program can be computed and rendered on a PC.

  P0  Demo         every state at high speed, one lunation per minute
  P1  Moon phase   live phase, always visible, needs no location
  P2  Real moon    like P1, but only while the moon is actually up;
                   brightness and colour follow its altitude
  P3  Colour cycle full moon with a slowly drifting tint, white still dominant
  P4  Night light  dimmest possible warm white across the whole ring
  P5  Manual       phase and an explicit RGBW mix from the web interface
  P6  Spectrum     the full colour range at saturation, very slowly
  P7  Rainbow      the whole spectrum spread around the ring at once, turning
"""

import math

from . import ephemeris as eph
from . import render

N_PROGRAMS = 8

NAMES = ("Demo", "Moon phase", "Real moon", "Colour cycle", "Night light",
         "Manual", "Spectrum", "Rainbow")

# P3 keeps white as the base and only tints it. 0.45 turned out too timid to
# read as a colour change at all from across a room, so the coloured share is
# larger now -- but the W channel still carries more than half, which is what
# keeps the disc looking like a moon rather than a lamp.
CYCLE_DEPTH = 0.62
CYCLE_PERIOD = 90.0         # seconds for one turn of the wheel

# P6 is the opposite choice: full saturation, no white base beyond a floor that
# keeps the relief readable, and slow enough that you notice it has moved
# rather than watch it moving.
SPECTRUM_PERIOD = 420.0     # seconds for one turn, seven minutes
SPECTRUM_WHITE = 0.10

# P7 drifts rather than races. At forty seconds a lap and forty LEDs, a colour
# takes about a second to hand over to its neighbour -- fast enough to see it
# moving, slow enough that nothing appears to step.
RAINBOW_PERIOD = 40.0       # seconds for one full turn of the ring

# Altitude above which the moon counts as risen. Slightly below zero, because
# refraction lifts it at the horizon and the transition should be gradual.
RISE_ALT = -2.0
FADE_ALT = 8.0          # P2 fades up to here
TWILIGHT_ALT = 12.0     # sun depression at which P2 reaches full brightness
DAY_LEVEL = 0.08        # residual level in daylight


def _clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else (hi if v > hi else v)


def _eclipse_today(cfg, d):
    """Is an eclipse listed in the configuration for today?"""
    ecl = cfg.get("eclipses") or []
    if not ecl:
        return 0.0
    y, mo, da, h, mi, _ = eph.calendar_from_jd(eph.jd_from_day_number(d))
    stamp = "%04d-%02d-%02d" % (y, mo, da)
    return 0.9 if stamp in ecl else 0.0


def phase_program(cfg, d, level, altitude_gate=False):
    """Shared core of P1 and P2."""
    p = eph.moon_phase(d)
    warmth = _eclipse_today(cfg, d)
    coolness = 0.0

    if altitude_gate:
        alt, _ = eph.moon_altitude(d, cfg["latitude"], cfg["longitude"])
        if alt <= RISE_ALT:
            return render.blank(cfg["led_count"])
        # Fade up to FADE_ALT, full brightness above it
        rise = _clamp((alt - RISE_ALT) / (FADE_ALT - RISE_ALT))
        level = level * (0.25 + 0.75 * rise)
        if not warmth:
            # A low moon is warmer and dimmer, a high one cooler. Physically
            # the same cause as the red full moon near the horizon.
            warmth = 0.55 * (1.0 - rise)
            coolness = _clamp((alt - FADE_ALT) / 40.0)

        # The moon is often up during the day but barely visible then. So the
        # lamp fades up between sunset and nautical twilight -- a residue stays
        # during the day, so that it does not look broken.
        sun_alt, _ = eph.sun_altitude(d, cfg["latitude"], cfg["longitude"])
        sky = _clamp((-sun_alt) / TWILIGHT_ALT)
        level = level * (DAY_LEVEL + (1.0 - DAY_LEVEL) * sky)

    return render.phase_frame(cfg["led_count"], p["illum"], p["waxing"], level,
                              offset=cfg["led_offset"],
                              clockwise=cfg["led_clockwise"],
                              warmth=warmth, coolness=coolness,
                              earthshine=cfg["earthshine"])


def demo(cfg, d, level, t):
    """P0: one lunation in 60 s, then briefly the special states.

    t is the program's running time in seconds.
    """
    cycle = 90.0
    u = (t % cycle) / cycle
    n = cfg["led_count"]

    if u < 0.66:
        # Lunation at high speed, including earthshine and terminator flip
        age = u / 0.66
        illum = (1.0 - math.cos(2.0 * math.pi * age)) / 2.0
        waxing = age < 0.5
        return render.phase_frame(n, illum, waxing, level,
                                  offset=cfg["led_offset"],
                                  clockwise=cfg["led_clockwise"],
                                  earthshine=cfg["earthshine"])
    if u < 0.78:
        # Moonrise: warmth and brightness climb
        k = (u - 0.66) / 0.12
        return render.phase_frame(n, 0.85, True, level * (0.2 + 0.8 * k),
                                  offset=cfg["led_offset"],
                                  clockwise=cfg["led_clockwise"],
                                  warmth=0.6 * (1.0 - k), coolness=k,
                                  earthshine=cfg["earthshine"])
    if u < 0.90:
        # Eclipse
        k = (u - 0.78) / 0.12
        return render.phase_frame(n, 1.0, True, level,
                                  offset=cfg["led_offset"],
                                  clockwise=cfg["led_clockwise"],
                                  warmth=math.sin(math.pi * k) * 0.9,
                                  earthshine=cfg["earthshine"])
    # Colour cycle
    k = (u - 0.90) / 0.10
    return colour_cycle(cfg, level, k * 30.0)


def colour_cycle(cfg, level, t, period=CYCLE_PERIOD, depth=CYCLE_DEPTH):
    """P3: full moon, tint drifting slowly, white still carrying the base."""
    hue = (t / period) % 1.0
    lin = math.pow(_clamp(level), render.GAMMA)
    r, g, b = render.wheel(hue)
    px = (int(lin * r * depth * render.FULL),
          int(lin * g * depth * render.FULL),
          int(lin * b * depth * render.FULL),
          int(lin * (1.0 - depth) * render.FULL))
    return render.solid(cfg["led_count"], px)


def spectrum(cfg, level, t):
    """P6: the whole colour wheel at full saturation, very slowly.

    The counterpart to P3. There the moon stays a moon and only takes on a
    tint; here it becomes the light source and travels the full range, which is
    what the RGBW strip can do that a white one cannot. A small white floor
    stays in so the crater relief does not disappear into flat colour.
    """
    hue = (t / SPECTRUM_PERIOD) % 1.0
    lin = math.pow(_clamp(level), render.GAMMA)
    r, g, b = render.hue_rgb(hue)
    px = (int(lin * r * (1.0 - SPECTRUM_WHITE) * render.FULL),
          int(lin * g * (1.0 - SPECTRUM_WHITE) * render.FULL),
          int(lin * b * (1.0 - SPECTRUM_WHITE) * render.FULL),
          int(lin * SPECTRUM_WHITE * render.FULL))
    return render.solid(cfg["led_count"], px)


def rainbow(cfg, level, t):
    """P7: the entire spectrum around the ring at once, slowly turning.

    Everything else here paints the ring one colour at a time. This is the one
    program that uses the ring as a ring -- and it only reads as a rainbow
    because of the dome. On a flat relief every LED would wash across the whole
    disc and the colours would sum to a muddy white; the 20 mm rise keeps each
    LED's light on its own side, so the wheel lands on the surface as a wheel.

    Hue follows the physical angle rather than the pixel index, so it turns the
    same way round whichever direction the strip was wired.
    """
    n = cfg["led_count"]
    lin = math.pow(_clamp(level), render.GAMMA)
    turn = (t / RAINBOW_PERIOD) % 1.0
    sign = -1.0 if cfg["led_clockwise"] else 1.0
    offset = cfg["led_offset"]

    frame = []
    for i in range(n):
        angle = offset + sign * 360.0 * i / n
        hue = (turn + angle / 360.0) % 1.0
        r, g, b = render.hue_rgb(hue)
        # No white at all: this is the one place where a clean moon is not the
        # point, and any white admixture only washes the colours out.
        frame.append((int(lin * r * render.FULL),
                      int(lin * g * render.FULL),
                      int(lin * b * render.FULL), 0))
    return frame


def night_light(cfg, level):
    """P4: warm residual light across the whole ring."""
    # No extra dimming here: the brightness steps already reach down to a
    # single count, and anything below that thins the ring out instead of
    # dimming it. P4 differs from a plain white ring by its warmth, not by
    # being darker than the chosen step.
    return render.solid(cfg["led_count"], render.tint(level, warmth=0.30))


def manual(cfg, level, state):
    """P5: phase in percent and an explicit RGBW mix, both from the browser.

    Colour here is not the warmth/coolness axis the moon programs use -- that
    axis exists because a real moon only ever moves along it. Manual mode is
    for everything a real moon does not do, so it addresses all four channels
    directly. Default is W alone, which is a plain white moon.
    """
    colour = (state.get("r", 0.0), state.get("g", 0.0),
              state.get("b", 0.0), state.get("w", 1.0))
    return render.phase_frame(cfg["led_count"],
                              state.get("illum", 0.5),
                              state.get("waxing", True),
                              level,
                              offset=cfg["led_offset"],
                              clockwise=cfg["led_clockwise"],
                              colour=colour,
                              earthshine=cfg["earthshine"])


def frame_for(program, cfg, d, level, t, manual_state=None, have_time=True):
    """Frame for the selected program."""
    if program == 0:
        return demo(cfg, d, level, t)
    if program == 1:
        if not have_time:
            return demo(cfg, d, level, t)
        return phase_program(cfg, d, level, altitude_gate=False)
    if program == 2:
        if not have_time:
            return demo(cfg, d, level, t)
        return phase_program(cfg, d, level, altitude_gate=True)
    if program == 3:
        return colour_cycle(cfg, level, t)
    if program == 4:
        return night_light(cfg, level)
    if program == 5:
        return manual(cfg, level, manual_state or {})
    if program == 6:
        return spectrum(cfg, level, t)
    if program == 7:
        return rainbow(cfg, level, t)
    return render.blank(cfg["led_count"])
