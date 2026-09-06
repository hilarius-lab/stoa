"""Canonical client-only OpenAPI projection used by generators and CI."""
import json
from .client_models import ChatSSEEvent,DashboardSSEEvent


def build_client_openapi(app):
    source = app.openapi()
    paths = {path: value for path, value in source.get("paths", {}).items()
             if path.startswith("/api/client/")}
    referenced = json.dumps(paths, sort_keys=True)
    schemas = source.get("components", {}).get("schemas", {})
    selected = {}
    changed = True
    while changed:
        changed = False
        for name, schema in schemas.items():
            marker = f"#/components/schemas/{name}"
            if name not in selected and marker in referenced:
                selected[name] = schema
                referenced += json.dumps(schema, sort_keys=True)
                changed = True
    # StreamingResponse intentionally bypasses FastAPI response serialization. Its
    # wire representation is text/event-stream, while x-event-data-schema points at
    # the typed JSON carried in each SSE data field. Register those two payload
    # schemas explicitly so the extension never contains a dangling reference.
    for model in (DashboardSSEEvent,ChatSSEEvent):
        selected[model.__name__]=model.model_json_schema(
            ref_template="#/components/schemas/{model}")
    return {
        "openapi": source["openapi"],
        "info": {"title": "Smart Notebook Client API", "version": "1"},
        "paths": paths,
        "components": {"schemas": selected},
    }


def canonical_client_openapi(app):
    return json.dumps(build_client_openapi(app), ensure_ascii=False, indent=2,
                      sort_keys=True) + "\n"
