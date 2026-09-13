"""Check the ephemeris against known astronomical quantities.

Runs on a PC under CPython, no Pico needed:
    python firmware\\tests\\test_ephemeris.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "lib"))

from moonlight import ephemeris as eph  # noqa: E402

FAILED = []


def check(name, value, expected, tol, unit=""):
    ok = abs(value - expected) <= tol
    print("  %-46s %10.4f %-4s (expected %.4f +/- %.4f) %s"
          % (name, value, unit, expected, tol, "ok" if ok else "FAILED"))
    if not ok:
        FAILED.append(name)


def check_range(name, lo, hi, exp_lo, exp_hi, tol, unit="", prec=0):
    ok = abs(lo - exp_lo) <= tol and abs(hi - exp_hi) <= tol
    fmt = ("  %%-46s %%9.%df..%%-9.%df %%-4s (expected %%.%df..%%.%df) %%s"
           % (prec, prec, prec, prec))
    print(fmt % (name, lo, hi, unit, exp_lo, exp_hi, "ok" if ok else "FAILED"))
    if not ok:
        FAILED.append(name)


print("1. Calendar arithmetic")
# J2000.0 is by definition 2000-01-01 12:00 UT = JD 2451545.0
check("JD of 2000-01-01 12:00 UT", eph.julian_day(2000, 1, 1, 12), 2451545.0,
      1e-6, "d")
# Converting back must give the same date
for probe in ((2026, 8, 24, 21, 30, 0), (1999, 12, 31, 0, 0, 0), (2038, 2, 28, 6, 5, 9)):
    jd = eph.julian_day(*probe)
    back = eph.calendar_from_jd(jd)
    ok = back == probe
    print("  %-46s %s %s" % ("round trip %s" % (probe,), back,
                             "ok" if ok else "FAILED"))
    if not ok:
        FAILED.append("calendar roundtrip %s" % (probe,))

print()
print("2. Sun: equinoxes and solstices")
# At the March equinox the sun's ecliptic longitude is 0 degrees, at the
# September equinox 180. The dates are known from the calendar.
for label, date, expect in (("March equinox 2026-03-20 14:46 UT",
                             (2026, 3, 20, 14, 46), 0.0),
                            ("September equinox 2026-09-23 00:05 UT",
                             (2026, 9, 23, 0, 5), 180.0),
                            ("June solstice 2026-06-21 08:24 UT",
                             (2026, 6, 21, 8, 24), 90.0),
                            ("December solstice 2026-12-21 20:50 UT",
                             (2026, 12, 21, 20, 50), 270.0)):
    lon = eph.sun_ecliptic(eph.day_number(*date))[0]
    err = (lon - expect + 180.0) % 360.0 - 180.0
    ok = abs(err) < 0.05
    print("  %-46s longitude %8.3f deg, error %+6.3f  %s"
          % (label, lon, err, "ok" if ok else "FAILED"))
    if not ok:
        FAILED.append(label)

print()
print("3. Moon: orbital quantities over 20 years")
d0 = eph.day_number(2020, 1, 1)
n = 20 * 365
dist = []
lons = []
for k in range(n):
    d = d0 + k
    p = eph.moon_phase(d)
    dist.append(p["dist_km"])
    lons.append(eph.moon_ecliptic(d)[0])
check_range("distance perigee..apogee", min(dist), max(dist),
            356500, 406700, 3000, "km")

# Mean sidereal motion: 360 degrees in 27.32166 days
adv = 0.0
for k in range(1, n):
    adv += (lons[k] - lons[k - 1] + 180.0) % 360.0 - 180.0
check("mean motion in longitude", adv / (n - 1), 360.0 / 27.321661, 0.002,
      "deg/d")

print()
print("4. Synodic month and long-term drift")
# The mean over a few lunations is not a useful measure: new moon instants
# really do swing about +/- 0.45 d around the uniform mean, so the first and
# last entry of a short series dominate the result. Only the regression
# slope over many lunations is meaningful.
d = eph.day_number(2000, 1, 1)
news = []
while len(news) < 500:
    d = eph.next_phase(d, 0.0)
    if d is None:
        break
    news.append(d)
    d += 1.0

gaps = [news[k + 1] - news[k] for k in range(len(news) - 1)]
check_range("spread of individual lunations", min(gaps), max(gaps),
            29.27, 29.83, 0.10, "d", prec=3)

nn = len(news)
xs = list(range(nn))
ys = [news[k] - (news[0] + k * eph.SYNODIC) for k in xs]
mx = sum(xs) / nn
my = sum(ys) / nn
slope = (sum((xs[i] - mx) * (ys[i] - my) for i in xs)
         / sum((x - mx) ** 2 for x in xs))
scatter = (sum((ys[i] - (my + slope * (xs[i] - mx))) ** 2 for i in xs) / nn) ** 0.5
check("drift over %.0f years, d per lunation" % (nn * 29.53 / 365.25),
      slope, 0.0, 0.0005, "d")
check("physical spread of new moon instants", scatter, 0.32, 0.06, "d")

print()
print("5. Illuminated fraction at the quarter points")
d = eph.day_number(2026, 1, 1)
for label, target, expect, tol in (("new moon", 0.0, 0.0, 0.005),
                                   ("first quarter", 0.25, 0.5, 0.02),
                                   ("full moon", 0.5, 1.0, 0.005),
                                   ("last quarter", 0.75, 0.5, 0.02)):
    t = eph.next_phase(d, target)
    p = eph.moon_phase(t)
    y, mo, da, h, mi, _ = eph.calendar_from_jd(eph.jd_from_day_number(t))
    ok = abs(p["illum"] - expect) <= tol
    print("  %-22s %04d-%02d-%02d %02d:%02d UT   illum %.4f (expected %.2f)  %s"
          % (label, y, mo, da, h, mi, p["illum"], expect,
             "ok" if ok else "FAILED"))
    if not ok:
        FAILED.append(label)

print()
print("6. Full moon culminates at midnight (opposite the sun)")
# At full moon the moon is opposite the sun, so it rises at sunset and
# culminates near true local midnight.
lat, lon = 51.2, 6.8          # Duesseldorf, example location
d_full = eph.next_phase(eph.day_number(2026, 6, 1), 0.5)
best_alt, best_t = -99.0, 0.0
for k in range(0, 24 * 60, 2):
    t = math.floor(d_full) + k / (24.0 * 60.0)
    alt, _ = eph.moon_altitude(t, lat, lon)
    if alt > best_alt:
        best_alt, best_t = alt, t
hour_ut = (best_t - math.floor(best_t)) * 24.0
solar_midnight = 24.0 - lon / 15.0 if lon > 0 else -lon / 15.0
offset = (hour_ut - (24.0 - lon / 15.0) + 12.0) % 24.0 - 12.0
ok = abs(offset) < 1.0
print("  culmination %5.2f h UT, true local midnight %5.2f h UT, "
      "error %+.2f h  %s" % (hour_ut, 24.0 - lon / 15.0, offset,
                                  "ok" if ok else "FAILED"))
if not ok:
    FAILED.append("full moon culmination")

print()
print("7. Sun altitude: noon altitude at the solstice")
# On 21 June the noon sun stands 90 - latitude + 23.44 degrees high.
d_sol = eph.day_number(2026, 6, 21, 12 - int(lon / 15.0))
best = -99.0
for k in range(0, 24 * 60, 2):
    t = math.floor(d_sol) + k / (24.0 * 60.0)
    alt, _ = eph.sun_altitude(t, lat, lon)
    best = max(best, alt)
check("noon altitude on 21 June at 51.2 deg north", best, 90.0 - lat + 23.44,
      0.3, "deg")

print()
if FAILED:
    print("FAILED: %d checks -> %s" % (len(FAILED), ", ".join(FAILED)))
    raise SystemExit(1)
print("All checks passed.")
