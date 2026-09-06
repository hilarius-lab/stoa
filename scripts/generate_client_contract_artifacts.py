"""Regenerate the frozen client OpenAPI and deterministic response fixtures."""
import json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from smart_notebook.app import app
from smart_notebook.client_openapi import build_client_openapi,canonical_client_openapi

OPENAPI=ROOT/"contracts"/"client-openapi-v1.json"
FIXTURES=ROOT/"contracts"/"client-reference-fixtures-v1.json"

def example(schema,root,seen=None):
    seen=set(seen or ())
    if "$ref" in schema:
        name=schema["$ref"].rsplit("/",1)[-1]
        if name in seen:return {}
        return example(root["components"]["schemas"][name],root,seen|{name})
    if "const" in schema:return schema["const"]
    if schema.get("enum"):return schema["enum"][0]
    if schema.get("examples"):return schema["examples"][0]
    if "default" in schema:return schema["default"]
    choices=schema.get("anyOf") or schema.get("oneOf")
    if choices:
        non_null=[x for x in choices if x.get("type")!="null"]
        return example((non_null or choices)[0],root,seen)
    kind=schema.get("type")
    if kind=="object" or "properties" in schema:
        required=set(schema.get("required",()))
        return {key:example(value,root,seen) for key,value in schema.get("properties",{}).items() if key in required}
    if kind=="array":return []
    if kind=="integer":return max(1,schema.get("minimum",1))
    if kind=="number":return max(1.0,schema.get("minimum",1.0))
    if kind=="boolean":return False
    if kind=="string":
        return {"uuid":"00000000-0000-4000-8000-000000000001","date-time":"2026-08-27T12:00:00+02:00"}.get(schema.get("format"),"fixture")
    return None

def main():
    spec=build_client_openapi(app)
    OPENAPI.write_text(canonical_client_openapi(app),encoding="utf-8")
    fixture=json.loads(FIXTURES.read_text(encoding="utf-8"))
    names=set()
    for path in spec["paths"].values():
        for operation in path.values():
            if not isinstance(operation,dict):continue
            for code,response in operation.get("responses",{}).items():
                if not str(code).startswith("2"):continue
                for media in response.get("content",{}).values():
                    schema=media.get("schema",{})
                    ref=schema.get("$ref") or schema.get("x-event-data-schema",{}).get("$ref")
                    if ref:names.add(ref.rsplit("/",1)[-1])
    fixture["response_examples"]={name:example({"$ref":f"#/components/schemas/{name}"},spec) for name in sorted(names)}
    FIXTURES.write_text(json.dumps(fixture,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Generated {OPENAPI.name} and {len(names)} response examples")

if __name__=="__main__":main()
