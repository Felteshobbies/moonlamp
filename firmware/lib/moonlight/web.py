"""Small HTTP server: setup portal and control page.

Non-blocking -- `poll()` is called from the main loop and returns
immediately when nothing is pending, so the frame rate stays constant
while someone is using the page.

It never waits for one client. Chrome and Edge open several connections at
once and leave some of them idle for later. A server that sits in recv() on
one of those stops accepting, the small queue of waiting connections fills,
and lwIP answers every further one with a reset -- ERR_CONNECTION_ABORTED in
the browser. So all connections are held open side by side, each is fed what
has arrived so far, and a request is answered as soon as it is complete,
whichever socket it came on.
"""

import socket
import time

try:
    import ujson as json
except ImportError:
    import json

try:
    import errno
    _AGAIN = (errno.EAGAIN, getattr(errno, "EWOULDBLOCK", errno.EAGAIN))
except ImportError:
    _AGAIN = (11,)

try:
    _BLOCKING = BlockingIOError     # CPython; MicroPython raises plain OSError
except NameError:
    _BLOCKING = ()

from . import VERSION
from . import config as configmod
from . import programs
from . import render

MAX_REQUEST = 2048
MAX_CONNS = 4         # held open at once; beyond that the oldest idle one goes
IDLE_MS = 8000        # a request not complete by then is given up on
SEND_TIMEOUT = 3.0    # seconds; only while writing a response out


def _ticks_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def _ticks_diff(a, b):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(a, b)
    return a - b


def _collect():
    try:
        import gc
        gc.collect()
    except Exception:
        pass


def _would_block(exc):
    return isinstance(exc, _BLOCKING) or (bool(exc.args)
                                          and exc.args[0] in _AGAIN)


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


def request_state(raw):
    """True once `raw` holds a whole request, head and body.

    Browsers routinely send the head and the body of a POST in separate TCP
    segments. Answering on the head alone means the form arrives empty and
    nothing gets saved. So: wait for the end of the head, look at
    Content-Length, and wait for that many bytes of body as well.
    """
    sep = b"\r\n\r\n"
    if len(raw) > MAX_REQUEST * 4:
        return True
    if sep not in raw:
        return False
    head, _, body = raw.partition(sep)
    length = 0
    for h in head.split(b"\r\n")[1:]:
        if h.lower().startswith(b"content-length:"):
            try:
                length = int(h.split(b":", 1)[1].strip())
            except ValueError:
                length = 0
            break
    return len(body) >= min(length, MAX_REQUEST * 4)


class _Conn(object):
    def __init__(self, sock, now):
        self.sock = sock
        self.raw = b""
        self.since = now


class Server(object):
    def __init__(self, port=80):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", port))
        self.sock.listen(5)
        self.sock.setblocking(False)
        self.conns = []

    def _accept(self, now):
        """Take every waiting connection off the queue.

        Leaving them there is what got them reset: the queue is short, and a
        connection that does not fit is refused by the network stack, not by
        anything this code could answer.
        """
        while True:
            try:
                sock, _ = self.sock.accept()
            except OSError:
                return
            try:
                sock.setblocking(False)
            except Exception:
                _close(sock)
                continue
            if len(self.conns) >= MAX_CONNS:
                # Make room by dropping a connection that has sent nothing --
                # a browser's spare, opened in case it is needed. Closing one
                # of those costs nothing; the browser opens another.
                victim = None
                for c in self.conns:
                    if not c.raw:
                        victim = c
                        break
                self._drop(victim or self.conns[0])
            self.conns.append(_Conn(sock, now))

    def _drop(self, c):
        _close(c.sock)
        try:
            self.conns.remove(c)
        except ValueError:
            pass

    def poll(self, handler):
        """Feed every open connection and answer any request now complete.

        Returns True if a request was answered.
        """
        now = _ticks_ms()
        self._accept(now)
        served = False
        for c in list(self.conns):
            closed = False
            try:
                chunk = c.sock.recv(MAX_REQUEST)
                if chunk:
                    c.raw += chunk
                else:
                    closed = True           # the browser gave up on it
            except OSError as exc:
                if not _would_block(exc):
                    self._drop(c)
                    continue

            if request_state(c.raw):
                self._answer(c, handler)
                served = True
            elif closed or _ticks_diff(now, c.since) > IDLE_MS:
                # A head that arrived but whose body never did is still
                # answered, so the portal can say the form was lost.
                if b"\r\n\r\n" in c.raw:
                    self._answer(c, handler)
                    served = True
                else:
                    self._drop(c)
        return served

    def _answer(self, c, handler):
        conn = c.sock
        try:
            head, _, body = c.raw.partition(b"\r\n\r\n")
            line = head.split(b"\r\n", 1)[0].decode()
            parts = line.split(" ")
            path = parts[1] if len(parts) > 1 else "/"
            query = {}
            if "?" in path:
                path, qs = path.split("?", 1)
                query = parse_query(qs)
            if body:
                query.update(parse_query(body.decode()))
            # The page is built from many short strings. Collecting first
            # gives it a tidy heap to be built in, instead of whatever the
            # frame loop left behind.
            _collect()
            try:
                status, ctype, payload = handler(path, query)
            except Exception as exc:
                # Say so in the browser, not just on the REPL: an empty reply
                # leaves whoever is looking at the page with nothing to go on.
                print("HTTP error in handler:", exc)
                status, ctype = "500 Internal Server Error", "text/plain"
                payload = "Moon lamp: %s: %s" % (type(exc).__name__, exc)
            # A page may come as a list of pieces; each is encoded and sent on
            # its own, so no block the size of the whole page is ever needed.
            if not isinstance(payload, (list, tuple)):
                payload = [payload]
            pieces = [p.encode() if isinstance(p, str) else p for p in payload]
            payload = None
            header = ("HTTP/1.0 %s\r\nContent-Type: %s\r\n"
                      "Content-Length: %d\r\n"
                      "Cache-Control: no-store\r\nConnection: close\r\n\r\n"
                      % (status, ctype, sum(len(p) for p in pieces)))
            # Waiting is fine here: the browser asked and is reading. A
            # non-blocking send would stop at the edge of lwIP's send buffer,
            # well short of the control page.
            conn.settimeout(SEND_TIMEOUT)
            # Bytes, not str: MicroPython accepts str, CPython does not --
            # without that difference the bug only shows up on the device.
            _send_all(conn, header.encode())
            for p in pieces:
                _send_all(conn, p)
            # Anything still unread when the socket closes makes lwIP send a
            # reset instead of a FIN, and a reset throws away the part of the
            # page that is still in flight.
            conn.setblocking(False)
            for _ in range(4):
                try:
                    if not conn.recv(MAX_REQUEST):
                        break
                except OSError:
                    break
        except Exception as exc:
            # The REPL is the only place to see anything on the device
            print("HTTP error:", exc)
        finally:
            self._drop(c)

    def close(self):
        for c in list(self.conns):
            self._drop(c)
        _close(self.sock)


def _close(sock):
    try:
        sock.close()
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
    ("led_offset", "Angle of pixel 0 (deg: 90 = top, 0 = right, 270 = bottom)", "text"),
)


def portal_page(cfg, message=""):
    rows = []
    for key, label, kind in PORTAL_FIELDS:
        val = "" if kind == "password" else str(cfg.get(key, ""))
        rows.append("<label>%s<input name='%s' type='%s' value='%s'></label>"
                    % (label, key, kind, val))
    return _page("Moon lamp setup", [
                 "<h1>Moon lamp setup</h1>"
                 "%s<form method='post' action='/save'>%s"
                 "<button type='submit'>Save and restart</button>"
                 "</form>"
                 "<p class='hint'>Wi-Fi names are case sensitive. The location is "
                 "only needed for the <b>Real moon</b> program. The angle of "
                 "pixel&nbsp;0 can also be set on the device: press and hold "
                 "the program button.</p>"
                 % ("<p class='msg'>%s</p>" % message if message else "",
                    "".join(rows))])


DESCRIPTIONS = (
    "Every mode at high speed, a whole month in a minute. Needs neither network nor clock.",
    "The current moon phase, visible around the clock.",
    "Like P1, but only while the moon is actually up. Brightness and colour follow its altitude.",
    "Full moon with a slowly drifting tint. White still carries it, so the disc stays a moon.",
    "The dimmest possible warm white across the whole ring.",
    "Phase and colour by hand: four channel sliders and an illuminated fraction.",
    "The whole colour wheel at full saturation, one turn every seven minutes.",
    "The entire spectrum around the ring at once, turning. Everything the strip can do.",
)


# One-click channel mixes for the manual mode, as (label, (r, g, b, w)) in
# percent. They exist because four independent sliders starting at "white only"
# give no hint that White has to come down before any colour is visible.
MANUAL_PRESETS = (
    ("White", (0, 0, 0, 100)),
    ("Warm", (100, 30, 0, 45)),
    ("Red", (100, 0, 0, 0)),
    ("Amber", (100, 45, 0, 0)),
    ("Green", (0, 100, 0, 0)),
    ("Cyan", (0, 100, 100, 0)),
    ("Blue", (0, 0, 100, 0)),
    ("Magenta", (100, 0, 100, 0)),
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
    m_rgbw = [int(manual.get(k, 1.0 if k == "w" else 0.0) * 100)
              for k in ("r", "g", "b", "w")]
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

    channels = ""
    for name, label, value in zip(("r", "g", "b", "w"),
                                  ("Red", "Green", "Blue", "White"),
                                  m_rgbw):
        channels += ("<label>%s <output>%d&nbsp;%%</output>"
                     "<input name='%s' type='range' min='0' max='100' "
                     "value='%d'%s></label>" % (label, value, name,
                                                value, _LIVE))

    presets = ""
    for label, mix in MANUAL_PRESETS:
        presets += ("<a class='chip' href='/set?program=5&r=%d&g=%d&b=%d&w=%d'>"
                    "%s</a>" % (mix[0], mix[1], mix[2], mix[3], label))
    out.append("<h2>Manual &mdash; switches to P5</h2>"
               "<div class='chips'>%s</div>" % presets)

    out.append(
               "<form action='/set'>"
               "<input type='hidden' name='program' value='5'>"
               "<label>Moon phase <output>%d&nbsp;%%</output>"
               "<input name='illum' type='range' min='0' max='100' value='%d'%s>"
               "</label>"
               "<label>Direction<select name='waxing'>"
               "<option value='1'%s>waxing &ndash; lit from the right</option>"
               "<option value='0'%s>waning &ndash; lit from the left</option>"
               "</select></label>"
               "%s"
               "<button type='submit'>Apply</button></form>"
               "<p class='hint'>0&nbsp;%% is new moon, 100&nbsp;%% is full. "
               "Overall brightness comes from the steps above, so the sliders "
               "only set the mix between channels.</p>"
               "<p class='hint'><b>White is a separate LED</b>, and on an "
               "SK6812 it is about as bright as red, green and blue together. "
               "With White at 100&nbsp;%% the colours barely show &mdash; pull "
               "it down to see them. The buttons above do that for you.</p>"
               % (m_illum, m_illum, _LIVE, "" if not waxing else " selected",
                  " selected" if not waxing else "", channels))

    # --- Ring geometry. Stated as a clock position, because that is how anyone
    # looking at a lamp on a wall would describe a point on its rim. Degrees
    # remain the stored form and stay available for a strip that did not happen
    # to start on an hour.
    clock = render.angle_to_clock(offset)
    named = {12: " &ndash; top", 3: " &ndash; right",
             6: " &ndash; bottom", 9: " &ndash; left"}
    hours = ""
    for h in [12] + list(range(1, 12)):
        hours += ("<option value='%d'%s>%d o&rsquo;clock%s</option>"
                  % (h, " selected" if h == clock else "", h,
                     named.get(h, "")))

    exact = render.on_the_hour(offset)
    out.append("<h2>Ring</h2>"
               "<form action='/set'>"
               "<label>Pixel 0 sits at<select name='led_clock'>%s</select>"
               "</label>"
               "<label>Counting from there<select name='led_clockwise'>"
               "<option value='0'%s>counter-clockwise</option>"
               "<option value='1'%s>clockwise</option>"
               "</select></label>"
               "<button type='submit'>Apply</button></form>"
               "<div class='chips'>"
               "<a class='chip' href='/set?nudge=-1'>&minus;1 LED</a>"
               "<a class='chip' href='/set?nudge=1'>+1 LED</a>"
               "<a class='chip' href='/calibrate'>Find pixel 0</a></div>"
               "<p class='hint'>Look at the lamp from the front and read the "
               "rim like a clock face: 12 at the top, 3 on the right, 6 at the "
               "bottom, 9 on the left. Set where the <em>first</em> LED of the "
               "strip sits, then whether the numbers run clockwise or "
               "counter-clockwise from it &mdash; follow the arrow printed on "
               "the strip.</p>"
               "<p class='hint'>Not sure which LED is the first one? Press "
               "&ldquo;Find pixel&nbsp;0&rdquo;. One LED lights: the one this "
               "setting believes is at <b>6 o&rsquo;clock</b>. Nudge by "
               "&plusmn;1&nbsp;LED until the lit one really is at the bottom "
               "&mdash; then the setting is right, and you never had to count "
               "a single LED. Press the program button on the device, or pick "
               "a program here, to leave that mode again.</p>"
               "<p class='hint'>Currently %d&deg;%s. One LED is %.1f&deg; on "
               "this ring.</p>"
               % (hours, "" if cw else " selected", " selected" if cw else "",
                  int(offset),
                  "" if exact else ", between two clock positions",
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

    return _page("Moon lamp", out,
                 "<meta http-equiv='refresh' content='30'>")


def _page(title, body, head=""):
    """The whole page as a list of pieces, each small enough to allocate."""
    parts = [_PAGE_TOP % (head, title), _STYLE]
    parts.extend(body)
    parts.append("</body></html>")
    return parts


# Shows the slider value while dragging, without needing a round trip
_LIVE = (" oninput=\"this.parentNode.querySelector('output').textContent="
         "this.value+(this.name=='led_offset'?'\\u00b0':' %')\"")


# The page goes out in pieces rather than as one string. Joined, the control
# page is some 11 kB, and encoding it needs another block that size; on a
# Pico W whose heap the Wi-Fi stack has cut into pieces, a block that large is
# sometimes not there -- MemoryError, and the page did not load.
_PAGE_TOP = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
%s<title>%s</title>"""

# Sent as it is, never formatted
_STYLE = """<style>
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
input,select{width:100%;padding:.5rem;font:inherit;margin-top:.3rem;
 border:1px solid var(--line);border-radius:8px;background:var(--card);
 color:inherit}
input[type=range]{padding:0;border:0;background:transparent;accent-color:var(--accent)}
button{width:100%;padding:.75rem;font:inherit;font-weight:600;border:0;
 border-radius:9px;background:var(--accent);color:#fff;margin-top:.4rem}
.msg{color:var(--mut);font-size:.9rem}
.hint{color:var(--mut);font-size:.82rem;margin-top:1.6rem}
</style></head><body>"""

# Earthshine is carried in tenths of a percent, so it needs its own formatting
_LIVE_PERMILLE = (" oninput=\"this.parentNode.querySelector('output')"
                  ".textContent=this.value=='0'?'off':(this.value/10)+' %'\"")

# Plain number, no unit
_LIVE_PLAIN = (" oninput=\"this.parentNode.querySelector('output')"
               ".textContent=this.value\"")
