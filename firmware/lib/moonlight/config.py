"""Load, validate and save the configuration.

Stored as config.json in the Pico's filesystem. If it is missing or the Wi-Fi
settings are unusable, main.py opens the setup portal.
"""

try:
    import ujson as json
except ImportError:
    import json

PATH = "config.json"

DEFAULTS = {
    # Network
    "ssid": "",
    "password": "",
    "hostname": "moonlamp",

    # Location, only needed for P2. Positive = north / east.
    "latitude": 51.2,
    "longitude": 6.8,
    "utc_offset": 1,            # standard time; timeutil adds summer time
    "eu_dst": True,

    # Hardware
    "led_pin": 16,
    # 33 mm pitch on the r = 209 mm ring (1313 mm circumference) fits 40 LEDs
    # with a 26 mm closing gap at the seam -- 39 would leave a visible 59 mm.
    "led_count": 40,
    "led_offset": 270.0,        # angle of pixel 0; 270 = 6 o'clock, bottom
    "led_clockwise": False,
    "button_program": 12,
    "button_up": 13,
    "button_down": 14,

    # Behaviour
    "program": 1,
    "brightness": 3,            # index into BRIGHTNESS_STEPS
    "fps": 60,

    # Temporal dithering. Needs the DMA output path; without it the setting is
    # ignored and the lamp stays on the blocking path. Off by default so that
    # a board where DMA misbehaves always boots into the safe mode.
    "temporal": False,
    "subframes": 8,
    "earthshine": 0.018,
    "eclipses": [],             # list of "YYYY-MM-DD" dates for the red moon
}

# Perceptual steps. The lower bound is set by the hardware, not by taste: with
# 8 bits per channel the dimmest level at which *every* LED still lights is one
# count, i.e. 1/255 = 0.39 % of linear light. In perceptual terms that is
# 0.39 %^(1/2.2) = 0.081. Going below that does not dim the ring, it thins it
# out into single lit pixels that crawl around as the dither pattern shifts.
BRIGHTNESS_STEPS = (0.09, 0.15, 0.25, 0.40, 0.65, 1.00)

_RANGES = {
    "latitude": (-90.0, 90.0),
    "longitude": (-180.0, 180.0),
    "utc_offset": (-12, 14),
    "led_count": (1, 300),
    "led_offset": (0.0, 360.0),
    "fps": (10, 200),
    "earthshine": (0.0, 0.2),
    "brightness": (0, len(BRIGHTNESS_STEPS) - 1),
    "subframes": (1, 16),
    "program": (0, 7),
}


def load():
    cfg = dict(DEFAULTS)
    try:
        with open(PATH) as fh:
            stored = json.load(fh)
        for k, v in stored.items():
            if k in cfg:
                cfg[k] = v
    except (OSError, ValueError):
        pass
    return validate(cfg)


def validate(cfg):
    """Force values into range, so a broken file cannot block the lamp."""
    for key, (lo, hi) in _RANGES.items():
        try:
            v = cfg[key]
            if isinstance(lo, int) and isinstance(hi, int):
                v = int(v)
            else:
                v = float(v)
            cfg[key] = lo if v < lo else (hi if v > hi else v)
        except (KeyError, TypeError, ValueError):
            cfg[key] = DEFAULTS[key]
    for key in ("ssid", "password", "hostname"):
        if not isinstance(cfg.get(key), str):
            cfg[key] = DEFAULTS[key]
    if not isinstance(cfg.get("eclipses"), list):
        cfg["eclipses"] = []
    return cfg


def save(cfg):
    tmp = PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(cfg, fh)
    try:
        import os
        os.remove(PATH)
    except OSError:
        pass
    try:
        import os
        os.rename(tmp, PATH)
    except OSError:
        # Some ports cannot rename; then write directly
        with open(PATH, "w") as fh:
            json.dump(cfg, fh)


def configured(cfg):
    return bool(cfg.get("ssid"))
