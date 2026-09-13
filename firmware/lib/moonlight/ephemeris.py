"""Sun and moon positions without third-party libraries.

Runs unchanged under CPython and MicroPython: only `math`, no classes from
`datetime`, no f-strings, no `typing`.

Method after Paul Schlyter ("How to compute planetary positions"): a Kepler
orbit plus the largest perturbation terms. Accuracy is roughly 2 arcminutes in
lunar longitude and about 0.1 days in the phase instants -- two orders of
magnitude more than a wall lamp needs.

All functions below work with `d`, the days since 1999-12-31 00:00 UT.
`day_number()` computes it from a UTC timestamp.
"""

import math

DEG = math.pi / 180.0
RAD = 180.0 / math.pi

# Mean synodic period, only used as a starting value for the phase search
SYNODIC = 29.530588853


def _rev(x):
    """Normalise an angle to 0..360 degrees."""
    return x - 360.0 * math.floor(x / 360.0)


def _rev180(x):
    """Normalise an angle to -180..180 degrees."""
    return (x + 180.0) % 360.0 - 180.0


# --------------------------------------------------------------- Time base

def julian_day(year, month, day, hour=0, minute=0, second=0):
    """Julian day from a UTC calendar date (Gregorian)."""
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    jd = (math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1))
          + day + b - 1524.5)
    return jd + (hour + minute / 60.0 + second / 3600.0) / 24.0


def day_number(year, month, day, hour=0, minute=0, second=0):
    """Days since 1999-12-31 00:00 UT -- the time variable of every formula here."""
    return julian_day(year, month, day, hour, minute, second) - 2451543.5


def day_number_from_jd(jd):
    return jd - 2451543.5


def jd_from_day_number(d):
    return d + 2451543.5


def calendar_from_jd(jd):
    """Inverse of julian_day(): (year, month, day, hour, minute, second)."""
    z = math.floor(jd + 0.5)
    f = (jd + 0.5) - z
    if z < 2299161:
        a = z
    else:
        alpha = math.floor((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - math.floor(alpha / 4)
    b = a + 1524
    c = math.floor((b - 122.1) / 365.25)
    dd = math.floor(365.25 * c)
    e = math.floor((b - dd) / 30.6001)
    day_f = b - dd - math.floor(30.6001 * e) + f
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    day = int(math.floor(day_f))
    rest = (day_f - day) * 24.0
    hour = int(math.floor(rest))
    rest = (rest - hour) * 60.0
    minute = int(math.floor(rest))
    second = int(round((rest - minute) * 60.0))
    if second == 60:
        second = 0
        minute += 1
    if minute == 60:
        minute = 0
        hour += 1
    return year, int(month), day, hour, minute, second


def obliquity(d):
    """Obliquity of the ecliptic, in degrees."""
    return 23.4393 - 3.563e-7 * d


# ------------------------------------------------------------------- Sun

def sun_ecliptic(d):
    """Ecliptic longitude of the sun and its mean anomaly, both in degrees.

    Returns (lon, mean_anomaly, distance_au).
    """
    w = 282.9404 + 4.70935e-5 * d          # longitude of perihelion
    e = 0.016709 - 1.151e-9 * d            # eccentricity
    m = _rev(356.0470 + 0.9856002585 * d)  # mean anomaly

    ea = m + RAD * e * math.sin(m * DEG) * (1.0 + e * math.cos(m * DEG))
    xv = math.cos(ea * DEG) - e
    yv = math.sqrt(1.0 - e * e) * math.sin(ea * DEG)
    v = RAD * math.atan2(yv, xv)
    r = math.sqrt(xv * xv + yv * yv)
    return _rev(v + w), m, r


def sun_equatorial(d):
    """Right ascension and declination of the sun in degrees, plus distance in AU."""
    lon, _, r = sun_ecliptic(d)
    ecl = obliquity(d) * DEG
    x = r * math.cos(lon * DEG)
    y = r * math.sin(lon * DEG) * math.cos(ecl)
    z = r * math.sin(lon * DEG) * math.sin(ecl)
    ra = _rev(RAD * math.atan2(y, x))
    dec = RAD * math.atan2(z, math.sqrt(x * x + y * y))
    return ra, dec, r


# ------------------------------------------------------------------- Moon

def moon_ecliptic(d):
    """Geocentric ecliptic coordinates of the moon.

    Returns (lon_deg, lat_deg, dist_earth_radii). Includes the largest
    perturbation terms: evection, variation, the annual equation and the
    reduction to the ecliptic.
    """
    n = _rev(125.1228 - 0.0529538083 * d)   # longitude of the ascending node
    i = 5.1454                              # inclination
    w = _rev(318.0634 + 0.1643573223 * d)   # argument of perigee
    a = 60.2666                             # semi-major axis in Earth radii
    e = 0.054900
    m = _rev(115.3654 + 13.0649929509 * d)  # mean anomaly

    # Kepler; two iterations are enough at e = 0.055
    ea = m + RAD * e * math.sin(m * DEG) * (1.0 + e * math.cos(m * DEG))
    for _ in range(2):
        ea = ea - (ea - RAD * e * math.sin(ea * DEG) - m) / \
             (1.0 - e * math.cos(ea * DEG))

    xv = a * (math.cos(ea * DEG) - e)
    yv = a * (math.sqrt(1.0 - e * e) * math.sin(ea * DEG))
    v = _rev(RAD * math.atan2(yv, xv))
    r = math.sqrt(xv * xv + yv * yv)

    # Rotate into ecliptic coordinates
    xh = r * (math.cos(n * DEG) * math.cos((v + w) * DEG)
              - math.sin(n * DEG) * math.sin((v + w) * DEG) * math.cos(i * DEG))
    yh = r * (math.sin(n * DEG) * math.cos((v + w) * DEG)
              + math.cos(n * DEG) * math.sin((v + w) * DEG) * math.cos(i * DEG))
    zh = r * (math.sin((v + w) * DEG) * math.sin(i * DEG))

    lon = _rev(RAD * math.atan2(yh, xh))
    lat = RAD * math.atan2(zh, math.sqrt(xh * xh + yh * yh))

    # Perturbations. ls and lm are the *mean* longitudes, not the true ones;
    # from them follows the mean elongation dd, the argument of evection and
    # variation.
    ms = _sun_mean_anomaly(d)
    ls = _rev(_sun_perihelion(d) + ms)                     # sun mean longitude
    lm = _rev(n + w + m)                                   # moon mean longitude
    mm = m
    dd = _rev(lm - ls)                                     # mean elongation
    f = _rev(lm - n)                                       # argument of latitude

    lon += (-1.274 * math.sin((mm - 2 * dd) * DEG)         # evection
            + 0.658 * math.sin(2 * dd * DEG)               # variation
            - 0.186 * math.sin(ms * DEG)                   # annual equation
            - 0.059 * math.sin((2 * mm - 2 * dd) * DEG)
            - 0.057 * math.sin((mm - 2 * dd + ms) * DEG)
            + 0.053 * math.sin((mm + 2 * dd) * DEG)
            + 0.046 * math.sin((2 * ls - ms) * DEG)
            + 0.041 * math.sin((mm - ms) * DEG)
            - 0.035 * math.sin(dd * DEG)                   # parallactic equation
            - 0.031 * math.sin((mm + ms) * DEG)
            - 0.015 * math.sin((2 * f - 2 * dd) * DEG)
            + 0.011 * math.sin((mm - 4 * dd) * DEG))

    lat += (-0.173 * math.sin((f - 2 * dd) * DEG)
            - 0.055 * math.sin((mm - f - 2 * dd) * DEG)
            - 0.046 * math.sin((mm + f - 2 * dd) * DEG)
            + 0.033 * math.sin((f + 2 * dd) * DEG)
            + 0.017 * math.sin((2 * mm + f) * DEG))

    r += (-0.58 * math.cos((mm - 2 * dd) * DEG)
          - 0.46 * math.cos(2 * dd * DEG))

    return _rev(lon), lat, r


def _sun_mean_anomaly(d):
    return _rev(356.0470 + 0.9856002585 * d)


def _sun_perihelion(d):
    return _rev(282.9404 + 4.70935e-5 * d)


def moon_equatorial(d):
    """Right ascension and declination in degrees, distance in Earth radii."""
    lon, lat, r = moon_ecliptic(d)
    ecl = obliquity(d) * DEG
    xh = r * math.cos(lon * DEG) * math.cos(lat * DEG)
    yh = r * math.sin(lon * DEG) * math.cos(lat * DEG)
    zh = r * math.sin(lat * DEG)
    xe = xh
    ye = yh * math.cos(ecl) - zh * math.sin(ecl)
    ze = yh * math.sin(ecl) + zh * math.cos(ecl)
    ra = _rev(RAD * math.atan2(ye, xe))
    dec = RAD * math.atan2(ze, math.sqrt(xe * xe + ye * ye))
    return ra, dec, r


# ------------------------------------------------------------------ Phase

def moon_phase(d):
    """Illuminated fraction and phase position of the moon.

    Returned as a dict:
      illum    0..1, illuminated fraction of the visible disc
      age      0..1, position within the synodic month (0 = new, 0.5 = full)
      waxing   True while the moon is waxing
      phase    phase angle sun-moon-earth in degrees (0 = full, 180 = new)
      dist_km  geocentric distance
    """
    slon, _, _ = sun_ecliptic(d)
    mlon, mlat, r = moon_ecliptic(d)

    elong = RAD * math.acos(max(-1.0, min(1.0, math.cos((slon - mlon) * DEG)
                                          * math.cos(mlat * DEG))))
    phase_angle = 180.0 - elong
    illum = (1.0 + math.cos(phase_angle * DEG)) / 2.0

    age = _rev(mlon - slon) / 360.0
    return {
        "illum": illum,
        "age": age,
        "waxing": age < 0.5,
        "phase": phase_angle,
        "dist_km": r * 6371.0,
    }


def bright_limb_angle(d):
    """Position angle of the moon's bright limb, from north through east, in degrees.

    Only needed if the shadow boundary is supposed to tilt realistically.
    """
    sra, sdec, _ = sun_equatorial(d)
    mra, mdec, _ = moon_equatorial(d)
    dra = (sra - mra) * DEG
    y = math.cos(sdec * DEG) * math.sin(dra)
    x = (math.sin(sdec * DEG) * math.cos(mdec * DEG)
         - math.cos(sdec * DEG) * math.sin(mdec * DEG) * math.cos(dra))
    return _rev(RAD * math.atan2(y, x))


# ------------------------------------------------------- Local horizon

def sidereal_time(d, lon_east):
    """Local mean sidereal time in degrees."""
    slon, sm, _ = sun_ecliptic(d)
    gmst0 = _rev(slon + 180.0)
    ut_hours = (d - math.floor(d)) * 24.0
    return _rev(gmst0 + ut_hours * 15.0 + lon_east)


def horizontal(ra, dec, d, lat, lon_east):
    """Convert right ascension/declination to altitude and azimuth, in degrees.

    Azimuth is counted from north through east.
    """
    ha = _rev(sidereal_time(d, lon_east) - ra)
    ha_r = ha * DEG
    dec_r = dec * DEG
    lat_r = lat * DEG

    x = math.cos(ha_r) * math.cos(dec_r)
    y = math.sin(ha_r) * math.cos(dec_r)
    z = math.sin(dec_r)

    xh = x * math.sin(lat_r) - z * math.cos(lat_r)
    zh = x * math.cos(lat_r) + z * math.sin(lat_r)

    az = _rev(RAD * math.atan2(y, xh) + 180.0)
    alt = RAD * math.atan2(zh, math.sqrt(xh * xh + y * y))
    return alt, az


def moon_altitude(d, lat, lon_east):
    """Topocentric altitude and azimuth of the moon, in degrees.

    The moon's parallax reaches a full degree and is largest exactly at the
    horizon -- which is where this lamp decides whether it is on.
    """
    ra, dec, r = moon_equatorial(d)
    alt, az = horizontal(ra, dec, d, lat, lon_east)
    parallax = RAD * math.asin(1.0 / r)
    return alt - parallax * math.cos(alt * DEG), az


def sun_altitude(d, lat, lon_east):
    """Altitude and azimuth of the sun, in degrees."""
    ra, dec, _ = sun_equatorial(d)
    return horizontal(ra, dec, d, lat, lon_east)


# ------------------------------------------------------------ Phase instants

def next_phase(d, target_age, max_days=40.0):
    """Next moment after d at which `age` reaches the target value.

    target_age: 0.0 new moon, 0.25 first quarter, 0.5 full, 0.75 last quarter.
    Returns a day number d, or None if not found.
    """
    def diff(x):
        return _rev180((moon_phase(x)["age"] - target_age) * 360.0)

    step = 0.5
    prev = diff(d)
    t = d
    while t - d < max_days:
        t += step
        cur = diff(t)
        if prev < 0.0 <= cur:
            lo, hi = t - step, t
            for _ in range(40):
                mid = 0.5 * (lo + hi)
                if diff(mid) < 0.0:
                    lo = mid
                else:
                    hi = mid
            return 0.5 * (lo + hi)
        prev = cur
    return None
