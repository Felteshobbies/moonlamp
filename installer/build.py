"""Build the single-file installer.

    python installer\\build.py

Collects the firmware and the MicroPython build into a payload directory,
then runs PyInstaller over it. The payload is staged rather than referenced in
place so that the executable always carries exactly the firmware that sat in
the repository when it was built -- an installer that silently picks up a
half-edited working tree would be worse than no installer.

The result lands in installer/dist/.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir))
PKG = os.path.join(HERE, "moonlamp_installer")
PAYLOAD = os.path.join(PKG, "payload")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "firmware", "lib"))


def stage_payload():
    """Copy the firmware and the UF2 into the package, ready to be bundled."""
    from moonlamp_installer import releases

    if os.path.isdir(PAYLOAD):
        shutil.rmtree(PAYLOAD)
    fw_dir = os.path.join(PAYLOAD, "firmware")
    for name in releases.DEVICE_FILES:
        src = os.path.join(REPO, "firmware", name.replace("/", os.sep))
        dst = os.path.join(fw_dir, name.replace("/", os.sep))
        if not os.path.isfile(src):
            raise SystemExit("missing firmware file: %s" % src)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

    uf2 = releases.bundled_uf2()
    if uf2:
        mp_dir = os.path.join(PAYLOAD, "micropython")
        os.makedirs(mp_dir, exist_ok=True)
        shutil.copy2(uf2, os.path.join(mp_dir, os.path.basename(uf2)))
    else:
        print("warning: no MicroPython UF2 found; the installer will not be")
        print("         able to flash a blank board")

    version = releases.version_of(releases.bundled_firmware())
    print("payload staged: firmware %s%s"
          % (version, ", plus " + os.path.basename(uf2) if uf2 else ""))
    return version


def run_pyinstaller(onefile=True):
    try:
        import PyInstaller                                   # noqa: F401
    except ImportError:
        raise SystemExit("PyInstaller is missing: "
                         "python -m pip install pyinstaller")
    sep = ";" if sys.platform.startswith("win") else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "moonlamp-installer",
        "--windowed" if sys.platform == "darwin" else "--console",
        "--add-data", "%s%s%s" % (PAYLOAD, sep, "payload"),
        # tkinter is found automatically; pyserial's port listing is not,
        # because it is imported by name at runtime
        "--hidden-import", "serial.tools.list_ports",
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", os.path.join(HERE, "build"),
        "--specpath", HERE,
        # The package has to be importable by name: entry.py uses absolute
        # imports precisely so that freezing does not turn them into orphans
        "--paths", HERE,
    ]
    cmd.append("--onefile" if onefile else "--onedir")
    cmd.append(os.path.join(HERE, "entry.py"))
    print("$ " + " ".join(cmd[1:]))
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    version = stage_payload()
    if "--stage-only" in sys.argv:
        print("staged only, not building")
    else:
        run_pyinstaller(onefile="--onedir" not in sys.argv)
