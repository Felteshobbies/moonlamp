"""Small HTTP server: setup portal and control page.

Non-blocking -- `poll()` is called from the main loop and returns
immediately when nothing is pending, so the frame rate stays constant
while someone is using the page.
"""

import socket

try:
    import ujson as json
except ImportError:
    import json

from . import VERSION
from . import config as configmod
from . import programs

MAX_REQUEST = 2048


def _unquote(s):
    s = s.replace("+", " ")
    out = ""
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            try:
                out += chr(int(s[i + 1:i + 3], 16))
                i += 3
                continue
            except ValueError:
                pass
        out += s[i]
        i += 1
    return out


def parse_query(qs):
    out = {}
    for part in qs.split("&"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out[_unquote(k)] = _unquote(v)
        else:
            out[_unquote(part)] = ""
    return out


def _send_all(conn, data):
    """Write everything out, even if send() only accepts part of it."""
    try:
        conn.sendall(data)
        return
    except AttributeError:
        pass
    sent = 0
    while sent < len(data):
        n = conn.send(data[sent:])
        if not n:
            break
        sent += n


class Server(object):
    def __init__(self, port=80):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", port))
        self.sock.listen(2)
        self.sock.setblocking(False)

    def _read_request(self, conn):
        """Read the complete request, not just the first packet.

        Browsers routinely send the head and the body of a POST in separate
        TCP segments. Calling recv() once often yields only the head; the
        form then arrives empty and nothing gets saved. So: read to the end
        of the head, look at Content-Length, then pull in the rest.
        """
        sep = b"\r\n\r\n"
        raw = b""
        while sep not in raw:
            try:
                chunk = conn.recv(MAX_REQUEST)
            except OSError:
                chunk = b""
            if not chunk:
                return raw
            raw += chunk
            if len(raw) > MAX_REQUEST * 4:
                return raw

        head, _, body = raw.partition(sep)
        length = 0
        for h in head.split(b"\r\n")[1:]:
            if h.lower().startswith(b"content-length:"):
                try:
                    length = int(h.split(b":", 1)[1].strip())
                except ValueError:
                    length = 0
                break
        if length > MAX_REQUEST * 4:
            length = MAX_REQUEST * 4
        while len(body) < length:
            try:
                chunk = conn.recv(length - len(body))
            except OSError:
                break
            if not chunk:
                break
            body += chunk
        return head + sep + body

    def poll(self, handler):
        """Serve one pending request, if there is one."""
        try:
            conn, _ = self.sock.accept()
        except OSError:
            return False
        try:
            conn.settimeout(3.0)
            raw = self._read_request(conn)
            if not raw:
                return True
            head, _, body = raw.partition(b"\r\n\r\n")
            line = head.split(b"\r\n", 1)[0].decode()
            parts = line.split(" ")
            path = parts[1] if len(parts) > 1 else "/"
            query = {}
            if "?" in path:
                path, qs = path.split("?", 1)
                query = parse_query(qs)
            if body:
                query.update(parse_query(body.decode()))
            status, ctype, payload = handler(path, query)
            if isinstance(payload, str):
                payload = payload.encode()
            header = ("HTTP/1.0 %s\r\nContent-Type: %s\r\n"
                      "Content-Length: %d\r\n"
                      "Cache-Control: no-store\r\nConnection: close\r\n\r\n"
                      % (status, ctype, len(payload)))
            # Bytes, not str: MicroPython accepts str, CPython does not --
            # without that difference the bug only shows up on the device.
            _send_all(conn, header.encode())
            _send_all(conn, payload)
        except Exception as exc:
            # The REPL is the only place to see anything on the device
            print("HTTP error:", exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return True

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# ------------------------------------------------------------------- Portal

PORTAL_FIELDS = (
    ("ssid", "Wi-Fi network", "text"),
    ("password", "Password", "password"),
    ("hostname", "Hostname", "text"),
    ("latitude", "Latitude (north positive)", "text"),
    ("longitude", "Longitude (east positive)", "text"),
    ("utc_offset", "Time zone (hours from UTC)", "text"),
    ("led_count", "Number of LEDs", "text"),
    ("led_offset", "Angle of pixel 0 (degrees)", "text"),
)


def portal_page(cfg, message=""):
    rows = []
    for key, label, kind in PORTAL_FIELDS:
        val = "" if kind == "password" else str(cfg.get(key, ""))
        rows.append("<label>%s<input name='%s' type='%s' value='%s'></label>"
                    % (label, key, kind, val))
    return _PAGE % {
        "head": "",
        "title": "Moon lamp setup",
        "body": ("<h1>Moon lamp setup</h1>"
                 "%s<form method='post' action='/save'>%s"
                 "<button type='submit'>Save and restart</button>"
                 "</form>"
                 "<p class='hint'>Wi-Fi names are case sensitive. The location is "
                 "only needed for the <b>Real moon</b> program. The angle of "
                 "pixel&nbsp;0 can also be set on the device: press and hold "
                 "the program button.</p>"
                 % ("<p class='msg'>%s</p>" % message if message else "",
                    "".join(rows))),
    }


DESCRIPTIONS = (
    "Every mode at high speed, a whole month in a minute. Needs neither network nor clock.",
    "The current moon phase, visible around the clock.",
    "Like P1, but only while the moon is actually up. Brightness and colour follow its altitude.",
    "Full moon with a slowly drifting hue.",
    "The dimmest possible warm white across the whole ring.",
    "Azimuth, illuminated fraction and warmth set by hand.",
)


def control_page(cfg, info):
    """Control page showing everything the device knows about itself.

    `info` is a dict filled in by main.py -- the page computes nothing itself,
    so that loading it does not disturb the frame rate.
    """
    cards = []
    for label, value in info.get("facts", ()):
        cards.append("<div><dt>%s</dt><dd>%s</dd></div>" % (label, value))

    progs = []
    for i in range(programs.N_PROGRAMS):
        on = " on" if i == cfg["program"] else ""
        desc = DESCRIPTIONS[i] if i < len(DESCRIPTIONS) else ""
        progs.append(
            "<a class='prog%s' href='/set?program=%d'>"
            "<b>P%d &middot; %s</b><span>%s</span></a>"
            % (on, i, i, programs.NAMES[i], desc))

    steps = []
    for i in range(len(configmod.BRIGHTNESS_STEPS)):
        on = " on" if i == cfg["brightness"] else ""
        pct = configmod.BRIGHTNESS_STEPS[i] * 100
        txt = ("%.1f" % pct).rstrip("0").rstrip(".")
        steps.append("<a class='chip%s' href='/set?brightness=%d'>%s&nbsp;%%</a>"
                     % (on, i, txt))

    manual = info.get("manual", {})
    m_illum = int(manual.get("illum", 0.5) * 100)
    m_warmth = int(manual.get("warmth", 0.0) * 100)
    waxing = manual.get("waxing", True)

    n_leds = int(cfg["led_count"])
    offset = float(cfg["led_offset"])
    pitch = 360.0 / n_leds if n_leds else 0.0
    cw = bool(cfg.get("led_clockwise"))

    out = ["<h1>Moon lamp</h1><p class='sub'>%s</p>" % info.get("status", "")]
    out.append("<dl class='facts'>%s</dl>" % "".join(cards))

    out.append("<h2>Program</h2><div class='progs'>%s</div>" % "".join(progs))
    out.append("<h2>Brightness</h2><div class='chips'>%s</div>" % "".join(steps))

    # Earthshine is a fraction of linear light, so the slider works in tenths
    # of a percent rather than in the raw value.
    es = int(round(float(cfg.get("earthshine", 0.018)) * 1000.0))
    out.append("<h2>Earthshine</h2>"
               "<form action='/set'>"
               "<label>Glow on the dark side <output>%s</output>"
               "<input name='earthshine' type='range' min='0' max='50' "
               "value='%d'%s></label>"
               "<button type='submit'>Apply</button></form>"
               "<p class='hint'>The averted half of the real moon is lit "
               "faintly by earthlight. 0 turns it off. On the lower brightness "
               "steps it is dropped automatically, because a glow weaker than "
               "one count would only show as scattered pixels.</p>"
               % ("off" if es == 0 else "%.1f&nbsp;%%" % (es / 10.0),
                  es, _LIVE_PERMILLE))

    out.append("<h2>Manual &mdash; switches to P5</h2>"
               "<form action='/set'>"
               "<input type='hidden' name='program' value='5'>"
               "<label>Illuminated fraction <output>%d&nbsp;%%</output>"
               "<input name='illum' type='range' min='0' max='100' value='%d'%s>"
               "</label>"
               "<label>Direction<select name='waxing'>"
               "<option value='1'%s>waxing &ndash; lit from the right</option>"
               "<option value='0'%s>waning &ndash; lit from the left</option>"
               "</select></label>"
               "<label>Warmth <output>%d&nbsp;%%</output>"
               "<input name='warmth' type='range' min='0' max='100' value='%d'%s>"
               "</label>"
               "<button type='submit'>Apply</button></form>"
               % (m_illum, m_illum, _LIVE, "" if not waxing else " selected",
                  " selected" if not waxing else "",
                  m_warmth, m_warmth, _LIVE))

    # --- Ring geometry. The angle is the one setting you want to change while
    # watching the lamp, so it gets nudge buttons of exactly one LED pitch.
    out.append("<h2>Ring</h2>"
               "<form action='/set'>"
               "<label>Angle of pixel 0 <output>%d&deg;</output>"
               "<input name='led_offset' type='range' min='0' max='359' "
               "value='%d'%s></label>"
               "<label>Pixel order<select name='led_clockwise'>"
               "<option value='0'%s>counter-clockwise</option>"
               "<option value='1'%s>clockwise</option>"
               "</select></label>"
               "<button type='submit'>Apply</button></form>"
               "<div class='chips'>"
               "<a class='chip' href='/set?nudge=-1'>&minus;1 LED</a>"
               "<a class='chip' href='/set?nudge=1'>+1 LED</a>"
               "<a class='chip' href='/calibrate'>Find the angle</a></div>"
               "<p class='hint'>Zero degrees is the right-hand side of the "
               "ring, 90&deg; the top, 270&deg; the bottom. One LED is "
               "%.1f&deg; here. If you do not know where pixel&nbsp;0 ended "
               "up, press &ldquo;Find the angle&rdquo;: it lights the single "
               "LED this setting believes is at the <em>bottom</em> of the "
               "ring. Nudge by &plusmn;1&nbsp;LED until the lit one really is "
               "at the bottom &mdash; then the angle is right. Press the "
               "program button on the device, or pick a program here, to "
               "leave that mode again.</p>"
               % (int(offset), int(offset), _LIVE,
                  "" if cw else " selected", " selected" if cw else "",
                  pitch))

    out.append("<form action='/set'>"
               "<label>Number of LEDs <input name='led_count' type='number' "
               "min='1' max='300' value='%d'></label>"
               "<button type='submit'>Apply and restart</button></form>"
               "<p class='hint'>Changing the count restarts the lamp: the "
               "output buffer is allocated once at start-up.</p>" % n_leds)

    tmp = bool(cfg.get("temporal"))
    out.append("<h2>Output</h2>"
               "<form action='/set'>"
               "<label>Temporal dithering<select name='temporal'>"
               "<option value='0'%s>off &ndash; 8 bit, no DMA</option>"
               "<option value='1'%s>on &ndash; DMA, subframes</option>"
               "</select></label>"
               "<label>Subframes <output>%d</output>"
               "<input name='subframes' type='range' min='2' max='16' "
               "value='%d'%s></label>"
               "<button type='submit'>Apply and restart</button></form>"
               "<p class='hint'>Currently running: <b>%s</b>. Temporal "
               "dithering shows several slightly different frames in quick "
               "succession; the eye averages them, which adds about three bits "
               "and makes single LEDs fade in smoothly at the low brightness "
               "steps. It needs the DMA path &ndash; if that is unavailable the "
               "lamp falls back automatically and says so here.</p>"
               % ("" if tmp else " selected", " selected" if tmp else "",
                  int(cfg.get("subframes", 8)), int(cfg.get("subframes", 8)),
                  _LIVE_PLAIN, info.get("output", "unknown")))

    out.append("<h2>Device</h2><div class='chips'>"
               "<a class='chip' href='/reboot'>Restart</a>"
               "<a class='chip warn' href='/forget'>Forget Wi-Fi</a></div>"
               "<p class='hint'>This page refreshes every 30&nbsp;seconds. "
               "Firmware %s.</p>" % VERSION)

    return _PAGE % {"title": "Moon lamp", "body": "".join(out),
                    "head": "<meta http-equiv='refresh' content='30'>"}


# Shows the slider value while dragging, without needing a round trip
_LIVE = (" oninput=\"this.parentNode.querySelector('output').textContent="
         "this.value+(this.name=='led_offset'?'\\u00b0':' %')\"")


_PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
%(head)s<title>%(title)s</title><style>
:root{--fg:#14161a;--bg:#eef0f2;--card:#fff;--mut:#5c646e;--line:#d6dbe1;
 --accent:#b87333;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--fg:#e6e9ed;--bg:#101317;
 --card:#191d22;--mut:#98a1ac;--line:#282e35;--accent:#d99a5b}}
*{box-sizing:border-box}
body{font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;
 padding:24px 18px 56px;max-width:36rem;margin-inline:auto;
 background:var(--bg);color:var(--fg)}
h1{font-size:1.6rem;margin:0 0 .3rem;letter-spacing:-.02em}
h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.09em;
 color:var(--mut);margin:1.8rem 0 .6rem;font-weight:600}
.sub{color:var(--mut);font-size:.9rem;margin:0 0 1.2rem}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));
 gap:1px;background:var(--line);border:1px solid var(--line);
 border-radius:10px;overflow:hidden;margin:0}
.facts>div{background:var(--card);padding:10px 12px}
dt{font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;
 color:var(--mut);margin:0 0 2px}
dd{margin:0;font-weight:600;font-variant-numeric:tabular-nums;font-size:.95rem}
.progs{display:grid;gap:.5rem}
.prog{display:block;padding:.7rem .85rem;border:1px solid var(--line);
 border-radius:10px;background:var(--card);text-decoration:none;color:inherit}
.prog b{display:block;font-size:.95rem}
.prog span{display:block;color:var(--mut);font-size:.8rem;margin-top:2px}
.prog.on{border-color:var(--accent);box-shadow:inset 3px 0 0 var(--accent)}
.chips{display:flex;flex-wrap:wrap;gap:.45rem}
.chip{padding:.5rem .8rem;border:1px solid var(--line);border-radius:999px;
 background:var(--card);text-decoration:none;color:inherit;font-size:.88rem}
.chip.on{background:var(--accent);border-color:var(--accent);color:#fff}
.chip.warn{color:#c0392b}
label{display:block;margin:0 0 .9rem;font-size:.9rem}
label output{float:right;color:var(--mut);font-variant-numeric:tabular-nums}
input,select{width:100%%;padding:.5rem;font:inherit;margin-top:.3rem;
 border:1px solid var(--line);border-radius:8px;background:var(--card);
 color:inherit}
input[type=range]{padding:0;border:0;background:transparent;accent-color:var(--accent)}
button{width:100%%;padding:.75rem;font:inherit;font-weight:600;border:0;
 border-radius:9px;background:var(--accent);color:#fff;margin-top:.4rem}
.msg{color:var(--mut);font-size:.9rem}
.hint{color:var(--mut);font-size:.82rem;margin-top:1.6rem}
</style></head><body>%(body)s</body></html>"""

# Earthshine is carried in tenths of a percent, so it needs its own formatting
_LIVE_PERMILLE = (" oninput=\"this.parentNode.querySelector('output')"
                  ".textContent=this.value=='0'?'off':(this.value/10)+' %'\"")

# Plain number, no unit
_LIVE_PLAIN = (" oninput=\"this.parentNode.querySelector('output')"
               ".textContent=this.value\"")
