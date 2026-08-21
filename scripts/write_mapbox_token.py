"""Generate frontend/assets/mapbox-token.js (gitignored) from MAPBOX_TOKEN.

The token comes from the environment, or from `.env` at the repo root when the
environment does not have it. Run after cloning or whenever the token changes:

    python scripts/write_mapbox_token.py
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend" / "assets" / "mapbox-token.js"


def read_env_file(path: Path) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*MAPBOX_TOKEN\s*=\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip("\"'")
    return ""


def main() -> None:
    token = os.environ.get("MAPBOX_TOKEN") or read_env_file(ROOT / ".env")
    if not token or token.startswith("pk.your-"):
        sys.exit("MAPBOX_TOKEN is not set — put it in .env (see .env.example) "
                 "or export it, then rerun.")
    if not re.fullmatch(r"pk\.[A-Za-z0-9_.-]+", token):
        sys.exit("MAPBOX_TOKEN does not look like a Mapbox public (pk.) token — "
                 "refusing to embed it in client-side code.")
    OUT.write_text(f'window.MAPBOX_TOKEN = "{token}";\n', encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
