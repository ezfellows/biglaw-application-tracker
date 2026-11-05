#!/usr/bin/env python3
"""Run the application tracker: python3 tracker.py --help"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apptracker.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
