"""Compatibility command for the refactored public-data fund report.

Historically this file contained fetching, calculation, HTML, storage and
PushPlus code in one module.  The implementation now lives in ``src/fund_report``
so every boundary can expose its source and validation state.
"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fund_report.main import main  # noqa: E402
from fund_report.sources import EastmoneyNavSource, HttpClient  # noqa: E402


def parse_fund_history_api(text: str, code: str = "000000"):
    """Legacy test helper; returns normalized points and the reported total."""
    return EastmoneyNavSource(HttpClient()).parse_history_response(code, text)


if __name__ == "__main__":
    main()

