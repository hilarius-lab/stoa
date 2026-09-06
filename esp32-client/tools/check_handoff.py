"""Validate the portable ESP32 handoff after generated directories are removed."""
import json
import re
from pathlib import Path

root=Path(__file__).resolve().parents[1]
required=[
    "README.md","HANDOFF.md","CMakeLists.txt","sdkconfig.defaults","partitions.csv",
    "main/main.c","main/recorder.c","main/screen.c","main/storage.c",
    "main/journal.c","main/journal.h","main/memo_queue.c","main/memo_queue.h",
    "main/api_client.c","main/api_client.h",
    "tools/journal_test.c","tools/run_journal_test.sh",
    "tools/h2_mock_server.py","tools/test_h2_mock_server.py",
    "docs/PRODUCT_VISION.md","docs/IMPLEMENTATION_DECISIONS.md",
    "docs/PROJECT_STATUS.md","docs/ARCHITECTURE.md","docs/API_INTERACTION.md","docs/DASHBOARD_UI.md",
    "docs/DEVELOPMENT_GUIDE.md","docs/ROADMAP.md",
    "docs/H2_MOCK_SERVER.md",
    "contract/openapi-esp32-client-v1.json",
]
missing=[name for name in required if not (root/name).is_file()]
assert not missing,f"Missing handoff files: {missing}"
generated=[name for name in ("build","managed_components","sdkconfig","sdkconfig.old") if (root/name).exists()]
assert not generated,f"Generated files present: {generated}"
contract=json.loads((root/"contract/openapi-esp32-client-v1.json").read_text(encoding="utf-8"))
schema_names=set(contract["components"]["schemas"])
refs=[]
def walk(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if key=="$ref" and isinstance(item,str) and item.startswith("#/components/schemas/"):
                refs.append(item.rsplit("/",1)[1])
            walk(item)
    elif isinstance(value,list):
        for item in value: walk(item)
walk(contract)
assert set(refs)<=schema_names,f"Unresolved schemas: {sorted(set(refs)-schema_names)}"
for markdown in root.rglob("*.md"):
    text=markdown.read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:[/\\]Users[/\\]",text),f"Absolute user path: {markdown}"
    for target in re.findall(r"\[[^]]+\]\(([^)]+)\)",text):
        if "://" in target or target.startswith("#"): continue
        assert (markdown.parent/target).resolve().exists(),f"Broken link {target} in {markdown}"
assert len(contract["paths"])==22,"ESP contract must include all 22 device paths"
print(f"Handoff OK: {len(required)} required files, {len(contract['paths'])} API paths, {len(schema_names)} schemas")
