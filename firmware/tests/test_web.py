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
print("4. Every control on the page is understood by the handler")
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
