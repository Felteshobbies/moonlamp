"""Three buttons, debounced, with long-press detection.

Wired to ground, internal pull-ups. Polled from the main loop -- no interrupt
needed: at 60 Hz the resolution is fine enough, and there are no races with the
Wi-Fi stack.
"""

try:
    from machine import Pin
    HAVE_PIN = True
except ImportError:
    HAVE_PIN = False

DEBOUNCE_MS = 25
LONG_MS = 900

SHORT = 1
LONG = 2


class Button(object):
    def __init__(self, pin_no):
        self.pin = Pin(pin_no, Pin.IN, Pin.PULL_UP) if HAVE_PIN else None
        self.down_at = None
        self.stable = 1
        self.changed_at = 0
        self.long_sent = False

    def _raw(self):
        return self.pin.value() if self.pin is not None else 1

    def poll(self, now_ms):
        """Returns SHORT, LONG or None.

        LONG fires while the button is still held, so the feedback is immediate;
        the following release then no longer produces a SHORT.
        """
        raw = self._raw()
        if raw != self.stable:
            if now_ms - self.changed_at >= DEBOUNCE_MS:
                self.stable = raw
                self.changed_at = now_ms
                if raw == 0:
                    self.down_at = now_ms
                    self.long_sent = False
                else:
                    was = self.down_at
                    self.down_at = None
                    if was is not None and not self.long_sent:
                        return SHORT
        else:
            self.changed_at = now_ms

        if (self.down_at is not None and not self.long_sent
                and now_ms - self.down_at >= LONG_MS):
            self.long_sent = True
            return LONG
        return None


class Panel(object):
    """Program, brighter, dimmer."""

    def __init__(self, cfg):
        self.program = Button(cfg["button_program"])
        self.up = Button(cfg["button_up"])
        self.down = Button(cfg["button_down"])

    def poll(self, now_ms):
        """Returns a list of events as (name, kind)."""
        events = []
        for name, btn in (("program", self.program), ("up", self.up),
                          ("down", self.down)):
            ev = btn.poll(now_ms)
            if ev is not None:
                events.append((name, ev))
        return events
