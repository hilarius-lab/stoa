"""Single executable M8 backend release gate.

Default execution includes the logical four-hour AAC soak. Use --quick only while
developing; a quick result is deliberately not a release approval.
"""
import argparse,json,subprocess,sys,time
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent
TESTS=[
    "m8_contract_foundation_test.py",
    "m8_client_schema_gate_test.py",
    "m8_reference_contract_test.py",
    "m8_client_session_test.py",
    "m8_client_session_night_repair_test.py",
    "m8_client_session_finish_regression_test.py",
    "m8_chat_promotion_night_repair_test.py",
    "m8_stt_uncertainty_test.py",
    "m8_maintenance_error_isolation_test.py",
    "m8_esp_backend_requirements_test.py",
    "m8_esp_dashboard_projection_test.py",
    "device_auth_test.py",
    "esp32-client/tools/test_h2_mock_server.py",
    "m8_dashboard_contract_test.py",
    "m8_dashboard_isolation_test.py",
    "m8_knowledge_sync_test.py",
    "m8_note_fact_promotion_test.py",
    "semantic_router_test.py",
    "capture_intent_span_test.py",
    "m8_content_type_pipeline_test.py",
    "m8_knowledge_preflight_test.py",
    "m8_mutation_target_resolution_test.py",
    "m8_mutation_action_test.py",
    "m8_partial_action_test.py",
    "m8_clarification_loop_test.py",
    "m8_knowledge_clarification_test.py",
    "m8_chat_push_contract_test.py",
    "m8_capture_contract_test.py",
    "m8_audio_recovery_e2e_test.py",
    "m8_audio_diagnostic_test.py",
    "smoke_test.py",
]


def run(command):
    started=time.perf_counter()
    result=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
    return {"command":command,"exit_code":result.returncode,"wall_seconds":round(time.perf_counter()-started,3),
            "stdout":result.stdout[-4000:],"stderr":result.stderr[-4000:]}


def assert_release_docs():
    roadmap=(ROOT/"ROADMAP.md").read_text(encoding="utf-8")
    section=roadmap.split("### M8 – Backend-Freigabe für den Android-Client",1)[1].split("### M9 –",1)[0]
    assert "- [ ]" not in section,"ROADMAP M8 still contains unchecked release requirements"
    contract=(ROOT/"CLIENT_BACKEND_CONTRACT.md").read_text(encoding="utf-8")
    assert "Status: freigegeben" in contract
    for marker in ("TBD","TODO","offene Frage","noch nicht freigegeben"):
        assert marker not in contract,f"client contract contains unresolved marker: {marker}"
    matrix=(ROOT/"CLIENT_CONTRACT_MATRIX.md").read_text(encoding="utf-8")
    android_roadmap=(ROOT/"android"/"docs"/"ANDROID_CLIENT_ROADMAP.md").read_text(encoding="utf-8")
    for name,text in (("ROADMAP M8",section),("CLIENT_BACKEND_CONTRACT",contract),
                      ("CLIENT_CONTRACT_MATRIX",matrix),("ANDROID_CLIENT_ROADMAP",android_roadmap)):
        assert "/api/client/v1/diagnostics/audio-upload-test" in text,f"missing diagnostic endpoint in {name}"
        assert "nebenwirkungsfrei" in text.lower(),f"diagnostic endpoint not documented as side-effect-free in {name}"
    json.loads((ROOT/"contracts"/"client-reference-fixtures-v1.json").read_text(encoding="utf-8"))
    esp=(ROOT/"esp32-client"/"docs"/"BACKEND_REQUIREMENTS.md").read_text(encoding="utf-8")
    for marker in ("local_audio_release_allowed","local_audio_release_at",
                   "SESSION_ID_CONFLICT","sequence_base","limit","offset",
                   "dashboard_cache_max_age_seconds: 7200",
                   "Stabile Fokusidentität","SSE — serverseitig umgesetzt"):
        assert marker in esp,f"ESP backend contract is missing: {marker}"
    assert "Keine Historie von Dashboard-Snapshots" in esp


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--quick",action="store_true");args=parser.parse_args()
    results=[]
    for test in TESTS:
        outcome=run([sys.executable,str(ROOT/test)]);results.append(outcome)
        if outcome["exit_code"]:
            print(outcome["stdout"]);print(outcome["stderr"],file=sys.stderr)
            raise SystemExit(f"M8 gate failed: {test}")
        print(f"PASS {test} ({outcome['wall_seconds']} s)")
    soak=[sys.executable,str(ROOT/"m8_four_hour_soak_test.py")]
    if args.quick:soak.extend(["--hours","0.02"])
    outcome=run(soak);results.append(outcome)
    if outcome["exit_code"]:
        print(outcome["stdout"]);print(outcome["stderr"],file=sys.stderr);raise SystemExit("M8 gate failed: soak")
    print(f"PASS m8_four_hour_soak_test.py ({outcome['wall_seconds']} s)")
    if not args.quick:assert_release_docs()
    report={"gate":"M8","mode":"quick" if args.quick else "release","passed":True,
            "completed_at":datetime.now().astimezone().isoformat(),"tests":[{"name":Path(x["command"][1]).name,"wall_seconds":x["wall_seconds"]} for x in results]}
    reports=ROOT/"reports";reports.mkdir(exist_ok=True)
    (reports/("m8-gate-quick.json" if args.quick else "m8-release-gate.json")).write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("M8 RELEASE GATE: PASS" if not args.quick else "M8 QUICK GATE: PASS (not a release approval)")


if __name__=="__main__":main()
