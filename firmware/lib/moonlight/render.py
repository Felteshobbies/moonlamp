"""Turning phase figures into a ring image.

Pure Python, runs under CPython and MicroPython. Produces linear 16-bit values
per channel; rounding down to the SK6812's 8 bits is `dither.py`'s job.

Two things in here come from the optical simulation of the lamp:

* ARC_TABLE maps the apparent illuminated fraction to the arc width needed.
  The relationship is anything but obvious and was measured with
  `tests/calibrate_arc.py` on the height field of the real relief.
* Real crescents are possible. For any single azimuth the shadow boundary does
  sit at the summit, i.e. across the middle of the disc -- but because of the
  1/d^2 falloff the near side is far from evenly lit. A narrow arc lights only
  a wedge at the rim, and that reads as a crescent. Measured: an 8 degree arc
  gives 9 % apparent illumination.
"""

import math

# Illuminated fraction -> arc width in degrees. Sample points from the
# simulation on the real relief (H = 20 mm conical, LED z = 16 mm, 44 LEDs),
# linearly interpolated in between. Regenerate with tests/calibrate_arc.py.
ARC_TABLE = (
    (0.10, 15.3),
    (0.15, 42.7),
    (0.20, 61.0),
    (0.25, 77.9),
    (0.30, 96.4),
    (0.35, 115.4),
    (0.40, 133.6),
    (0.45, 153.1),
    (0.50, 173.7),
    (0.55, 193.7),
    (0.60, 212.4),
    (0.65, 231.8),
    (0.70, 253.0),
    (0.75, 272.5),
    (0.80, 290.6),
    (0.85, 312.9),
    (0.90, 336.0),
    (0.95, 358.9),
    (1.00, 360.0),
)

ARC_MIN = ARC_TABLE[0][1]
ILLUM_MIN = ARC_TABLE[0][0]

# Softness of the arc edges, as a fraction of the half arc width
EDGE_SOFTNESS = 0.15

# Earthshine: fraction of the base level on the averted side,
# measured in linear light (see linear_to_level)
EARTHSHINE = 0.018

GAMMA = 2.2
FULL = 65535


def arc_for_illumination(illum):
    """Arc width in degrees that produces this illuminated fraction."""
    if illum <= ARC_TABLE[0][0]:
        return ARC_MIN
    if illum >= 1.0:
        return 360.0
    for i in range(len(ARC_TABLE) - 1):
        x0, y0 = ARC_TABLE[i]
        x1, y1 = ARC_TABLE[i + 1]
        if x0 <= illum <= x1:
            t = (illum - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return 360.0


def arc_weights(n_leds, azimuth, arc, offset=0.0, clockwise=False,
                softness=EDGE_SOFTNESS):
    """Weight 0..1 per LED for one arc of light.

    azimuth    direction of the arc centre in degrees, 0 = right, 90 = up
    arc        arc width in degrees, 360 = the whole ring
    offset     physical angle of pixel 0, from the calibration
    clockwise  True if pixel numbers run clockwise
    """
    out = [0.0] * n_leds
    if arc <= 0.0:
        return out
    if arc >= 360.0:
        return [1.0] * n_leds

    half = arc / 2.0
    # The soft edge has to be at least one LED pitch wide, otherwise it falls
    # between the pixels on narrow arcs and the arc jumps in whole LEDs as it
    # moves. On very narrow arcs this turns into a triangle -- deliberately, so
    # that the azimuth can be shifted smoothly as well.
    edge = half * softness
    pitch = 360.0 / n_leds
    if edge < pitch:
        edge = pitch
    if edge > half:
        edge = half
    # Transition into the closed ring: without this there would be a jump of a
    # whole LED between "almost full" and "full", visible just before full moon.
    close = 0.0
    if arc > 360.0 - 2.0 * edge:
        close = (arc - (360.0 - 2.0 * edge)) / (2.0 * edge)

    sign = -1.0 if clockwise else 1.0
    for i in range(n_leds):
        a = offset + sign * 360.0 * i / n_leds
        delta = (a - azimuth + 180.0) % 360.0 - 180.0
        if delta < 0:
            delta = -delta
        if delta >= half:
            w = 0.0
        else:
            w = (half - delta) / edge
            if w > 1.0:
                w = 1.0
        if close > 0.0:
            w = w + (1.0 - w) * close
        out[i] = w
    return out


# Reference direction for the calibration mode: the bottom of the ring, where
# the cable leaves through the channel. Any fixed direction would do; the point
# is that the user can identify it by eye without counting LEDs.
CALIBRATION_ANGLE = 270.0


def pixel_at_angle(n_leds, angle, offset=0.0, clockwise=False):
    """Index of the LED sitting closest to `angle` -- the inverse of the
    mapping in arc_weights, where pixel i sits at offset +/- i * 360/n.

    The calibration mode lights the pixel the configuration believes is at
    CALIBRATION_ANGLE. Nudging the offset until the lit LED really is down
    there is what makes the offset correct, and it needs no knowledge of which
    physical LED is number 0 -- which is the normal situation once the strip is
    glued into the frame.
    """
    if n_leds < 1:
        return 0
    pitch = 360.0 / n_leds
    delta = (offset - angle) if clockwise else (angle - offset)
    return int(round((delta % 360.0) / pitch)) % n_leds


def linear_to_level(fraction):
    """Convert a fraction of *linear* light into a perceptual level factor.

    Constants such as earthshine are physically fractions of the emitted light,
    not of the perceived value. Multiplying them into `level` before tint()
    applies gamma would square the effect: 1.8 % perceived becomes 0.015 %
    linear, which 8-bit LEDs cannot show at all.
    """
    if fraction <= 0.0:
        return 0.0
    return math.pow(fraction, 1.0 / GAMMA)


def _linear(level):
    """Convert perceived brightness 0..1 into linear light."""
    if level <= 0.0:
        return 0.0
    if level >= 1.0:
        return 1.0
    return math.pow(level, GAMMA)


def tint(level, warmth=0.0, coolness=0.0):
    """Split a tinted white into linear RGBW components.

    warmth    0 = neutral, 1 = deep red (eclipse, near the horizon)
    coolness  lifts a slight blue component (moon high in the sky)

    The W channel carries the base brightness, RGB only the tint. That is the
    reason for the RGBW strip: white mixed from RGB would look dirty on grey
    relief and draw roughly three times the current.
    """
    lin = _linear(level)
    if lin <= 0.0:
        return (0, 0, 0, 0)

    w = lin * (1.0 - 0.85 * warmth)
    r = lin * warmth
    g = lin * warmth * 0.22
    b = lin * (coolness * 0.16 + warmth * 0.02)

    return (int(r * FULL), int(g * FULL), int(b * FULL), int(w * FULL))


def scale(rgbw, factor):
    return (int(rgbw[0] * factor), int(rgbw[1] * factor),
            int(rgbw[2] * factor), int(rgbw[3] * factor))


def add(a, b):
    return (min(FULL, a[0] + b[0]), min(FULL, a[1] + b[1]),
            min(FULL, a[2] + b[2]), min(FULL, a[3] + b[3]))


def phase_frame(n_leds, illum, waxing, level, offset=0.0, clockwise=False,
                warmth=0.0, coolness=0.0, earthshine=EARTHSHINE):
    """Complete ring image for one moon phase.

    illum   0..1 illuminated fraction
    waxing  True = waxing, lit from the right
    level   perceived brightness 0..1 of the lit side

    Returns a list of (r, g, b, w) with 0..65535, linear.
    """
    azimuth = 0.0 if waxing else 180.0

    arc = arc_for_illumination(illum)
    bright = level
    if illum < ILLUM_MIN:
        # Nothing narrower than the narrowest arc is available; the last few
        # percent down to new moon are faded out via brightness.
        bright = level * max(0.0, illum) / ILLUM_MIN

    lit = tint(bright, warmth, coolness)
    weights = arc_weights(n_leds, azimuth, arc, offset, clockwise)

    frame = []
    if earthshine > 0.0 and illum < 0.98:
        # Earthshine: the geometrically black side is lifted very faintly and
        # coolly by the opposite LEDs. A real phenomenon, and the one thing the
        # dome geometry cannot do by itself.
        eshine = tint(level * linear_to_level(earthshine), 0.0, 1.0)
        # Below roughly half a count the dither can no longer produce a glow,
        # only scattered lit pixels. A dark side that is genuinely dark looks
        # better than one speckled with dots, so drop it instead.
        if eshine[3] < 128:
            eshine = (0, 0, 0, 0)
        # The unlit side is exactly the complementary phase: whatever is
        # missing from 1 - illum is carried by earthshine. Hence the same
        # table, just with the complement and turned by 180 degrees.
        back = arc_weights(n_leds, (azimuth + 180.0) % 360.0,
                           arc_for_illumination(1.0 - illum),
                           offset, clockwise)
    else:
        eshine = (0, 0, 0, 0)
        back = [0.0] * n_leds

    for i in range(n_leds):
        px = scale(lit, weights[i])
        if back[i] > 0.0:
            px = add(px, scale(eshine, back[i]))
        frame.append(px)
    return frame


def solid(n_leds, rgbw):
    return [rgbw] * n_leds


def blank(n_leds):
    return [(0, 0, 0, 0)] * n_leds
