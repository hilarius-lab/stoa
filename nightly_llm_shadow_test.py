"""Live local-LLM regression: semantic review is logged but never mutates knowledge."""
import asyncio
import math
import random
import uuid

from smart_notebook.config import EMBEDDING_DIMENSIONS
from smart_notebook.database import get_db_connection
from smart_notebook.services.nightly_consolidation import run_nightly_knowledge_consolidation
from smart_notebook.services.notes import save_note


async def main():
    token = uuid.uuid4().hex[:12]
    rng = random.Random(token)
    embedding = [rng.uniform(-1.0, 1.0) for _ in range(EMBEDDING_DIMENSIONS)]
    norm = math.sqrt(sum(value * value for value in embedding))
    embedding = [value / norm for value in embedding]
    ids = [
        save_note(f"Das Projekt Aurora benötigt bis Freitag den geprüften Kostenbericht. {token}", embedding),
        save_note(f"Für Aurora soll der kontrollierte Kostenbericht spätestens Freitag vorliegen. {token}", embedding),
    ]
    run_id = None
    try:
        result = await run_nightly_knowledge_consolidation(
            dry_run=True, semantic_review=True, limit=5
        )
        run_id = result["run_id"]
        with get_db_connection() as connection:
            row = connection.execute(
                """SELECT model_decision,status,source_refs FROM nightly_consolidation_candidates
                WHERE run_id=%s AND candidate_kind='knowledge_duplicate'
                AND (source_refs->>'left_id')::bigint = ANY(%s)
                AND (source_refs->>'right_id')::bigint = ANY(%s)""",
                (run_id, ids, ids),
            ).fetchone()
            assert row, "The isolated semantic pair was not reviewed"
            assert row[0] in {"merge", "synthesize", "keep_separate"}, row
            assert row[1] == "shadow", row
            assert connection.execute(
                "SELECT count(*) FROM notes WHERE id=ANY(%s) AND archived", (ids,)
            ).fetchone()[0] == 0
        assert result["summary"]["semantic_mutations"] == 0
        print("NIGHTLY LOCAL-LLM SHADOW TEST: PASS")
    finally:
        with get_db_connection() as connection:
            connection.execute("DELETE FROM notes WHERE id=ANY(%s)", (ids,))
            if run_id is not None:
                connection.execute("DELETE FROM nightly_consolidation_runs WHERE id=%s", (run_id,))
            connection.commit()


if __name__ == "__main__":
    asyncio.run(main())
