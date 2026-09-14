"""Firmware versions: the one built into this installer, and newer ones on
GitHub.

The installer always carries a complete copy of the firmware, so a rebuild
works with no network at all -- someone flashing a board in a workshop should
not need one. GitHub is only consulted when asked, to see whether something
newer has been published since this installer was built.

Uses urllib rather than requests: one less thing to bundle, and the API is a
single unauthenticated GET against a public repository.
"""

import io
import json
import os
import re
import ssl
import sys
import zipfile

try:
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError
except ImportError:                                   # pragma: no cover
    from urllib2 import Request, urlopen, URLError, HTTPError

REPO = "Felteshobbies/moonlamp"
API = "https://api.github.com/repos/%s/releases" % REPO
TIMEOUT = 15.0

# Files that belong on the device, in the order they are written. main.py last
# on purpose: if anything goes wrong partway, the board still has the old
# main.py and boots into something that works.
DEVICE_FILES = (
    "lib/moonlight/__init__.py",
    "lib/moonlight/buttons.py",
    "lib/moonlight/config.py",
    "lib/moonlight/dither.py",
    "lib/moonlight/ephemeris.py",
    "lib/moonlight/leds.py",
    "lib/moonlight/programs.py",
    "lib/moonlight/render.py",
    "lib/moonlight/timeutil.py",
    "lib/moonlight/web.py",
    "main.py",
)


class ReleaseError(Exception):
    pass


# ------------------------------------------------------------- versions

def parse_version(text):
    """A version string as a comparable tuple, with pre-releases sorting low.

    "0.2" > "0.2-dev" > "0.1". A trailing suffix means not-yet-released, so it
    has to sort below the bare number, which a plain tuple comparison of the
    numeric parts alone would get wrong.
    """
    if not text:
        return ()
    text = text.strip().lstrip("vV")
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", text)
    if not m:
        return ()
    nums = tuple(int(p) for p in m.group(1).split("."))
    suffix = m.group(2).strip(" -_")
    # 1 for a plain release, 0 for anything with a suffix
    return nums + (1 if not suffix else 0,)


def is_newer(candidate, installed):
    """True when `candidate` is a version worth offering as an update."""
    a, b = parse_version(candidate), parse_version(installed)
    if not a:
        return False
    if not b:
        return True
    # Compare on equal length so 0.2 beats 0.1.9 rather than tripping on it
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


# ------------------------------------------------------------- bundled

def _resource_root():
    """Where our data files live, frozen or not.

    PyInstaller unpacks a one-file build into a temporary directory and points
    sys._MEIPASS at it; from source the files sit next to this module.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "payload")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "payload")


def _dev_root():
    """Running from a source checkout: use the repository's own firmware."""
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(here, os.pardir, os.pardir))
    return os.path.join(repo, "firmware")


def firmware_root():
    """Where the bundled firmware actually is, packaged or from source."""
    packed = os.path.join(_resource_root(), "firmware")
    if os.path.isfile(os.path.join(packed, "main.py")):
        return packed
    return _dev_root()


def bundled_firmware():
    """The firmware carried inside this installer, as {path: bytes}."""
    root = firmware_root()
    out = {}
    for name in DEVICE_FILES:
        path = os.path.join(root, name.replace("/", os.sep))
        if not os.path.isfile(path):
            raise ReleaseError("the installer is missing %s" % name)
        with open(path, "rb") as fh:
            out[name] = fh.read()
    return out


def bundled_version():
    fw = bundled_firmware()
    return version_of(fw)


def version_of(files):
    """Read VERSION out of a firmware file set without importing it."""
    src = files.get("lib/moonlight/__init__.py", b"").decode("utf-8", "replace")
    m = re.search(r"""VERSION\s*=\s*["']([^"']+)["']""", src)
    return m.group(1) if m else None


def bundled_uf2():
    """Path of the MicroPython build shipped with the installer, or None."""
    root = os.path.join(_resource_root(), "micropython")
    if not os.path.isdir(root):
        root = os.path.join(_dev_root(), "micropython")
    if not os.path.isdir(root):
        return None
    for name in sorted(os.listdir(root)):
        if name.lower().endswith(".uf2"):
            return os.path.join(root, name)
    return None


# -------------------------------------------------------------- GitHub

def _get(url, accept="application/vnd.github+json"):
    req = Request(url, headers={"Accept": accept,
                                "User-Agent": "moonlamp-installer"})
    try:
        # Frozen builds do not always find the system certificate store
        ctx = ssl.create_default_context()
        return urlopen(req, timeout=TIMEOUT, context=ctx).read()
    except HTTPError as exc:
        if exc.code == 403:
            raise ReleaseError("GitHub is rate limiting this address; "
                               "try again in a few minutes")
        raise ReleaseError("GitHub returned %s" % exc.code)
    except URLError as exc:
        raise ReleaseError("no connection to GitHub: %s" % exc.reason)


def list_releases(include_prereleases=False):
    """Published releases, newest first, as dicts with version/url/notes."""
    data = json.loads(_get(API).decode("utf-8"))
    out = []
    for rel in data:
        if rel.get("draft"):
            continue
        if rel.get("prerelease") and not include_prereleases:
            continue
        asset = None
        for a in rel.get("assets", ()):
            name = a.get("name", "")
            if name.startswith("moonlamp-firmware") and name.endswith(".zip"):
                asset = a.get("browser_download_url")
                break
        out.append({
            "version": (rel.get("tag_name") or "").lstrip("vV"),
            "name": rel.get("name") or rel.get("tag_name"),
            "notes": rel.get("body") or "",
            "asset": asset,
            "prerelease": bool(rel.get("prerelease")),
        })
    out.sort(key=lambda r: parse_version(r["version"]), reverse=True)
    return out


def latest_release(include_prereleases=False):
    rels = [r for r in list_releases(include_prereleases) if r["asset"]]
    return rels[0] if rels else None


def download_firmware(url):
    """Fetch a release archive and return {path: bytes} for the device files.

    The archive has a single top-level folder, so paths are matched by their
    tail rather than by position -- that way the folder can be renamed without
    breaking the installer.
    """
    raw = _get(url, accept="application/octet-stream")
    out = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        for want in DEVICE_FILES:
            hit = None
            for n in names:
                if n.replace("\\", "/").endswith("/" + want) or n == want:
                    hit = n
                    break
            if hit is None:
                raise ReleaseError("the archive is missing %s" % want)
            out[want] = z.read(hit)
    return out
