"""Rounding 16 bits down to the SK6812's 8, without losing the low end.

The problem: this lamp's most interesting states live right at the bottom --
earthshine at 1.8 %, night light at a few percent. Rounded naively you end up
at counts of 2 to 5, where the steps become visible and the white shifts hue
while dimming, because all four channels round differently.

The usual remedy is temporal dithering at a high frame rate. Here that would
need DMA: 44 pixels times 32 bits take 1.76 ms, so 400 Hz would be 70 % of the
CPU, and with Wi-Fi active that gets tight.

So this does *purely spatial* dithering around the ring. That exploits the fact
that neighbouring LEDs illuminate heavily overlapping areas of the moon:
rounding one up and the next one down averages out on the surface with no time
component at all. The caller rebuilds the state for every frame and keeps the
start index fixed, so a still image yields bit-identical output on every frame
and nothing can flicker by construction.

Note what this costs: the ring cannot show less than one count per LED. Below
that the pattern thins out into isolated lit pixels instead of getting dimmer,
which is why config.BRIGHTNESS_STEPS stops at 1/255 of linear light.

The pattern would only be visible right in front of the LEDs in the outermost
ring -- and the frame's front lip hides that anyway.
"""

CHANNELS = 4


def dither_ring(frame16, state, rotate=0):
    """Turn a 16-bit frame into 8-bit values, carrying the error along the ring.

    frame16  list of (r, g, b, w) with 0..65535, linear
    state    list of CHANNELS entries, carries the error across frames
    rotate   start index; advancing it by one each frame spreads the error over
             time as well, without fast changes in brightness

    Returns a list of (r, g, b, w) with 0..255.
    """
    n = len(frame16)
    out = [None] * n
    err = list(state)
    for k in range(n):
        i = (k + rotate) % n
        px = frame16[i]
        vals = [0] * CHANNELS
        for c in range(CHANNELS):
            # 16 bits down to 8: the remainder moves on to the next LED
            total = px[c] + err[c]
            v = total >> 8
            if v < 0:
                v = 0
            elif v > 255:
                v = 255
            err[c] = total - (v << 8)
            vals[c] = v
        out[i] = (vals[0], vals[1], vals[2], vals[3])
    for c in range(CHANNELS):
        state[c] = err[c]
    return out


def new_state():
    return [0] * CHANNELS


def window_error(frame16, window=5):
    """Largest error of a sliding-window mean, in 16-bit counts -- for the tests.

    The physically meaningful quantity is not the accuracy of a single LED but
    of a small group of them, because neighbouring LEDs light overlapping areas
    of the relief. So compare the mean of `window` adjacent outputs against the
    mean of the same window of targets.
    """
    out = dither_ring(frame16, new_state(), 0)
    n = len(frame16)
    worst = [0.0] * CHANNELS
    for i in range(n):
        for c in range(CHANNELS):
            got = sum(out[(i + k) % n][c] for k in range(window)) / float(window)
            want = sum(frame16[(i + k) % n][c] for k in range(window)) / float(window)
            d = abs(got * 256.0 - want)
            if d > worst[c]:
                worst[c] = d
    return worst


def ring_mean(frame16):
    """Mean 8-bit output over the whole ring, per channel, scaled to 16 bits."""
    out = dither_ring(frame16, new_state(), 0)
    n = float(len(frame16))
    return [sum(p[c] for p in out) / n * 256.0 for c in range(CHANNELS)]

def subframes(frame16, count):
    """Split one 16-bit frame into `count` 8-bit frames for temporal dithering.

    Shown in quick succession, their average resolves finer than a single
    count. Each subframe runs the same spatial diffusion, only with a different
    starting error: a pixel whose target is a whole count plus a fraction f
    then lands one count higher in about f of the subframes, so its time
    average comes out right.

    That is worth doing only if the whole set can be shown well above the
    flicker fusion limit -- see leds.Ring, which drives it from a timer.
    """
    if count < 2:
        return [dither_ring(frame16, new_state(), 0)]
    out = []
    for j in range(count):
        bias = (j * 256) // count
        out.append(dither_ring(frame16, [bias] * CHANNELS, 0))
    return out


def temporal_mean(frame16, count):
    """Time average of the subframes, per LED and channel, in 16-bit counts."""
    subs = subframes(frame16, count)
    n = len(frame16)
    return [[sum(s[i][c] for s in subs) / float(count) * 256.0
             for c in range(CHANNELS)] for i in range(n)]
