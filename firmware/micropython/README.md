# MicroPython

`RPI_PICO_W-20260824-v1.29.0.uf2` is an unmodified MicroPython build for the
Raspberry Pi Pico W, taken from [micropython.org/download](https://micropython.org/download/RPI_PICO_W/).

It is in version control on purpose. The installer's whole promise is that it
carries everything needed to take a blank Pico to a running lamp with no
network — and a build runner starting from a fresh checkout has no other way to
obtain it. Downloading it during the build would put micropython.org in the
critical path of every release.

MicroPython is copyright Damien P. George and contributors, and is distributed
under the MIT license. Redistributing the binary is permitted; the full license
travels with the project at
[github.com/micropython/micropython](https://github.com/micropython/micropython/blob/master/LICENSE).

For a **Pico 2 W** you need the `RPI_PICO2_W` build instead — a UF2 carries a
family id and the bootloader silently discards one meant for the other chip.
The installer checks for that mismatch and refuses rather than leaving you with
a board that never comes back. Pass a different build with `--uf2`.
