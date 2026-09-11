"""Regression for the real Session 1032 W05 knowledge-probe crash.

STT and semantic-segment text normalize whitespace around punctuation
differently ("W05 -Testschrank" vs "W05-Testschrank"). A byte-exact
`target_text in text` containment check rejected a faithfully-quoted mutation
target span purely because of that incidental spacing difference, hard-
failing the client session into `attention_required` instead of persisting
an intent decision. Reproduced live against the stored session text below
before the fix; must stay green afterwards without weakening the underlying
anti-hallucination guarantee (fabricated content must still be rejected).
"""
from smart_notebook.services.capture_intent import _validate_decision, _contains_span


SESSION_1032_TEXT = ("Korrektur zum W05 -Testschrank. Er steht nicht links, "
                      "sondern rechts neben dem Fenster.")


def _decision(target_text):
    return {"primary_intent": "change", "target_type": "note", "target_text": target_text,
            "confidence": 0.92, "multiple_intents_detected": False, "reason_codes": ["modifies_existing"]}


def main():
    # The real crash: a normalized target span across an STT whitespace artifact.
    result = _validate_decision(_decision("W05-Testschrank"), SESSION_1032_TEXT)
    assert result["target_text"] == "W05-Testschrank", result

    # Extra/missing/repositioned whitespace in either direction is tolerated.
    assert _contains_span("W05 -Testschrank", "W05-Testschrank")
    assert _contains_span("W05-Testschrank", "W05 -Testschrank")
    assert _contains_span("Der Schrank  steht rechts.", "Der Schrank steht rechts.")

    # An exact, unspaced match still works (no regression on the common case).
    exact = _validate_decision(_decision("W05-Testschrank"), "Ändere den W05-Testschrank bitte.")
    assert exact["target_text"] == "W05-Testschrank", exact

    # Fabricated / non-source content must still be rejected: same characters
    # in a different arrangement, not just different whitespace.
    try:
        _validate_decision(_decision("Kuechenschrank"), SESSION_1032_TEXT)
        raise AssertionError("fabricated target_text was wrongly accepted")
    except ValueError as exc:
        assert "exact source span" in str(exc), exc

    print("CAPTURE INTENT SPAN REGRESSION: PASS")


if __name__ == "__main__":
    main()
