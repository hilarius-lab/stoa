"""Create the self-contained ESP32-facing subset of the monorepo OpenAPI contract."""
import argparse
import hashlib
import json
from pathlib import Path

PATHS = {
    "/api/client/capabilities",
    "/api/client/v1/contract",
    "/api/client/v1/captures",
    "/api/client/v1/captures/{capture_id}",
    "/api/client/v1/dashboard",
    "/api/client/v1/dashboard/events",
    "/api/client/v1/diagnostics/audio-upload-test",
    "/api/client/v1/entities/{entity_type}/{entity_id}",
    "/api/client/v1/installations/enroll",
    "/api/client/v1/installations/{client_installation_id}/credentials/rotate",
    "/api/client/v1/sessions",
    "/api/client/v1/sessions/{client_session_id}",
    "/api/client/v1/sessions/{client_session_id}/abort",
    "/api/client/v1/sessions/{client_session_id}/audio-chunks",
    "/api/client/v1/sessions/{client_session_id}/dashboard",
    "/api/client/v1/sessions/{client_session_id}/dashboard/events",
    "/api/client/v1/sessions/{client_session_id}/finalize",
    "/api/client/v1/sessions/{client_session_id}/finish",
    "/api/client/v1/sessions/{client_session_id}/pause",
    "/api/client/v1/sessions/{client_session_id}/reconciliation",
    "/api/client/v1/sessions/{client_session_id}/resume",
    "/api/client/v1/sessions/{client_session_id}/start",
}

def refs(value):
    if isinstance(value, dict):
        ref=value.get("$ref")
        if isinstance(ref,str) and ref.startswith("#/components/schemas/"):
            yield ref.rsplit("/",1)[1]
        for item in value.values(): yield from refs(item)
    elif isinstance(value,list):
        for item in value: yield from refs(item)

parser=argparse.ArgumentParser()
parser.add_argument("source",type=Path)
parser.add_argument("output",type=Path)
args=parser.parse_args()
raw=args.source.read_bytes()
source=json.loads(raw)
missing=PATHS-source["paths"].keys()
if missing: raise SystemExit(f"Missing paths: {sorted(missing)}")
paths={key:source["paths"][key] for key in sorted(PATHS)}
all_schemas=source["components"]["schemas"]
needed=set(refs(paths))
pending=list(needed)
while pending:
    name=pending.pop()
    if name not in all_schemas: raise SystemExit(f"Missing schema: {name}")
    for dependency in refs(all_schemas[name]):
        if dependency not in needed:
            needed.add(dependency); pending.append(dependency)
result={
    "openapi":source["openapi"],
    "info":source["info"],
    "paths":paths,
    "components":{"schemas":{key:all_schemas[key] for key in sorted(needed)}},
    "x-handoff-scope":"esp32-client",
    "x-source-sha256":hashlib.sha256(raw).hexdigest(),
}
args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(f"Wrote {len(paths)} paths and {len(needed)} schemas; source SHA-256 {result['x-source-sha256']}")
