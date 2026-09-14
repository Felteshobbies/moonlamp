"""Entry point.

Double-clicking the executable passes no arguments and should open the window;
anything on the command line means the console was the intent.
"""

import sys


def main():
    argv = sys.argv[1:]
    if not argv or argv == ["gui"]:
        from .gui import main as gui_main
        return gui_main()
    from .cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
