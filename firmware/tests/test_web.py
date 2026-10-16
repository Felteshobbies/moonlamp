"""Check that the HTTP server reads a split request completely.

The bug this test pins down: browsers routinely send the head and the body
of a POST in separate TCP segments. A single recv() then yields only the
head, the form arrives empty, and the setup portal silently saves nothing.

    python firmware/tests/test_web.py
"""

import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "lib"))

from moonlight import web  # noqa: E402

FAILED = []


def check(name, got, want):
    ok = got == want
    print("  %-46s %s" % (name, "ok" if ok else "FAILED: %r != %r" % (got, want)))
    if not ok:
        FAILED.append(name)


def serve_once(server, seen, timeout=6.0):
    def handler(path, query):
        seen.append((path, dict(query)))
        return "200 OK", "text/html", "ok"
    t0 = time.time()
    while time.time() - t0 < timeout:
        if server.poll(handler) and seen:
            return True
        time.sleep(0.01)
    return False


def run(name, sender):
    server = web.Server(port=0)
    port = server.sock.getsockname()[1]
    seen = []
    th = threading.Thread(target=sender, args=(port,), daemon=True)
    th.start()
    ok = serve_once(server, seen)
    th.join(timeout=3.0)
    server.close()
    if not ok:
        print("  %-46s FAILED: no request was handled" % name)
        FAILED.append(name)
        return None
    return seen[0]


print("1. POST with the body in a second packet (the actual failure case)")
BODY = "ssid=Mein+WLAN&password=geheim%21&hostname=mondlampe&latitude=51.2"


def split_post(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    head = ("POST /save HTTP/1.1\r\nHost: 192.168.4.1\r\n"
            "Content-Type: application/x-www-form-urlencoded\r\n"
            "Content-Length: %d\r\n\r\n" % len(BODY))
    s.sendall(head.encode())
    time.sleep(0.25)              # body deliberately later
    s.sendall(BODY.encode())
    try:
        s.recv(4096)
    except OSError:
        pass
    s.close()


got = run("split POST", split_post)
if got:
    check("path", got[0], "/save")
    check("ssid containing a space", got[1].get("ssid"), "Mein WLAN")
    check("password percent-encoded", got[1].get("password"), "geheim!")
    check("number of fields", len(got[1]), 4)

print()
print("2. POST in one piece")


def single_post(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(("POST /save HTTP/1.1\r\nHost: x\r\nContent-Length: %d\r\n\r\n%s"
               % (len(BODY), BODY)).encode())
    try:
        s.recv(4096)
    except OSError:
        pass
    s.close()


got = run("single-packet POST", single_post)
if got:
    check("ssid", got[1].get("ssid"), "Mein WLAN")

print()
print("3. GET with a query string")


def get_query(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"GET /set?program=2&brightness=4 HTTP/1.1\r\nHost: x\r\n\r\n")
    try:
        s.recv(4096)
    except OSError:
        pass
    s.close()


got = run("GET with query", get_query)
if got:
    check("path without the query", got[0], "/set")
    check("program", got[1].get("program"), "2")
    check("brightness", got[1].get("brightness"), "4")

print()
print("4. Idle spare connections, the way Chrome opens them")
# The failure seen in the field: Chrome on Windows opens spare connections and
# sends nothing on them. The old server sat in recv() on such a spare for
# three seconds, the accept queue overflowed meanwhile, and the browser got
# ERR_CONNECTION_ABORTED for the real request.


def _poll_until(server, handler, done, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout and not done():
        server.poll(handler)
        time.sleep(0.005)
    return time.time() - t0


def _fetch(port, path, out, key):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(("GET %s HTTP/1.1\r\nHost: x\r\n\r\n" % path).encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        out[key] = data
    except OSError as exc:
        out[key] = exc


def _ok_handler(path, query):
    return "200 OK", "text/html", "x" * 20000     # larger than one send buffer


server = web.Server(port=0)
port = server.sock.getsockname()[1]
spares = [socket.create_connection(("127.0.0.1", port), timeout=5)
          for _ in range(3)]
for _ in range(5):
    server.poll(_ok_handler)        # the server has now taken the spares on
out = {}
th = threading.Thread(target=_fetch, args=(port, "/", out, "a"), daemon=True)
th.start()
took = _poll_until(server, _ok_handler, lambda: "a" in out, 5.0)
th.join(timeout=1.0)
got = out.get("a")
check("request behind idle spares answered",
      isinstance(got, bytes) and got.startswith(b"HTTP/1.0 200"), True)
check("whole page arrived", isinstance(got, bytes) and got.endswith(b"x" * 100),
      True)
check("without waiting for the spares", took < 1.0, True)
print("     answered after %.2f s" % took)
for s in spares:
    s.close()
server.close()

print()
print("5. More connections at once than the server holds")
server = web.Server(port=0)
port = server.sock.getsockname()[1]
spares = []
for _ in range(web.MAX_CONNS + 3):
    spares.append(socket.create_connection(("127.0.0.1", port), timeout=5))
    server.poll(_ok_handler)        # the main loop polls hundreds of times a second
out = {}
threads = []
for i in range(3):
    th = threading.Thread(target=_fetch, args=(port, "/p%d" % i, out, i),
                          daemon=True)
    th.start()
    threads.append(th)
_poll_until(server, _ok_handler, lambda: len(out) == 3, 6.0)
for th in threads:
    th.join(timeout=1.0)
answered = sum(1 for v in out.values()
               if isinstance(v, bytes) and v.startswith(b"HTTP/1.0 200"))
check("all three real requests answered", answered, 3)
check("never more open than MAX_CONNS", len(server.conns) <= web.MAX_CONNS,
      True)
for s in spares:
    s.close()
_poll_until(server, _ok_handler, lambda: not server.conns, 2.0)
check("closed spares are let go", len(server.conns), 0)
server.close()

print()
print("6. A failing handler still answers")


def _broken(path, query):
    raise ValueError("no such thing")


server = web.Server(port=0)
port = server.sock.getsockname()[1]
out = {}
th = threading.Thread(target=_fetch, args=(port, "/", out, "a"), daemon=True)
th.start()
_poll_until(server, _broken, lambda: "a" in out, 5.0)
th.join(timeout=1.0)
got = out.get("a")
check("500 instead of an empty reply",
      isinstance(got, bytes) and got.startswith(b"HTTP/1.0 500"), True)
check("the reason is shown", isinstance(got, bytes) and b"no such thing" in got,
      True)
server.close()

print()
print("7. Every control on the page is understood by the handler")
# The classic failure when adding settings: the form field is named one thing
# and main.py reads another. Nothing errors, the setting simply does nothing.
import re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "lib"))
from moonlight import config as configmod  # noqa: E402
from moonlight import web as webmod  # noqa: E402

cfg = configmod.load()
cfg.update({"program": 1, "brightness": 3, "led_count": 44,
            "led_offset": 180.0, "led_clockwise": False})
page = webmod.control_page(cfg, {"status": "", "facts": [],
                                 "manual": {"illum": 0.5, "waxing": True,
                                            "warmth": 0.0}})

names = set(re.findall(r"<(?:input|select)[^>]*name='([a-z_]+)'", page))
names |= set(re.findall(r"href='/set[?]([a-z_]+)=", page))
main_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "main.py"), encoding="utf-8").read()
# main.py reads some keys directly and others through a loop over a tuple of
# names, so look for the name as a literal anywhere in the handler
missing = sorted(n for n in names if '"%s"' % n not in main_src)
check("all form fields read by main.py", missing, [])
print("     fields on the page: %s" % ", ".join(sorted(names)))

# Links that must resolve to a route in the handler
routes = set(re.findall(r"href='(/[a-z]+)'", page))
missing_routes = sorted(r for r in routes
                        if 'path == "%s"' % r not in main_src)
check("all links have a route", missing_routes, [])
print("     routes on the page: %s" % ", ".join(sorted(routes)))

# The nudge step must be one LED pitch
pitch = 360.0 / cfg["led_count"]
check("one nudge is one LED pitch",
      round(((cfg["led_offset"] + pitch) % 360.0) - cfg["led_offset"], 4),
      round(pitch, 4))

print()
if FAILED:
    print("FAILED: %s" % ", ".join(FAILED))
    raise SystemExit(1)
print("All checks passed.")
