"""Machine-readable M8 gate for every public client response contract."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from referencing import Registry,Resource
from referencing.jsonschema import DRAFT202012
from smart_notebook.app import app
from smart_notebook.client_openapi import build_client_openapi

ROOT=Path(__file__).resolve().parent
METHODS={"get","post","put","patch","delete"}

def main():
    spec=build_client_openapi(app);fixtures=json.loads((ROOT/"contracts"/"client-reference-fixtures-v1.json").read_text(encoding="utf-8"))
    examples=fixtures["response_examples"];used=set()
    registry=Registry().with_resource("urn:smart-notebook:client-openapi",Resource(contents=spec,specification=DRAFT202012))
    assert "/api/client/v1/diagnostics/audio-upload-test" in spec["paths"]
    for path,item in spec["paths"].items():
        for method,operation in item.items():
            if method not in METHODS:continue
            successes=[(str(code),response) for code,response in operation.get("responses",{}).items() if str(code).startswith("2")]
            assert successes,f"{method.upper()} {path}: no success response"
            for code,response in successes:
                content=response.get("content",{})
                if code=="204":
                    assert not content,f"{method.upper()} {path}: 204 must not carry content";continue
                assert len(content)==1,f"{method.upper()} {path}: ambiguous success media types"
                media,specification=next(iter(content.items()));schema=specification.get("schema")
                assert schema and schema!={},f"{method.upper()} {path}: empty success schema"
                if media=="text/event-stream":
                    assert schema.get("type")=="string"
                    ref=schema.get("x-event-data-schema",{}).get("$ref")
                else:
                    assert media=="application/json",f"{method.upper()} {path}: unexpected media type {media}"
                    ref=schema.get("$ref")
                assert ref and ref.startswith("#/components/schemas/"),f"{method.upper()} {path}: response is not typed"
                name=ref.rsplit("/",1)[-1];assert name in spec["components"]["schemas"],f"dangling response ref: {ref}"
                assert name in examples,f"missing reference fixture for {name}"
                Draft202012Validator({"$ref":"urn:smart-notebook:client-openapi"+ref},registry=registry).validate(examples[name]);used.add(name)
            for code,response in operation.get("responses",{}).items():
                if not (str(code).startswith("4") or str(code).startswith("5")):continue
                schema=response.get("content",{}).get("application/json",{}).get("schema",{})
                assert schema.get("$ref")=="#/components/schemas/ErrorResponse",f"{method.upper()} {path} {code}: non-contract error schema"
    assert set(examples)==used,f"orphan fixture schemas: {sorted(set(examples)-used)}"
    assert app.openapi()["paths"]["/api/client/v1/diagnostics/audio-upload-test"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    print(f"M8 CLIENT SCHEMA GATE: PASS ({len(used)} response schemas)")

if __name__=="__main__":main()
