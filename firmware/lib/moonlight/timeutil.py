"""Time: NTP, epochs and the EU daylight-saving rule.

MicroPython on the RP2 counts seconds from 2000-01-01, CPython from
1970-01-01. This module converts either one into the ephemeris day number, so
that the same code produces the same result on a PC and on the Pico.
"""

import time

from . import ephemeris as eph

# Seconds between 1970-01-01 and 2000-01-01
EPOCH_DELTA = 946684800

# Detect which epoch this runtime uses
_MP_EPOCH = time.gmtime(0)[0] == 2000


def utc_day_number():
    """Current ephemeris day number, taken from the system clock (UTC)."""
    t = time.gmtime()
    return eph.day_number(t[0], t[1], t[2], t[3], t[4], t[5])


def unix_to_day_number(seconds):
    """Convert Unix time (1970 epoch) into the day number."""
    t = time.gmtime(seconds - EPOCH_DELTA if _MP_EPOCH else seconds)
    return eph.day_number(t[0], t[1], t[2], t[3], t[4], t[5])


def is_eu_dst(year, month, day, hour):
    """EU summer time: last Sunday in March 01:00 UTC to last Sunday in October."""
    if month < 3 or month > 10:
        return False
    if 3 < month < 10:
        return True
    last_sunday = _last_sunday(year, month)
    if month == 3:
        if day > last_sunday:
            return True
        if day < last_sunday:
            return False
        return hour >= 1
    if day > last_sunday:
        return False
    if day < last_sunday:
        return True
    return hour < 1


def _last_sunday(year, month):
    """Day of the last Sunday in the month, without a calendar module."""
    days = 31 if month in (1, 3, 5, 7, 8, 10, 12) else 30
    if month == 2:
        days = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
    # Zeller's congruence: 0 = Saturday, 1 = Sunday, ...
    y, m = year, month
    if m < 3:
        m += 12
        y -= 1
    k = y % 100
    j = y // 100
    h = (days + (13 * (m + 1)) // 5 + k + k // 4 + j // 4 + 5 * j) % 7
    weekday = (h + 6) % 7          # 0 = Sunday
    return days - weekday


def local_offset_hours(cfg, d):
    """Offset from UTC in hours, including summer time."""
    off = cfg.get("utc_offset", 0)
    if cfg.get("eu_dst"):
        y, mo, da, h, _, _ = eph.calendar_from_jd(eph.jd_from_day_number(d))
        if is_eu_dst(y, mo, da, h):
            off += 1
    return off


def sync_ntp(retries=3):
    """Set the system clock over NTP. Returns True on success."""
    try:
        import ntptime
    except ImportError:
        return False
    for _ in range(retries):
        try:
            ntptime.settime()
            return True
        except Exception:
            time.sleep(2)
    return False
