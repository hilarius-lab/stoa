from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from main import app
from smart_notebook.client_openapi import canonical_client_openapi

target = ROOT / "contracts" / "client-openapi-v1.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(canonical_client_openapi(app), encoding="utf-8")
print(target)
