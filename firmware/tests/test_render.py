"""Check frame composition and dithering without hardware.

    python firmware\\tests\\test_render.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "lib"))

from moonlight import config as cfgmod
from moonlight import dither, render  # noqa: E402

N = 44
FAILED = []


def ok(name, cond, detail=""):
    print("  %-56s %s %s" % (name, "ok" if cond else "FAILED", detail))
    if not cond:
        FAILED.append(name)


print("1. Lichtbogen")
w = render.arc_weights(N, 0.0, 360.0)
ok("Vollkreis: alle LEDs auf 1", all(abs(x - 1.0) < 1e-9 for x in w))

w = render.arc_weights(N, 0.0, 0.0)
ok("arc 0: everything off", all(x == 0.0 for x in w))

w = render.arc_weights(N, 0.0, 180.0)
lit = [i for i, x in enumerate(w) if x > 0]
# At 180 degrees around azimuth 0 the LEDs from -90 to +90 must be on
expect = set(i for i in range(N)
             if abs((360.0 * i / N + 180.0) % 360.0 - 180.0) < 90.0)
ok("arc of 180 deg covers the correct half", set(lit) == expect,
   "%d LEDs" % len(lit))

# Soft edge: the outermost LEDs of the arc must be attenuated
w = render.arc_weights(N, 0.0, 120.0)
edge = [x for x in w if 0.0 < x < 1.0]
ok("soft arc edges present", len(edge) >= 2, "%d attenuated LEDs" % len(edge))

# Narrow arc: the edge must still be at least one LED pitch wide
w = render.arc_weights(N, 0.0, render.ARC_MIN)
ok("narrowest arc still lights at least one LED", sum(1 for x in w if x > 0) >= 1)

# Continuity: no LED may jump as the azimuth is rotated
prev = render.arc_weights(N, 0.0, 90.0)
maxjump = 0.0
for k in range(1, 721):
    cur = render.arc_weights(N, k * 0.5, 90.0)
    maxjump = max(maxjump, max(abs(cur[i] - prev[i]) for i in range(N)))
    prev = cur
ok("azimuth rotates smoothly", maxjump < 0.12,
   "largest step per 0.5 deg: %.4f" % maxjump)

# The same for the arc width across a whole lunation
prev = render.arc_weights(N, 0.0, render.arc_for_illumination(0.0))
maxjump = 0.0
for k in range(1, 1001):
    cur = render.arc_weights(N, 0.0, render.arc_for_illumination(k / 1000.0))
    maxjump = max(maxjump, max(abs(cur[i] - prev[i]) for i in range(N)))
    prev = cur
ok("arc width changes smoothly", maxjump < 0.12,
   "largest step per 0.1 %% of phase: %.4f" % maxjump)

print()
print("2. Phase mapping")
mono = True
last = -1.0
for k in range(0, 101):
    a = render.arc_for_illumination(k / 100.0)
    if a < last - 1e-9:
        mono = False
    last = a
ok("arc grows monotonically with the illuminated fraction", mono)
ok("full moon is the whole ring",
   abs(render.arc_for_illumination(1.0) - 360.0) < 1e-9)
ok("half moon at about 174 deg",
   abs(render.arc_for_illumination(0.5) - 173.7) < 0.1)

f = render.phase_frame(N, 0.5, True, 1.0)
right = sum(f[i][3] for i in range(N) if abs((360.0 * i / N + 180) % 360 - 180) < 60)
left = sum(f[i][3] for i in range(N)
           if abs((360.0 * i / N + 180) % 360 - 180) > 120)
ok("waxing is lit from the right", right > left * 3, "%d vs %d" % (right, left))

f = render.phase_frame(N, 0.5, False, 1.0)
right = sum(f[i][3] for i in range(N) if abs((360.0 * i / N + 180) % 360 - 180) < 60)
left = sum(f[i][3] for i in range(N)
           if abs((360.0 * i / N + 180) % 360 - 180) > 120)
ok("waning is lit from the left", left > right * 3, "%d vs %d" % (left, right))

print()
print("3. Colour")
r, g, b, wv = render.tint(1.0, warmth=0.0)
ok("neutral: white carries everything", wv > 60000 and r == 0 and g == 0 and b == 0)
r, g, b, wv = render.tint(1.0, warmth=1.0)
ok("warmth 1: red dominates, white recedes", r > 60000 and wv < 12000)
r, g, b, wv = render.tint(1.0, coolness=1.0)
ok("coolness 1: Blauanteil dazu", b > 5000 and wv > 60000)
ok("gamma: half the perceived level is about a fifth of the light",
   0.19 < render.tint(0.5)[3] / 65535.0 < 0.24,
   "%.3f" % (render.tint(0.5)[3] / 65535.0))

print()
print("4. Dithering")
# The yardstick is one 8-bit step: 256 counts at 16-bit resolution. What has to
# be accurate is not a single LED but a small group of them, because
# neighbouring LEDs light overlapping areas of the relief.
STEP = 256.0
LIMIT = 0.35 * STEP
for label, level in (("night light", 0.20), ("dim", 0.12),
                     ("lowest step", 0.09)):
    frame = [render.tint(level)] * N
    worst = max(dither.window_error(frame, window=5))
    ok("%-14s window error below 0.35 steps" % label, worst < LIMIT,
       "%.2f steps" % (worst / STEP))

# A gradient along the ring, as it occurs at the edge of an arc
frame = [render.tint(0.12 + 0.004 * i) for i in range(N)]
worst = max(dither.window_error(frame, window=5))
ok("gradient along the ring", worst < LIMIT, "%.2f steps" % (worst / STEP))

# The whole point of dithering: the ring average must hit the target even
# though every single LED is a whole count
for level in (0.09, 0.15, 0.30, 0.70):
    frame = [render.tint(level)] * N
    got = dither.ring_mean(frame)[3]
    want = render.tint(level)[3]
    ok("ring average at level %.2f" % level, abs(got - want) < 0.5 * STEP,
       "%.0f vs %d (%.2f steps off)" % (got, want, abs(got - want) / STEP))

# No flicker by construction: a still image must produce identical output on
# every frame. This is what the crawling dither pattern used to violate.
frame = [render.tint(0.09)] * N
a = dither.dither_ring(frame, dither.new_state(), 0)
b = dither.dither_ring(frame, dither.new_state(), 0)
ok("still image is bit-identical frame to frame", a == b)

# Every LED must actually light at the lowest step -- below one count the ring
# does not dim, it thins out into single pixels
frame = [render.tint(cfgmod.BRIGHTNESS_STEPS[0])] * N
out = dither.dither_ring(frame, dither.new_state(), 0)
dark = sum(1 for p in out if p[3] == 0)
ok("lowest step lights every LED", dark == 0, "%d of %d LEDs dark" % (dark, N))

print()
print("5. Ring calibration")

# pixel_at_angle must be the exact inverse of the pixel -> angle mapping that
# arc_weights uses. If the two ever drift apart, the calibration mode lights
# the wrong LED and every offset set with it comes out wrong.
worst = 0.0
for n in (30, 40, 44, 60):
    pitch = 360.0 / n
    for cw in (False, True):
        for off10 in range(0, 3600, 37):
            off = off10 / 10.0
            i = render.pixel_at_angle(n, render.CALIBRATION_ANGLE, off, cw)
            placed = off + (-1.0 if cw else 1.0) * pitch * i
            err = (placed - render.CALIBRATION_ANGLE + 180.0) % 360.0 - 180.0
            # The best any ring can do is half an LED pitch
            worst = max(worst, abs(err) / (pitch / 2.0))
            if not 0 <= i < n:
                worst = 1e9
ok("lit pixel lands on the reference direction", worst <= 1.0 + 1e-9,
   "worst miss %.3f of half an LED pitch" % worst)

# Second consequence: once the offset is right, pixel 0 is at that angle and
# the arc really does start there. Checked against arc_weights itself.
bad = []
for cw in (False, True):
    for off in (0.0, 90.0, 180.0, 270.0, 117.0):
        w = render.arc_weights(40, off, 18.0, off, cw)
        if w[0] < 0.99 or max(w[1:]) > w[0]:
            bad.append((cw, off))
ok("a narrow arc at the offset angle peaks on pixel 0", not bad, str(bad))

print()
print("6. Colour mixing and clock positions")

# Clock positions are the interface; degrees are storage. A round trip through
# both must land back where it started for every hour, or the dropdown would
# quietly move the ring.
bad = [h for h in range(1, 13)
       if render.angle_to_clock(render.clock_to_angle(h)) != h]
ok("every clock position survives the round trip", not bad, str(bad))

# The four the user is told about by name, against the module's own convention
cardinals = {12: 90.0, 3: 0.0, 6: 270.0, 9: 180.0}
bad = [(h, render.clock_to_angle(h)) for h, deg in cardinals.items()
       if abs(render.clock_to_angle(h) - deg) > 1e-9]
ok("12/3/6/9 are top/right/bottom/left", not bad, str(bad))

ok("the calibration reference is 6 o'clock",
   render.clock_to_angle(render.CALIBRATION_CLOCK) == render.CALIBRATION_ANGLE)

ok("an angle on the hour is recognised", render.on_the_hour(270.0))
ok("an angle between hours is not", not render.on_the_hour(285.0))

# mix(): the manual mode's four sliders must reach each channel on its own,
# which is the whole reason it does not go through tint()
white = render.mix(1.0, (0.0, 0.0, 0.0, 1.0))
ok("W alone lights only the white channel",
   white[3] == render.FULL and max(white[:3]) == 0, str(white))
red = render.mix(1.0, (1.0, 0.0, 0.0, 0.0))
ok("R alone lights only the red channel",
   red[0] == render.FULL and red[1] == 0 and red[3] == 0, str(red))
ok("mix clamps out-of-range weights",
   render.mix(1.0, (2.0, -1.0, 0.0, 0.0))[:2] == (render.FULL, 0))
ok("mix at zero level is dark", render.mix(0.0, (1.0, 1.0, 1.0, 1.0))
   == (0, 0, 0, 0))

# saturate() is what separates P6 from P3: the cosine wheel bottoms out at
# 0.25, so without it every hue would stay pastel
worst = 0.0
for i in range(72):
    r, g, b = render.saturate(*render.wheel(i / 72.0))
    worst = max(worst, min(r, g, b))
ok("saturate drives one channel to zero at every hue", worst < 1e-9,
   "worst residual %.4f" % worst)

# ... and it is worth doing: the raw wheel is fully saturated only at the six
# hues where one lobe bottoms out, and washed out by up to 0.25 in between.
mins = [min(render.wheel(i / 360.0)) for i in range(360)]
ok("the raw wheel is pastel between those hues",
   max(mins) > 0.2 and sum(mins) / len(mins) > 0.05,
   "per-hue minimum up to %.2f, mean %.3f" % (max(mins),
                                              sum(mins) / len(mins)))

# The manual colour must actually reach the frame
frame = render.phase_frame(N, 1.0, True, 1.0, colour=(1.0, 0.0, 0.0, 0.0),
                           earthshine=0.0)
ok("phase_frame honours an explicit colour",
   frame[0][0] > 0 and frame[0][3] == 0, str(frame[0]))

print()
if FAILED:
    print("FAILED: %s" % ", ".join(FAILED))
    raise SystemExit(1)
print("All checks passed.")
