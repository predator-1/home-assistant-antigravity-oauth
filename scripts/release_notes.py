"""Print the CHANGELOG.md section for a version: python scripts/release_notes.py 1.5.300"""

import re
import sys
from pathlib import Path

version = sys.argv[1].removeprefix("v")
text = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text()
match = re.search(rf"^## {re.escape(version)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
if not match:
    sys.exit(f"CHANGELOG.md has no section for {version}")
print(match[1].strip())
