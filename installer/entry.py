"""Entry point for the frozen executable.

Deliberately outside the package and using absolute imports. A frozen
`__main__.py` becomes a top-level script with no parent package, so the
relative imports that work under `python -m moonlamp_installer` fail with
"attempted relative import with no known parent package" -- and only once the
build is running, never in development.
"""

import sys


def main():
    argv = sys.argv[1:]
    if not argv or argv == ["gui"]:
        from moonlamp_installer.gui import main as gui_main
        return gui_main()
    from moonlamp_installer.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
