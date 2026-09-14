"""Render the control page to a file, so the styling can be worked on
without a Pico on the bench.

    python firmware\\tools\\render_sample_page.py

Writes firmware/tests/control_page_sample.html. The values are invented but
shaped exactly like the ones main.build_info() produces, so the layout is
representative. Nothing from a real network goes in here -- the file is
published, so the sample stays synthetic.
"""

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "lib"))

from moonlight import config as configmod   # noqa: E402
from moonlight import programs              # noqa: E402
from moonlight import web                   # noqa: E402

OUT = os.path.join(HERE, os.pardir, "tests", "control_page_sample.html")

cfg = dict(configmod.DEFAULTS)
cfg.update({
    "ssid": "MyNetwork",
    "program": 2,
    "brightness": 3,
    "led_count": 40,
    "led_offset": 270.0,
})

level = configmod.BRIGHTNESS_STEPS[cfg["brightness"]]

info = {
    "status": "connected to MyNetwork · 192.0.2.42 · -36 dBm",
    "facts": [
        ("Program", "P%d %s" % (cfg["program"], programs.NAMES[cfg["program"]])),
        ("Brightness", "%.1f %%" % (level * 100)),
        ("Signal", "-36 dBm"),
        ("IP", "192.0.2.42"),
        ("Local time", "22:14"),
        ("Date", "2026-09-13"),
        ("Moon phase", "63 % waning"),
        ("Moon age", "18.7 days"),
        ("Distance", "391240 km"),
        ("Moon altitude", "+21.4 deg above the horizon"),
        ("Uptime", "143 min"),
    ],
    "manual": {"illum": 0.5, "waxing": True,
               "r": 0.0, "g": 0.0, "b": 0.0, "w": 1.0},
    "output": "blocking",
}

html = web.control_page(cfg, info)
io.open(OUT, "w", encoding="utf-8", newline="\n").write(html)
print("wrote %s (%d bytes)" % (os.path.relpath(OUT), len(html)))
