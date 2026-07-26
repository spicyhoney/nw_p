from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from home_repair_agent.data_cleaning.reference_cli import main  # noqa: E402


raise SystemExit(main())
