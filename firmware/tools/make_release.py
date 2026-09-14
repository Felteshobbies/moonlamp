"""Build the firmware release archive.

    python firmware\\tools\\make_release.py

Writes dist/moonlamp-firmware-<VERSION>.zip. The version comes from
moonlight.VERSION, so there is exactly one place to bump.

What goes in is what somebody needs to put the lamp together: the code that
runs on the Pico, the two scripts that talk to it, and the documentation.
Development scaffolding -- the test suites, the translation helpers, the page
renderer -- stays in the repository and out of the archive.
"""

import io
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRMWARE = os.path.join(HERE, os.pardir)
ROOT = os.path.abspath(os.path.join(FIRMWARE, os.pardir))
sys.path.insert(0, os.path.join(FIRMWARE, "lib"))

from moonlight import VERSION   # noqa: E402

# published path -> source path, both relative to the repository root
CONTENTS = {}
for name in ("main.py",):
    CONTENTS[name] = os.path.join("firmware", name)
for name in ("__init__", "buttons", "config", "dither", "ephemeris", "leds",
             "programs", "render", "timeutil", "web"):
    CONTENTS["lib/moonlight/%s.py" % name] = \
        os.path.join("firmware", "lib", "moonlight", "%s.py" % name)
for name in ("provision.py", "status.py"):
    CONTENTS["tools/" + name] = os.path.join("firmware", "tools", name)
CONTENTS["README.md"] = os.path.join("firmware", "README.md")
CONTENTS["LICENSE"] = "LICENSE"


def build():
    out_dir = os.path.join(ROOT, "dist")
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    stem = "moonlamp-firmware-%s" % VERSION
    path = os.path.join(out_dir, stem + ".zip")

    missing = [src for src in CONTENTS.values()
               if not os.path.isfile(os.path.join(ROOT, src))]
    if missing:
        raise SystemExit("missing: %s" % ", ".join(missing))

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for dst in sorted(CONTENTS):
            src = os.path.join(ROOT, CONTENTS[dst])
            # Normalise to LF so the archive is identical on every platform
            data = io.open(src, encoding="utf-8").read().replace("\r\n", "\n")
            z.writestr("%s/%s" % (stem, dst), data)

    size = os.path.getsize(path)
    print("wrote %s" % os.path.relpath(path, ROOT))
    print("  %d files, %.1f kB" % (len(CONTENTS), size / 1024.0))
    return path


if __name__ == "__main__":
    build()
