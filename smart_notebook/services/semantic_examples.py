"""Versioned semantic gold examples and mutation-free embedding evaluation."""
from datetime import datetime
import json
from pathlib import Path

from ..config import (EMBEDDING_MODEL,SEMANTIC_EXAMPLE_MIN_MARGIN,
    SEMANTIC_EXAMPLE_MIN_SIMILARITY,TIMEZONE)
from ..database import get_db_connection
from .embeddings import embedding_to_pgvector,get_embedding

CATALOG_PATH=Path(__file__).resolve().parent.parent/"data"/"semantic_signals_v1.json"

def load_curated_catalog():
    payload=json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return payload["version"],[(item["text"],item["artifact_type"],item["label"]) for item in payload["examples"]]

async def record_gold_example(text,artifact_type,label="positive",source_kind="user_correction",source_artifact_id=None):
    text=text.strip()
    if not text:return None
    vector=await get_embedding(text);now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        row=c.execute("""INSERT INTO semantic_gold_examples(text,artifact_type,label,source_kind,source_artifact_id,
        embedding,embedding_model,active,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s::vector,%s,TRUE,%s,%s)
        ON CONFLICT(text,artifact_type,label) DO UPDATE SET active=TRUE,embedding=EXCLUDED.embedding,
        embedding_model=EXCLUDED.embedding_model,updated_at=EXCLUDED.updated_at RETURNING id""",
        (text,artifact_type,label,source_kind,source_artifact_id,embedding_to_pgvector(vector),EMBEDDING_MODEL,now,now)).fetchone();c.commit()
    return row[0]

async def seed_curated_examples():
    version,examples=load_curated_catalog();ids=[]
    for text,kind,label in examples:ids.append(await record_gold_example(text,kind,label,"curated"))
    return {"catalog_version":version,"seeded":len(ids),"ids":ids}

def list_gold_examples():
    with get_db_connection() as c:rows=c.execute("""SELECT id,text,artifact_type,label,source_kind,source_artifact_id,
        embedding_model,active,created_at,updated_at FROM semantic_gold_examples ORDER BY id""").fetchall()
    return [{"id":r[0],"text":r[1],"artifact_type":r[2],"label":r[3],"source_kind":r[4],"source_artifact_id":r[5],
        "embedding_model":r[6],"active":r[7],"created_at":r[8].isoformat(),"updated_at":r[9].isoformat()} for r in rows]

async def evaluate_semantic_examples(segment_id,text):
    with get_db_connection() as c:available=c.execute("SELECT 1 FROM semantic_gold_examples WHERE active AND label='positive' AND embedding IS NOT NULL LIMIT 1").fetchone()
    if not available:return None
    vector=embedding_to_pgvector(await get_embedding(text));now=datetime.now(TIMEZONE)
    with get_db_connection() as c:
        rows=c.execute("""SELECT DISTINCT ON(artifact_type) artifact_type,1-(embedding<=>%s::vector) similarity
        FROM semantic_gold_examples WHERE active AND label='positive' AND embedding IS NOT NULL
        ORDER BY artifact_type,embedding<=>%s::vector""",(vector,vector)).fetchall()
        ranked=sorted(((r[0],float(r[1])) for r in rows),key=lambda x:x[1],reverse=True)
        best=ranked[0] if ranked else (None,0.0);runner=ranked[1] if len(ranked)>1 else (None,0.0);margin=best[1]-runner[1]
        negative=c.execute("""SELECT 1-(embedding<=>%s::vector) FROM semantic_gold_examples WHERE active AND label='negative'
        AND artifact_type=%s AND embedding IS NOT NULL ORDER BY embedding<=>%s::vector LIMIT 1""",(vector,best[0],vector)).fetchone()
        negative_similarity=float(negative[0]) if negative else None
        positive_negative_margin=(best[1]-negative_similarity) if negative_similarity is not None else None
        ood=(best[1]<SEMANTIC_EXAMPLE_MIN_SIMILARITY or margin<SEMANTIC_EXAMPLE_MIN_MARGIN or
            (positive_negative_margin is not None and positive_negative_margin<SEMANTIC_EXAMPLE_MIN_MARGIN))
        row=c.execute("""INSERT INTO semantic_example_evaluations(segment_id,best_type,best_similarity,runner_up_type,
        runner_up_similarity,margin,out_of_distribution,direct_decision_allowed,created_at,best_negative_similarity,positive_negative_margin)
        VALUES(%s,%s,%s,%s,%s,%s,%s,FALSE,%s,%s,%s) RETURNING id""",
        (segment_id,best[0],best[1],runner[0],runner[1],margin,ood,now,negative_similarity,positive_negative_margin)).fetchone();c.commit()
    return {"id":row[0],"best_type":best[0],"best_similarity":best[1],"runner_up_type":runner[0],
        "runner_up_similarity":runner[1],"margin":margin,"best_negative_similarity":negative_similarity,
        "positive_negative_margin":positive_negative_margin,"out_of_distribution":ood,"direct_decision_allowed":False,
        "thresholds":{"min_similarity":SEMANTIC_EXAMPLE_MIN_SIMILARITY,"min_margin":SEMANTIC_EXAMPLE_MIN_MARGIN}}
