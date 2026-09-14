"""Check time zone, configuration and the programs without hardware.

    python firmware\\tests\\test_system.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "lib"))

from moonlight import config as cfgmod       # noqa: E402
from moonlight import ephemeris as eph       # noqa: E402
from moonlight import programs               # noqa: E402
from moonlight import timeutil as tu         # noqa: E402

FAILED = []


def ok(name, cond, detail=""):
    print("  %-52s %s %s" % (name, "ok" if cond else "FAILED", detail))
    if not cond:
        FAILED.append(name)


print("1. Daylight saving time, EU rule")
ok("2026-03-29 00:30 UTC is still standard time", not tu.is_eu_dst(2026, 3, 29, 0))
ok("2026-03-29 01:30 UTC schon Sommerzeit", tu.is_eu_dst(2026, 3, 29, 1))
ok("2026-10-25 00:30 UTC is still summer time", tu.is_eu_dst(2026, 10, 25, 0))
ok("2026-10-25 01:30 UTC wieder Winterzeit", not tu.is_eu_dst(2026, 10, 25, 1))
ok("mid July is summer time", tu.is_eu_dst(2026, 7, 15, 12))
ok("mid January is standard time", not tu.is_eu_dst(2026, 1, 15, 12))
ok("last Sunday in March 2026 is the 29th", tu._last_sunday(2026, 3) == 29)
ok("last Sunday in October 2026 is the 25th", tu._last_sunday(2026, 10) == 25)
ok("leap year: last Sunday in February 2024 is the 25th",
   tu._last_sunday(2024, 2) == 25)

print()
print("2. Configuration")
broken = dict(cfgmod.DEFAULTS, latitude=999, led_count=-5, program="x",
              hostname=None, eclipses="nein")
c = cfgmod.validate(broken)
ok("nonsense values get clamped instead of blocking",
   c["latitude"] == 90 and c["led_count"] == 1
   and c["program"] == cfgmod.DEFAULTS["program"]
   and isinstance(c["hostname"], str) and c["eclipses"] == [])
ok("brightness steps increase monotonically",
   all(cfgmod.BRIGHTNESS_STEPS[i] < cfgmod.BRIGHTNESS_STEPS[i + 1]
       for i in range(len(cfgmod.BRIGHTNESS_STEPS) - 1)))
# One count out of 255 is the dimmest level at which every LED still lights.
# Anything below is not dimmer, only patchier.
floor = (1.0 / 255.0) ** (1.0 / 2.2)
ok("lowest step is at the 8-bit floor, not below",
   floor * 0.9 <= cfgmod.BRIGHTNESS_STEPS[0] <= floor * 1.6,
   "%.3f, floor %.3f" % (cfgmod.BRIGHTNESS_STEPS[0], floor))

print()
print("3. Programs return valid frames")
cfg = cfgmod.validate(dict(cfgmod.DEFAULTS))
d = eph.day_number(2026, 8, 24, 21, 0)
for p in range(programs.N_PROGRAMS):
    f = programs.frame_for(p, cfg, d, 0.3, 12.0,
                           {"illum": 0.4, "waxing": True})
    good = (len(f) == cfg["led_count"]
            and all(len(px) == 4 and all(0 <= v <= 65535 for v in px) for px in f))
    ok("P%d %-14s" % (p, programs.NAMES[p]), good,
       "%d LEDs lit" % sum(1 for px in f if max(px) > 0))

print()
print("4. P2 follows the real moon")
lat, lon = 51.2, 6.8
cfg2 = dict(cfg, latitude=lat, longitude=lon)
# Over 30 days in hourly steps: the lamp may only be lit while the moon is
# genuinely above the horizon.
d0 = eph.day_number(2026, 9, 1)
wrong_on = wrong_off = lit = dark = 0
for k in range(30 * 24):
    dd = d0 + k / 24.0
    alt, _ = eph.moon_altitude(dd, lat, lon)
    f = programs.frame_for(2, cfg2, dd, 1.0, 0.0)
    on = any(max(px) > 0 for px in f)
    if on:
        lit += 1
        if alt <= programs.RISE_ALT:
            wrong_on += 1
    else:
        dark += 1
        # Being off is only allowed when the moon is down, or when daylight
        # and new moon leave nothing that 8 bits could represent -- in which
        # case there would be nothing to see in reality either.
        if alt > programs.RISE_ALT + 2.0:
            sun_alt, _ = eph.sun_altitude(dd, lat, lon)
            night = sun_alt < 0.0
            if night or eph.moon_phase(dd)["illum"] > 0.03:
                wrong_off += 1
ok("never on while the moon is below the horizon", wrong_on == 0,
   "%d of %d hours lit" % (lit, lit + dark))
ok("never off while something would really be visible", wrong_off == 0)
ok("share of visible hours is plausible", 0.35 < lit / (lit + dark) < 0.65,
   "%.0f %%" % (100.0 * lit / (lit + dark)))

# Clearly dimmed during the day, full at night
def level_at(day, hour):
    dd = eph.day_number(2026, 9, day, hour)
    alt, _ = eph.moon_altitude(dd, lat, lon)
    if alt <= programs.RISE_ALT:
        return None
    f = programs.frame_for(2, cfg2, dd, 1.0, 0.0)
    return max(max(px) for px in f)


day_vals = [v for h in range(9, 16) for d_ in range(1, 29)
            for v in (level_at(d_, h),) if v]
night_vals = [v for h in (23, 0, 1, 2) for d_ in range(1, 29)
              for v in (level_at(d_, h),) if v]
ok("strongly dimmed by day compared with night",
   max(day_vals) < max(night_vals) * 0.35,
   "day max %d, night max %d" % (max(day_vals), max(night_vals)))

print()
print("5. P1 needs no location")
cfg3 = dict(cfg)
cfg3.pop("latitude", None)
cfg3.pop("longitude", None)
try:
    f = programs.frame_for(1, cfg3, d, 0.3, 0.0)
    ok("P1 runs without location data", any(max(px) > 0 for px in f))
except KeyError as exc:
    ok("P1 runs without location data", False, "KeyError %s" % exc)

print()
print("6. SK6812 bit timing")
# Impossible to see without a scope, easy to break, and the failure mode is
# nasty: a marginal pulse makes the strip latch mid-frame, and the rest of the
# picture lands on the first LEDs.
from moonlight import leds  # noqa: E402

cyc = 1.0e6 / leds.PIO_FREQ
timing = {
    "T0H": leds.T_HIGH * cyc,
    "T0L": (leds.T_LOW + leds.T_EXTRA) * cyc,
    "T1H": (leds.T_HIGH + leds.T_EXTRA) * cyc,
    "T1L": leds.T_LOW * cyc,
}
SPEC = {"T0H": 0.30, "T0L": 0.90, "T1H": 0.60, "T1L": 0.60}
TOL = 0.15
for key in ("T0H", "T0L", "T1H", "T1L"):
    got, want = timing[key], SPEC[key]
    ok("%s within %.2f +/- %.2f us" % (key, want, TOL),
       abs(got - want) <= TOL, "%.3f us" % got)

period = (leds.T_LOW + leds.T_HIGH + leds.T_EXTRA) * cyc
ok("bit period is 1.20 us", abs(period - 1.20) < 0.01, "%.3f us" % period)

# The PIO body cannot see module-level names, so the delays are written there
# as literals. Parse them out and make sure they still match the constants the
# timing above is computed from.
import ast as _ast  # noqa: E402

_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                         "lib", "moonlight", "leds.py"), encoding="utf-8").read()
_lit = {}
for _node in _ast.walk(_ast.parse(_src)):
    if isinstance(_node, _ast.FunctionDef) and _node.name == "_sk6812":
        for _st in _node.body:
            if (isinstance(_st, _ast.Assign)
                    and isinstance(_st.targets[0], _ast.Name)
                    and isinstance(_st.value, _ast.Constant)):
                _lit[_st.targets[0].id] = _st.value.value
ok("PIO literals match the timing constants",
   (_lit.get("T1"), _lit.get("T2"), _lit.get("T3"))
   == (leds.T_HIGH, leds.T_EXTRA, leds.T_LOW),
   "PIO %s, constants %s" % ((_lit.get("T1"), _lit.get("T2"), _lit.get("T3")),
                             (leds.T_HIGH, leds.T_EXTRA, leds.T_LOW)))

# The FIFO has to bridge longer than the strip's latch time, or an interrupted
# transfer restarts the frame at LED 0
word_us = period * 32
FIFO_WORDS = 8                  # doubled by fifo_join=JOIN_TX
ok("joined TX FIFO bridges more than the 80 us latch time",
   FIFO_WORDS * word_us > 80.0,
   "%.0f us of buffer, latch at 80 us" % (FIFO_WORDS * word_us))

print()
print("7. The two colour programs stay different from each other")

from moonlight import render                  # noqa: E402
from moonlight import web as webmod           # noqa: E402

# Forgetting the description when adding a program leaves a blank card on the
# page, which nothing else would catch
ok("every program has a name", len(programs.NAMES) == programs.N_PROGRAMS,
   "%d names, %d programs" % (len(programs.NAMES), programs.N_PROGRAMS))
ok("every program has a description",
   len(webmod.DESCRIPTIONS) == programs.N_PROGRAMS,
   "%d descriptions" % len(webmod.DESCRIPTIONS))
ok("the program range in config covers them all",
   cfgmod._RANGES["program"] == (0, programs.N_PROGRAMS - 1),
   str(cfgmod._RANGES["program"]))

# P6 must reach full saturation at every point of its cycle -- that is the one
# thing it does that P3 does not
worst, w3_min, w6_max = 0, 65536, 0
for i in range(24):
    t = i * programs.SPECTRUM_PERIOD / 24.0
    px6 = programs.spectrum(cfg, 1.0, t)[0]
    px3 = programs.colour_cycle(cfg, 1.0, i * programs.CYCLE_PERIOD / 24.0)[0]
    worst = max(worst, min(px6[:3]))
    w3_min = min(w3_min, px3[3])
    w6_max = max(w6_max, px6[3])
ok("P6 is fully saturated throughout", worst <= 1,
   "largest residual on the darkest channel: %d of 65535" % worst)
ok("P3 keeps more white than P6 ever does", w3_min > w6_max,
   "P3 never below %d, P6 never above %d" % (w3_min, w6_max))

# Regression guard on the complaint that P3 was too subtle to read as a colour
# change at all. Chroma here is the spread across RGB at the strongest hue.
samples = [programs.colour_cycle(cfg, 1.0,
                                  i * programs.CYCLE_PERIOD / 180.0)[0]
           for i in range(180)]
chroma = max(max(px[:3]) - min(px[:3]) for px in samples) / 65535.0
# The wheel's own widest spread is 0.866, not 1.0 -- three cosines 120 degrees
# apart are furthest apart halfway between two lobes -- so chroma tops out at
# CYCLE_DEPTH * 0.866. The old depth of 0.45 gave 0.39; anything above 0.50
# means the bump is still in.
ok("P3 has visible colour, not a hint of one", chroma > 0.50,
   "chroma %.2f, was 0.39 at the old depth" % chroma)

# Manual mode must pass its mix through untouched
frame = programs.manual(cfg, 1.0, {"illum": 1.0, "waxing": True,
                                   "r": 1.0, "g": 0.0, "b": 0.0, "w": 0.0})
ok("P5 puts the slider colour on the ring",
   frame[0][0] > 60000 and frame[0][3] == 0, str(frame[0]))
frame = programs.manual(cfg, 1.0, {"illum": 1.0, "waxing": True})
ok("P5 defaults to a plain white moon",
   frame[0][3] > 60000 and max(frame[0][:3]) == 0, str(frame[0]))

print()
print("8. Rainbow spreads the spectrum around the ring")

cfg8 = dict(cfg)
cfg8["led_count"] = 40

# The point of P7 is that the LEDs differ from each other. Every other program
# paints the ring one colour at a time, so this is the one thing to verify.
frame = programs.rainbow(cfg8, 1.0, 0.0)
distinct = len(set(frame))
ok("every LED carries its own colour", distinct >= 30,
   "%d distinct colours across %d LEDs" % (distinct, len(frame)))

ok("no white is mixed in", all(px[3] == 0 for px in frame))
ok("every LED is fully saturated", all(min(px[:3]) <= 1 for px in frame),
   "worst %d" % max(min(px[:3]) for px in frame))

# The seamless part: no LED may be brighter than its neighbours just because of
# its hue, or the ring shows bands and pulses as it turns
powers = [sum(px[:3]) for px in frame]
spread = (max(powers) - min(powers)) / float(max(powers))
ok("every LED carries the same total power", spread < 0.01,
   "%.1f %% variation around the ring" % (100 * spread))

# Neighbours must be close, or it is confetti rather than a rainbow
worst = max(max(abs(a - b) for a, b in zip(frame[i], frame[(i + 1) % 40]))
            for i in range(40))
ok("neighbouring LEDs are close in colour", worst < 0.25 * render.FULL,
   "largest neighbour step %d of %d" % (worst, render.FULL))

# One full turn must come back to where it started, or it would jump each lap
a = programs.rainbow(cfg8, 1.0, 0.0)
b = programs.rainbow(cfg8, 1.0, programs.RAINBOW_PERIOD)
ok("a full turn closes seamlessly", a == b)

# Smoothness in time. The animation is driven by whatever main.py passes as
# `t`, so it can only be as smooth as that clock is fine-grained.
tiny = programs.RAINBOW_PERIOD / 240.0        # a quarter of a frame at 60 fps
near = programs.rainbow(cfg8, 1.0, tiny)
step = max(max(abs(x - y) for x, y in zip(p1, p2))
           for p1, p2 in zip(a, near))
ok("a small step in time makes a small change in colour",
   step < 0.05 * render.FULL,
   "%d counts of %d for %.2f s" % (step, render.FULL, tiny))

# And the trap that caused it: MicroPython's time.time() returns whole seconds,
# so deriving `t` from it advanced every animation in one-second jumps. On the
# rainbow that was several LED positions at a time. main.py must therefore
# accumulate from ticks_ms(), and this is the guard on that.
main_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             os.pardir, "main.py"), encoding="utf-8").read()
call = "programs.frame_for("
idx = main_src.index(call)
args = main_src[idx:idx + 260]
ok("main.py does not time the programs with time.time()",
   "time.time()" not in args, args.split(chr(10))[1].strip())
ok("main.py accumulates programme time in milliseconds",
   "prog_time += ticks_diff(" in main_src)

leap = programs.rainbow(cfg8, 1.0, 1.0)
moved = sum(1 for p1, p2 in zip(a, leap) if p1 != p2)
ok("one whole second would have moved most of the ring", moved > 30,
   "%d of %d LEDs change in a one-second jump" % (moved, len(a)))

# Turning must actually move the pattern along the ring
half = programs.rainbow(cfg8, 1.0, programs.RAINBOW_PERIOD / 2.0)
ok("the pattern travels as time passes", half != a)

# Hue follows the physical angle, so the wheel turns the same way round
# whichever direction the strip happens to be wired
# Pixel i sits at offset + i*pitch counter-clockwise and offset - i*pitch
# clockwise, so reversing the wiring must mirror the pattern in index space
# while leaving it identical in physical space.
cw = programs.rainbow(dict(cfg8, led_clockwise=True), 1.0, 0.0)
n = len(a)
# Compared with a tolerance of one count: the two paths reach the same hue by
# different arithmetic -- one adds a turn, the other subtracts it -- so the last
# bit can differ before the cast to 16 bits.
worst = max(max(abs(x - y) for x, y in zip(cw[i], a[(n - i) % n]))
            for i in range(n))
ok("reversed wiring mirrors the indices, not the physical colours",
   worst <= 1, "largest difference %d of %d counts" % (worst, render.FULL))

print()
print("9. Manual mode reaches every channel on its own")

for name, mix, want in (("red", (1.0, 0, 0, 0), 0),
                        ("green", (0, 1.0, 0, 0), 1),
                        ("blue", (0, 0, 1.0, 0), 2),
                        ("white", (0, 0, 0, 1.0), 3)):
    st = {"illum": 1.0, "waxing": True,
          "r": mix[0], "g": mix[1], "b": mix[2], "w": mix[3]}
    px = programs.manual(cfg8, 1.0, st)[0]
    others = [v for i, v in enumerate(px) if i != want]
    ok("%s alone lights only its own channel" % name,
       px[want] > 60000 and max(others) == 0, str(px))

# The complaint this came from: with White at 100 the colour sliders look dead,
# because the white die is about as bright as the other three together. The
# presets exist to make colour reachable in one click, so they must actually
# turn white off.
from moonlight import web as webmod                     # noqa: E402
coloured = [(name, mix) for name, mix in webmod.MANUAL_PRESETS
            if name != "White"]
ok("every colour preset pulls White down",
   all(mix[3] < 50 for _, mix in coloured),
   ", ".join("%s W=%d" % (n, m[3]) for n, m in coloured))
ok("there is still a preset for a plain white moon",
   ("White", (0, 0, 0, 100)) in webmod.MANUAL_PRESETS)

print()
if FAILED:
    print("FAILED: %s" % ", ".join(FAILED))
    raise SystemExit(1)
print("All checks passed.")
