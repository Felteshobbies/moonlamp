"""SK6812 RGBW driver via PIO. MicroPython on RP2040/RP2350 only.

The PIO state machine generates the single-wire protocol timing exactly and
without jitter, no matter what the CPU is doing.

SK6812 RGBW data format: 32 bits per pixel, MSB first, order G R B W -- the
same order Adafruit's `NEO_GRBW` produces.

Two output paths:

* blocking -- the CPU pushes the frame into the PIO FIFO itself. Simple, always
  available, but it occupies the CPU for the whole 1.5 ms and must not be
  interrupted for longer than the FIFO can bridge, so it runs with interrupts
  disabled.
* dma -- a DMA channel feeds the FIFO on the PIO's request line. The CPU only
  starts the transfer. Nothing can starve the stream, and because the output
  costs no CPU time it can run fast enough for temporal dithering: several
  subframes per image, averaged by the eye, which buys about three extra bits
  exactly where they are needed -- at the lowest brightness steps.

The DMA path is driven from the main loop via tick(), not from an interrupt.
That avoids touching DMA registers inside an ISR, and one loop iteration is
easily short enough to keep the subframes flowing.
"""

import array
import time

try:
    import machine
    import rp2
    HAVE_PIO = True
except ImportError:                     # keeps the file importable on a PC
    HAVE_PIO = False

from . import dither

# SK6812 bit timing, 12 PIO cycles per bit at 10 MHz = 1.20 us:
#   T0H 0.30  T0L 0.90   T1H 0.60  T1L 0.60   (datasheet, tolerance +/- 0.15)
# The obvious shortcut is to reuse the WS2812B numbers, but the SK6812 wants a
# symmetric one bit. With T1H 0.875 and T1L 0.375 both halves sit outside the
# window, and the shortest pulse -- the 0.25 us high of a zero bit -- is the
# first thing a marginal driver loses.
PIO_FREQ = 10_000_000
T_LOW = 6                               # leading low, before the bit is known
T_HIGH = 3                              # high for a zero
T_EXTRA = 3                             # additional high for a one
RESET_US = 100                          # SK6812 latches after 80 us of idle

# Frames a picture has to hold still before the subframes are built for it.
# Long enough that a moving programme never pays the cost, short enough that a
# settled one gets the benefit within a blink.
SETTLE_FRAMES = 3

PIO0_BASE = 0x50200000
PIO_TXF0 = PIO0_BASE + 0x10


if HAVE_PIO:
    # JOIN_TX doubles the transmit FIFO from four words to eight. One word is
    # one pixel and takes 38.4 us to shift out, so the buffer grows from 154 us
    # to 307 us. That matters because the strip latches after 80 us of idle: if
    # the FIFO ever runs dry mid-frame, the remaining pixels are written to
    # LED 0 onwards and the first LEDs flash.
    @rp2.asm_pio(sideset_init=rp2.PIO.OUT_LOW, out_shiftdir=rp2.PIO.SHIFT_LEFT,
                 autopull=True, pull_thresh=32,
                 fifo_join=rp2.PIO.JOIN_TX)
    def _sk6812():
        # These must be literals: asm_pio() runs this body with its own
        # namespace, so module-level names are not visible in here. They have
        # to match T_HIGH / T_EXTRA / T_LOW above -- test_system.py parses this
        # function and compares, so the two cannot drift apart unnoticed.
        T1 = 3
        T2 = 3
        T3 = 6
        wrap_target()
        label("bitloop")
        out(x, 1)                   .side(0)    [T3 - 1]
        jmp(not_x, "do_zero")       .side(1)    [T1 - 1]
        jmp("bitloop")              .side(1)    [T2 - 1]
        label("do_zero")
        nop()                       .side(0)    [T2 - 1]
        wrap()


class Ring(object):
    """The LED ring. Takes 16-bit frames and shifts out 8 bits."""

    def __init__(self, pin, n_leds, state_machine=0, irq_safe=True,
                 temporal=False, n_subframes=8):
        self.n = n_leds
        self.irq_safe = irq_safe
        self.n_sub = max(1, int(n_subframes)) if temporal else 1
        self.bufs = [array.array("I", [0] * n_leds) for _ in range(self.n_sub)]
        self.buf = self.bufs[0]
        self.mode = "off"
        self.sm = None
        self.dma = None
        self._idx = 0
        self._free_at = 0
        self._want_temporal = bool(temporal)
        # How many of the buffers tick() is currently cycling. One while the
        # picture is moving, the full set once it has settled -- see _plan().
        self._active = 1
        self._prev = None
        self._stable = 0

        if not HAVE_PIO:
            return

        self.sm = rp2.StateMachine(state_machine, _sk6812, freq=PIO_FREQ,
                                   sideset_base=machine.Pin(pin))
        self.sm.active(1)
        self.mode = "blocking"

        if self._want_temporal:
            try:
                self._start_dma(state_machine)
                self.mode = "dma"
            except Exception as exc:
                # Never let this take the lamp down: fall back and say why
                print("LED: DMA unavailable (%s), staying on the blocking path"
                      % exc)
                self.dma = None
                self.n_sub = 1
                self.bufs = self.bufs[:1]
                self.buf = self.bufs[0]

    # ------------------------------------------------------------------ DMA

    def _start_dma(self, sm_index):
        """Set up one DMA channel feeding the PIO transmit FIFO.

        MicroPython does not expose the FIFO address or the request line
        number, so both are written out here. For PIO0 the request number of
        the transmit FIFO happens to equal the state machine index.
        """
        dma = rp2.DMA()
        ctrl = dma.pack_ctrl(size=2, inc_read=True, inc_write=False,
                             treq_sel=sm_index)
        dma.config(read=self.bufs[0], write=PIO_TXF0 + 4 * sm_index,
                   count=self.n, ctrl=ctrl, trigger=False)
        self.dma = dma

    def busy(self):
        if self.dma is None:
            return False
        try:
            return bool(self.dma.active())
        except Exception:
            return False

    def _plan(self, frame16):
        """Decide how many buffers this frame should be shown through.

        Temporal dithering only works if the whole set of subframes is shown
        well above flicker fusion. Building them costs six dithers, and on this
        chip that is 32 ms against 13 ms for the picture itself -- so on a
        moving programme the loop never finishes early, tick() runs once per
        frame instead of dozens of times, and the six subframes end up being
        shown for 50 ms each. That does not average, it strobes, and a drifting
        rainbow lurches around the ring in thirds of a second.

        The way out is not a cleverer schedule but a cheaper question: has the
        picture stopped changing? A moon phase holds the same 16-bit frame for
        minutes at a time, so the subframes get built once and then cycle for
        as long as it lasts, which is exactly the case they help. Anything
        moving gets a single dither -- no worse than the blocking path, and
        still over DMA, so the CPU is not held with interrupts off.

        Returns True when the buffers need rebuilding.
        """
        if frame16 != self._prev:
            self._prev = frame16
            self._stable = 0
            if self._active != 1:
                self._active = 1
                self._idx = 0
            return True
        if self._stable < SETTLE_FRAMES:
            self._stable += 1
            if self._stable == SETTLE_FRAMES and self.n_sub > 1:
                # It has held still long enough to be worth the six dithers
                self._active = self.n_sub
                self._idx = 0
                return True
        return False

    def tick(self):
        """Push the next subframe if the previous one is done.

        Called from the main loop as often as it likes; returns True when a
        transfer was actually started. Keeps at least RESET_US of idle between
        subframes so the strip latches each one.
        """
        if self.dma is None or self.mode != "dma":
            return False
        if self.busy():
            return False
        now = time.ticks_us()
        if self._free_at and time.ticks_diff(now, self._free_at) < 0:
            return False
        self.dma.config(read=self.bufs[self._idx], count=self.n, trigger=True)
        self._idx += 1
        if self._idx >= self._active:
            self._idx = 0
        # Transmission time plus the latch gap
        self._free_at = time.ticks_add(now, int(self.n * 32 * 1.2) + RESET_US)
        return True

    # --------------------------------------------------------------- output

    def _pack(self, out8, buf):
        for i in range(self.n):
            r, g, b, w = out8[i]
            buf[i] = (g << 24) | (r << 16) | (b << 8) | w

    def show(self, frame16):
        """Emit one 16-bit frame. frame16: list of (r, g, b, w) 0..65535.

        On the blocking path the dither state is rebuilt every time and the
        starting index is fixed, so a still image produces bit-identical data
        on every frame and nothing can flicker. On the DMA path the same frame
        is turned into several subframes whose average carries the extra bits;
        tick() then cycles through them fast enough to fuse.
        """
        if self.mode == "dma":
            if self._plan(frame16):
                if self._active > 1:
                    subs = dither.subframes(frame16, self._active)
                    for j in range(self._active):
                        self._pack(subs[j], self.bufs[j])
                else:
                    self._pack(dither.dither_ring(frame16, dither.new_state(),
                                                  0), self.bufs[0])
            self.tick()
            return

        self._pack(dither.dither_ring(frame16, dither.new_state(), 0), self.buf)
        if self.sm is None:
            return
        if self.irq_safe:
            # Shifting out one frame takes 1.5 ms and must not be interrupted
            # for longer than the FIFO can bridge. Blocking interrupts for that
            # window costs about a tenth of the CPU at 60 Hz and is invisible to
            # Wi-Fi, whereas an underrun is immediately visible on the ring.
            state = machine.disable_irq()
            try:
                self.sm.put(self.buf, 0)
            finally:
                machine.enable_irq(state)
        else:
            self.sm.put(self.buf, 0)

    def off(self):
        self.show([(0, 0, 0, 0)] * self.n)

    def describe(self):
        """One line for the status page."""
        if self.mode == "dma":
            if self._active > 1:
                return "DMA, %d subframes" % self._active
            return "DMA, single frame while the picture moves"
        if self.mode == "blocking":
            return "blocking" + (", DMA requested but unavailable"
                                 if self._want_temporal else "")
        return "no output"
