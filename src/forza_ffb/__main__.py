"""Entry point: ``python -m forza_ffb [options]``."""

from __future__ import annotations

import sys

from .bridge import main

if __name__ == "__main__":
    sys.exit(main())
