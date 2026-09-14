"""The window.

tkinter, because it ships with Python and therefore adds nothing to the size
of a frozen build, and because a four-step wizard does not need more.

Threading rule, and it is the only one that matters here: tkinter must be
touched from the main thread alone. Serial work takes seconds and would freeze
the window, so it runs in a worker that pushes messages into a queue; the main
thread drains that queue from an `after` timer. No widget is ever touched from
the worker.
"""

import queue
import threading
import webbrowser

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:                                   # pragma: no cover
    tk = None

from . import device
from . import install
from . import releases

PAD = {"padx": 12, "pady": 6}

CLOCK_CHOICES = [
    ("12 o'clock  (top)", 12),
    ("1 o'clock", 1), ("2 o'clock", 2),
    ("3 o'clock  (right)", 3),
    ("4 o'clock", 4), ("5 o'clock", 5),
    ("6 o'clock  (bottom)", 6),
    ("7 o'clock", 7), ("8 o'clock", 8),
    ("9 o'clock  (left)", 9),
    ("10 o'clock", 10), ("11 o'clock", 11),
]


class Worker(object):
    """Runs one job off the UI thread and reports back through a queue."""

    def __init__(self, widget):
        self.widget = widget
        self.q = queue.Queue()
        self.busy = False
        self._drain()

    def run(self, fn, done=None):
        if self.busy:
            return False
        self.busy = True

        def body():
            try:
                result = fn(self.report)
                self.q.put(("done", result, None))
            except Exception as exc:                  # noqa: BLE001
                self.q.put(("done", None, exc))

        self._done_cb = done
        threading.Thread(target=body, daemon=True).start()
        return True

    def report(self, stage, done, total, text):
        """Called from the worker thread -- queue only, no widgets."""
        self.q.put(("progress", (stage, done, total, text), None))

    def _drain(self):
        try:
            while True:
                kind, payload, exc = self.q.get_nowait()
                if kind == "progress":
                    self.on_progress(*payload)
                else:
                    self.busy = False
                    cb, self._done_cb = getattr(self, "_done_cb", None), None
                    if cb:
                        cb(payload, exc)
        except queue.Empty:
            pass
        self.widget.after(80, self._drain)

    def on_progress(self, stage, done, total, text):
        pass


class App(object):
    def __init__(self, root):
        self.root = root
        root.title("Moon Lamp Installer")
        root.minsize(560, 460)

        self.port = None
        self.state = {}
        self.files = None
        self.chosen = None
        # What the lamp actually holds, as last read. Empty means "unknown",
        # which is treated as "write nothing you were not asked to write".
        self.loaded = {}

        head = ttk.Frame(root)
        head.pack(fill="x", **PAD)
        ttk.Label(head, text="Moon Lamp", font=("", 17, "bold")).pack(anchor="w")
        self.sub = ttk.Label(head, text="Firmware installer and updater",
                             foreground="#666")
        self.sub.pack(anchor="w")

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, **PAD)
        self.tab_board = ttk.Frame(self.nb)
        self.tab_fw = ttk.Frame(self.nb)
        self.tab_set = ttk.Frame(self.nb)
        self.nb.add(self.tab_board, text="1 · Board")
        self.nb.add(self.tab_fw, text="2 · Firmware")
        self.nb.add(self.tab_set, text="3 · Settings")

        self._build_board()
        self._build_firmware()
        self._build_settings()

        bar = ttk.Frame(root)
        bar.pack(fill="x", **PAD)
        self.progress = ttk.Progressbar(bar, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.status = ttk.Label(bar, text="Ready.", foreground="#666")
        self.status.pack(anchor="w", pady=(4, 0))

        self.worker = Worker(root)
        self.worker.on_progress = self._on_progress

        self.refresh()

    # ------------------------------------------------------------ plumbing

    def _on_progress(self, stage, done, total, text):
        if done is not None and total:
            self.progress.configure(value=100.0 * done / total)
        self.status.configure(text=text)

    def _busy(self, text):
        self.status.configure(text=text)
        self.progress.configure(value=0)

    def _fail(self, exc):
        self.status.configure(text=str(exc))
        messagebox.showerror("Moon Lamp Installer", str(exc))

    # --------------------------------------------------------------- board

    def _build_board(self):
        f = self.tab_board
        self.board_text = tk.Text(f, height=9, wrap="word",
                                  relief="flat", background="#f4f4f6")
        self.board_text.pack(fill="both", expand=True, **PAD)
        self.board_text.configure(state="disabled")

        row = ttk.Frame(f)
        row.pack(fill="x", **PAD)
        ttk.Button(row, text="Scan again",
                   command=self.refresh).pack(side="left")
        self.btn_mp = ttk.Button(row, text="Install MicroPython",
                                 command=self.do_micropython)
        self.btn_mp.pack(side="left", padx=8)

    def _set_board_text(self, lines):
        self.board_text.configure(state="normal")
        self.board_text.delete("1.0", "end")
        self.board_text.insert("1.0", "\n".join(lines))
        self.board_text.configure(state="disabled")

    def refresh(self):
        self._busy("Looking for a board ...")

        def job(report):
            return install.survey(report)

        def done(state, exc):
            if exc:
                return self._fail(exc)
            self.state = state
            self.port = state["repl_port"]
            lines = []
            for port, pid, what in state["boards"]:
                lines.append("%-10s  USB 2E8A:%04X   %s" % (port, pid, what))
            if state["bootsel_drive"]:
                info = state["board_info"]
                lines.append("%-10s  BOOTSEL drive, board %s"
                             % (state["bootsel_drive"],
                                info.get("Board-ID", "unknown")))
            if not lines:
                lines = [
                    "No Raspberry Pi board found on USB.",
                    "",
                    "If one is plugged in, check the cable: charging cables "
                    "and data cables look identical, and a charging cable "
                    "carries no data at all.",
                ]
            if state.get("micropython"):
                lines += ["", "MicroPython : %s" % state["micropython"]]
            if state.get("firmware"):
                lines.append("Firmware    : %s" % state["firmware"])
            elif state["repl_port"]:
                lines.append("Firmware    : not installed yet")

            self._set_board_text(lines)
            ready = bool(state["repl_port"])
            self.btn_mp.configure(
                state="disabled" if ready else "normal",
                text="MicroPython is installed" if ready
                else "Install MicroPython")
            self.status.configure(
                text="Board ready." if ready
                else "MicroPython is needed before anything else.")
            if ready:
                self.nb.select(self.tab_fw)
                self.fw_refresh()
                # Read the existing configuration straight away, so the
                # settings form can never show defaults over real values
                if state.get("firmware"):
                    self.load_settings()

        self.worker.run(job, done)

    def do_micropython(self):
        if not device.find_bootsel_drive():
            messagebox.showinfo(
                "Put the board into BOOTSEL mode",
                "1. Unplug the Pico\n"
                "2. Hold the BOOTSEL button down\n"
                "3. Plug it back in while still holding\n"
                "4. Release the button\n\n"
                "A drive called RPI-RP2 appears. Press OK, then wait.")
        self._busy("Waiting for a board in BOOTSEL mode ...")

        def job(report):
            return install.flash_micropython(report=report)

        def done(port, exc):
            if exc:
                return self._fail(exc)
            self.port = port
            self.refresh()

        self.worker.run(job, done)

    # ------------------------------------------------------------ firmware

    def _build_firmware(self):
        f = self.tab_fw
        self.fw_label = ttk.Label(f, text="", justify="left")
        self.fw_label.pack(anchor="w", **PAD)

        self.fw_source = tk.StringVar(value="bundled")
        ttk.Radiobutton(f, text="Use the version bundled with this installer",
                        variable=self.fw_source,
                        value="bundled").pack(anchor="w", padx=12)
        self.rb_online = ttk.Radiobutton(
            f, text="Download the newest release from GitHub",
            variable=self.fw_source, value="github", state="disabled")
        self.rb_online.pack(anchor="w", padx=12)

        self.notes = tk.Text(f, height=8, wrap="word", relief="flat",
                             background="#f4f4f6")
        self.notes.pack(fill="both", expand=True, **PAD)
        self.notes.configure(state="disabled")

        row = ttk.Frame(f)
        row.pack(fill="x", **PAD)
        ttk.Button(row, text="Check GitHub",
                   command=self.fw_check).pack(side="left")
        ttk.Button(row, text="Install firmware",
                   command=self.do_install).pack(side="left", padx=8)

    def fw_refresh(self):
        have = self.state.get("firmware")
        self.fw_label.configure(
            text="On the board: %s\nIn this installer: %s"
                 % (have or "nothing yet", releases.bundled_version()))

    def fw_check(self):
        self._busy("Asking GitHub ...")

        def job(report):
            return install.check_for_update(self.state.get("firmware"), False)

        def done(result, exc):
            if exc:
                return self._fail(exc)
            rel, why = result
            self.chosen = rel
            self.notes.configure(state="normal")
            self.notes.delete("1.0", "end")
            if rel and rel.get("asset"):
                self.rb_online.configure(state="normal")
                self.fw_source.set("github")
                self.notes.insert("1.0", "%s\n\n%s"
                                  % (rel.get("name", ""), rel.get("notes", "")))
                self.status.configure(text="Version %s is available."
                                           % rel["version"])
            else:
                self.notes.insert("1.0", why)
                self.status.configure(text=why)
            self.notes.configure(state="disabled")

        self.worker.run(job, done)

    def do_install(self):
        if not self.port:
            return messagebox.showwarning(
                "Moon Lamp Installer", "No board with MicroPython found.")
        online = self.fw_source.get() == "github" and self.chosen
        self._busy("Writing the firmware ...")

        def job(report):
            files = (install.fetch_firmware(self.chosen) if online
                     else releases.bundled_firmware())
            return install.install_firmware(self.port, files, report)

        def done(version, exc):
            if exc:
                return self._fail(exc)
            self.state["firmware"] = version
            self.fw_refresh()
            self.status.configure(text="Firmware %s installed." % version)
            self.nb.select(self.tab_set)
            self.load_settings()

        self.worker.run(job, done)

    # ------------------------------------------------------------ settings

    def _build_settings(self):
        f = self.tab_set
        grid = ttk.Frame(f)
        grid.pack(fill="x", **PAD)
        self.vars = {}
        rows = [
            ("ssid", "Wi-Fi network", ""),
            ("password", "Password", ""),
            ("hostname", "Hostname", "moonlamp"),
            ("latitude", "Latitude (north positive)", "51.2"),
            ("longitude", "Longitude (east positive)", "6.8"),
            ("utc_offset", "Time zone (hours from UTC)", "1"),
            ("led_count", "Number of LEDs", "40"),
        ]
        for i, (key, label, default) in enumerate(rows):
            ttk.Label(grid, text=label).grid(row=i, column=0, sticky="w",
                                             pady=3)
            var = tk.StringVar(value=default)
            show = "*" if key == "password" else ""
            ttk.Entry(grid, textvariable=var, width=28, show=show).grid(
                row=i, column=1, sticky="ew", pady=3, padx=(10, 0))
            self.vars[key] = var
        grid.columnconfigure(1, weight=1)

        i = len(rows)
        ttk.Label(grid, text="Pixel 0 sits at").grid(row=i, column=0,
                                                     sticky="w", pady=3)
        self.clock = ttk.Combobox(grid, width=26, state="readonly",
                                  values=[c[0] for c in CLOCK_CHOICES])
        self.clock.current(6)               # 6 o'clock, the default
        self.clock.grid(row=i, column=1, sticky="ew", pady=3, padx=(10, 0))

        self.origin = ttk.Label(f, wraplength=520, foreground="#666",
                                justify="left", text="")
        self.origin.pack(anchor="w", **PAD)

        ttk.Label(f, wraplength=520, foreground="#666", justify="left",
                  text="Read the rim like a clock face, looking at the lamp "
                       "from the front. Leave the password blank to keep the "
                       "one already stored. Leave Wi-Fi empty altogether to "
                       "set the lamp up from a phone instead: it opens a "
                       "network called 'Moon Lamp Setup'.").pack(anchor="w",
                                                                 **PAD)

        row = ttk.Frame(f)
        row.pack(fill="x", **PAD)
        ttk.Button(row, text="Save and restart",
                   command=self.do_settings).pack(side="left")
        ttk.Button(row, text="Reload from lamp",
                   command=self.load_settings).pack(side="left", padx=8)
        ttk.Button(row, text="Find the lamp",
                   command=self.do_find).pack(side="left", padx=8)

    def load_settings(self):
        """Read what is on the lamp and show it, before anything is written.

        The form starts out holding sensible defaults, and defaults are exactly
        what must not reach a lamp that is already configured. So: read first,
        remember what came back, and on save send only what the user actually
        changed.
        """
        if not self.port:
            return

        def job(report):
            return install.read_config(self.port)

        def done(cfg, exc):
            if exc:
                self.loaded = {}
                self.origin.configure(
                    text="Could not read the current settings from the lamp. "
                         "Saving now would write every field as shown.",
                    foreground="#a33")
                return
            self.loaded = dict(cfg or {})
            for key, var in self.vars.items():
                if cfg.get(key) not in (None, ""):
                    var.set(str(cfg[key]))
            offset = cfg.get("led_offset")
            if offset is not None:
                hour = install.angle_to_clock(offset)
                for idx, (_, h) in enumerate(CLOCK_CHOICES):
                    if h == hour:
                        self.clock.current(idx)
                        break
            if cfg:
                self.origin.configure(
                    text="Showing the settings currently on the lamp. Only "
                         "what you change is written back.",
                    foreground="#666")
            else:
                self.origin.configure(
                    text="The lamp has no settings yet, so these are defaults.",
                    foreground="#666")

        self.worker.run(job, done)

    def do_settings(self):
        if not self.port:
            return messagebox.showwarning(
                "Moon Lamp Installer", "No board found.")
        settings = {}
        for key, var in self.vars.items():
            val = var.get().strip()
            if val == "":
                # Blank never means "erase this". For the password that is the
                # important case: the field starts empty, and a stray save
                # would otherwise take the lamp off the network.
                continue
            if key in ("latitude", "longitude"):
                try:
                    val = float(val)
                except ValueError:
                    return messagebox.showwarning(
                        "Moon Lamp Installer",
                        "%s must be a number, for example 51.2" % key)
            elif key in ("utc_offset", "led_count"):
                try:
                    val = int(val)
                except ValueError:
                    return messagebox.showwarning(
                        "Moon Lamp Installer", "%s must be a whole number"
                                               % key)
            settings[key] = val
        hour = CLOCK_CHOICES[self.clock.current()][1]
        settings["led_offset"] = install.clock_to_angle(hour)

        # Send only what actually differs from what the lamp already holds.
        # The form is pre-filled with defaults, and defaults are precisely what
        # must not reach a configured lamp just because someone pressed Save.
        settings = install.changed_settings(settings, self.loaded)
        if not settings:
            self.status.configure(text="Nothing changed, so nothing written.")
            return
        changed = ", ".join(sorted(settings))
        if self.loaded and not messagebox.askyesno(
                "Moon Lamp Installer",
                "Write these settings and restart the lamp?\n\n%s\n\n"
                "Everything else stays as it is." % changed):
            return

        self._busy("Writing the settings ...")

        def job(report):
            install.write_config(self.port, settings, report=report)
            install.restart(self.port, report)
            return True

        def done(_, exc):
            if exc:
                return self._fail(exc)
            self.status.configure(
                text="Saved. The lamp is restarting -- give it a few seconds, "
                     "then press 'Find the lamp'.")

        self.worker.run(job, done)

    def do_find(self):
        """Ask the running lamp for its address.

        This interrupts the program on the device and restarts it afterwards,
        which is a brief flicker on the ring and the only way to ask over USB.
        """
        if not self.port:
            return
        self._busy("Asking the lamp for its address ...")

        def job(report):
            pico = device.Pico(self.port)
            try:
                pico.enter_raw()
                out = pico.exec_(
                    "import network\n"
                    "w=network.WLAN(network.STA_IF)\n"
                    "print(w.ifconfig()[0] if w.isconnected() else '')")
                pico.reset()
                return out.strip()
            finally:
                pico.close()

        def done(ip, exc):
            if exc:
                return self._fail(exc)
            if not ip:
                self.status.configure(
                    text="The lamp is not on the network yet. Check the Wi-Fi "
                         "name and password -- they are case sensitive.")
                return
            url = "http://%s/" % ip
            self.status.configure(text="The lamp is at %s" % url)
            if messagebox.askyesno("Moon Lamp Installer",
                                   "The lamp is at %s\n\nOpen it now?" % url):
                webbrowser.open(url)

        self.worker.run(job, done)


def main():
    if tk is None:
        raise SystemExit("tkinter is not available; use the console instead: "
                         "moonlamp-installer --help")
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()
    return 0
