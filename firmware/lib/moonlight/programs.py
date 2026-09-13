"""The lamp's programs.

Each program is handed the current moment and returns a 16-bit frame. Pure
Python, so every program can be computed and rendered on a PC.

  P0  Demo         every state at high speed, one lunation per minute
  P1  Moon phase   live phase, always visible, needs no location
  P2  Real moon    like P1, but only while the moon is actually up;
                   brightness and colour follow its altitude
  P3  Colour cycle  full moon with a slowly drifting hue
  P4  Night light  dimmest possible warm white across the whole ring
  P5  Manual       azimuth, arc and colour come from the web interface
"""

import math

from . import ephemeris as eph
from . import render

N_PROGRAMS = 6

NAMES = ("Demo", "Moon phase", "Real moon", "Colour cycle", "Night light",
         "Manual")

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


def colour_cycle(cfg, level, t):
    """P3: full moon, hue drifting slowly."""
    hue = (t / 60.0) % 1.0
    # A colour wheel that keeps the W channel as the base level: the moon stays
    # a moon instead of turning into a disco ball.
    lin = math.pow(_clamp(level), render.GAMMA)
    a = 2.0 * math.pi * hue
    r = 0.5 + 0.5 * math.cos(a)
    g = 0.5 + 0.5 * math.cos(a - 2.0944)
    b = 0.5 + 0.5 * math.cos(a - 4.1888)
    depth = 0.45
    px = (int(lin * r * depth * render.FULL),
          int(lin * g * depth * render.FULL),
          int(lin * b * depth * render.FULL),
          int(lin * (1.0 - depth) * render.FULL))
    return render.solid(cfg["led_count"], px)


def night_light(cfg, level):
    """P4: warm residual light across the whole ring."""
    # No extra dimming here: the brightness steps already reach down to a
    # single count, and anything below that thins the ring out instead of
    # dimming it. P4 differs from a plain white ring by its warmth, not by
    # being darker than the chosen step.
    return render.solid(cfg["led_count"], render.tint(level, warmth=0.30))


def manual(cfg, level, state):
    """P5: values come from the web interface."""
    return render.phase_frame(cfg["led_count"],
                              state.get("illum", 0.5),
                              state.get("waxing", True),
                              level,
                              offset=cfg["led_offset"],
                              clockwise=cfg["led_clockwise"],
                              warmth=state.get("warmth", 0.0),
                              coolness=state.get("coolness", 0.0),
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
    return render.blank(cfg["led_count"])
