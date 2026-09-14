"""
Entry point for the editions. Keeps the repo's `python src/<thing>.py`
convention; the work is in the editions package.

    python src/edition.py preview --dry-run
    python src/edition.py auto
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from editions.runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
