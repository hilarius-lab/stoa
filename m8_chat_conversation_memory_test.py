"""W03: client_chat conversations now have real multi-turn memory.

client_chat.py::run_chat_turn_once() answered every real ("llm" mode) turn by
creating a synthetic events-table row purely to call chat.py::ask_llm(), whose
build_messages() sourced prior conversation turns exclusively from
chat.py::get_recent_conversation() -- a query over the *legacy* `events`
table (`WHERE response IS NOT NULL AND created_at >= NOW() - N minutes`,
with no conversation scoping at all). Two real, compounding bugs followed:

1. The synthetic event created for a client_chat turn never has its
   `events.response` column set (only routers/events.py's legacy /api/message
   endpoint ever writes that column) -- so get_recent_conversation()'s
   `response IS NOT NULL` filter never matches a client_chat turn's own prior
   messages. A client_chat conversation therefore had **no working memory of
   its own history at all**: every turn was answered as if it were the first.
2. Had that filter matched, it would not have been scoped to the specific
   conversation_id either -- windowed only by recency, so multiple concurrent
   conversations (or the legacy /api/message thread, if used) could bleed
   into each other's context.

Fixed by adding chat.py::get_conversation_turn_context(), which reads
client_conversation_messages (the table A11 introduced) filtered to one
conversation_id and ordered by sequence -- the same source client_chat.py
already uses for everything else about a conversation. ask_llm()/
build_messages() take an optional conversation_id/before_sequence and use
this instead of get_recent_conversation() whenever a conversation_id is
given; the legacy /api/message path (routers/events.py, no conversation_id)
is untouched.

This test makes real LLM calls (mode="llm", not "deterministic") against the
live endpoint -- proving actual memory, not just that the query changed.

Run directly: `.venv/Scripts/python.exe m8_chat_conversation_memory_test.py`
"""
import asyncio
import atexit
from uuid import uuid4

from smart_notebook.database import get_db_connection
from smart_notebook.services.client_chat import add_turn, create_conversation, run_chat_turn_once

_TAG = f"m8-w03-{uuid4().hex[:12]}"
_CLEANUP_CONVERSATION_IDS = []


def _cleanup():
    with get_db_connection() as db:
        for conversation_id in _CLEANUP_CONVERSATION_IDS:
            db.execute("DELETE FROM client_conversations WHERE id=%s", (conversation_id,))
        # The synthetic events-table rows run_chat_turn_once() creates per real
        # turn (see module docstring) are not linked to client_conversations by
        # any FK -- clean them up by the tag every test message carries so they
        # cannot be swept into a real nightly consolidation run (W07's new
        # catch-up boundary would otherwise happily pick these up).
        db.execute("DELETE FROM events WHERE text LIKE %s", (f"%{_TAG}%",))
        db.commit()


atexit.register(_cleanup)


def main():
    # The tag identifies this test's rows for cleanup; it must never overlap
    # textually with the secret code itself, or a memory-less LLM could
    # "answer correctly" by echoing the tag straight out of its own current
    # turn instead of truly recalling turn 1 -- exactly the false pass this
    # test must not produce.
    secret_code = f"Fuchs-{uuid4().hex[:10]}"
    result = create_conversation(
        uuid4(), uuid4(), uuid4(),
        f"Merk dir bitte diesen Code: {secret_code}. [test-tag:{_TAG}]",
    )
    conversation_id = result["conversation"]["id"]
    _CLEANUP_CONVERSATION_IDS.append(conversation_id)

    outcome1 = asyncio.run(run_chat_turn_once(mode="llm"))
    assert outcome1["outcome"] == "completed", outcome1

    add_turn(conversation_id, uuid4(), uuid4(), f"Welchen Code habe ich dir gerade genannt? [test-tag:{_TAG}]")
    outcome2 = asyncio.run(run_chat_turn_once(mode="llm"))
    assert outcome2["outcome"] == "completed", outcome2

    with get_db_connection() as db:
        assistant_reply = db.execute(
            """SELECT content FROM client_conversation_messages
            WHERE conversation_id=%s AND role='assistant' ORDER BY sequence DESC LIMIT 1""",
            (conversation_id,),
        ).fetchone()[0]

    assert secret_code in assistant_reply, assistant_reply

    print("W03 CHAT CONVERSATION MEMORY: PASS")


if __name__ == "__main__":
    main()
