"""PyInstaller entry point; keep normal startup shared with the installed package."""

from multiprocessing import freeze_support

from trackfolio.launcher import main

if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
