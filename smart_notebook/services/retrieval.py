# Retrieval service
from datetime import datetime,timedelta
import hashlib,json
from ..config import (
    KNOWLEDGE_RETRIEVAL_LIMIT, KNOWLEDGE_RETRIEVAL_MIN_SIMILARITY,
    HYBRID_CANDIDATE_LIMIT, HYBRID_RRF_K, HYBRID_TRIGRAM_MIN_SCORE,
    EMBEDDING_MODEL,RETRIEVAL_CACHE_TTL_HOURS,TIMEZONE
)
from ..database import get_db_connection
from .embeddings import get_query_embedding, embedding_to_pgvector
from .provenance import get_knowledge_sources
from .notes import get_note_record
from .tasks import get_task_record
from .lists import get_list_record, get_list_item_record
from .topics import get_knowledge_topic_links

RETRIEVAL_VERSION="efficiency-ladder-v2"

def _knowledge_version(connection):
    return connection.execute("""SELECT md5(concat_ws('|',
    (SELECT concat(count(*),':',COALESCE(max(updated_at)::text,'')) FROM notes),
    (SELECT concat(count(*),':',COALESCE(max(updated_at)::text,'')) FROM tasks),
    (SELECT concat(count(*),':',COALESCE(max(updated_at)::text,'')) FROM lists),
    (SELECT concat(count(*),':',COALESCE(max(updated_at)::text,'')) FROM list_items),
    (SELECT count(*)::text FROM knowledge_topic_links),(SELECT count(*)::text FROM knowledge_supersessions)))""").fetchone()[0]

def _cache_identity(connection,query,selected_types,limit,min_similarity):
    normalized=" ".join(query.casefold().split());version=_knowledge_version(connection)
    request={"query_hash":hashlib.sha256(normalized.encode()).hexdigest(),"types":sorted(selected_types),"limit":limit,
        "min_similarity":min_similarity,"retrieval_version":RETRIEVAL_VERSION,"embedding_model":EMBEDDING_MODEL,"knowledge_version":version}
    return hashlib.sha256(json.dumps(request,sort_keys=True,separators=(',',':')).encode()).hexdigest(),request

def purge_expired_retrieval_cache():
    with get_db_connection() as c:
        count=c.execute("DELETE FROM retrieval_cache WHERE expires_at<=%s",(datetime.now(TIMEZONE),)).rowcount;c.commit()
    return count

def _exact_channel_candidates(connection,selected_types,query):
    candidates=[];normalized=" ".join(query.casefold().split())
    specs={
        "note":("notes","content","archived=FALSE","note"),
        "task":("tasks","content","archived=FALSE AND status='open'","task"),
        "list":("lists","title","archived=FALSE","list"),
        "list_item":("list_items","content","archived=FALSE AND status='active'","list_item"),
    }
    for kind in selected_types:
        table,column,where,prefix=specs[kind]
        rows=connection.execute(f"SELECT id FROM {table} WHERE {where} AND lower(regexp_replace(trim({column}),'\\s+',' ','g'))=%s LIMIT %s",
            (normalized,HYBRID_CANDIDATE_LIMIT)).fetchall()
        candidates.extend({"key":f"{prefix}:{r[0]}","score":1.0} for r in rows)
    return candidates

def parse_knowledge_key(key: str):
    if ":" not in key:
        raise ValueError(
            "Knowledge key must use '<type>:<id>', "
            "for example 'note:15'"
        )

    raw_type, raw_id = key.split(":", 1)

    knowledge_type = raw_type.strip().lower()
    allowed_types = {
        "note",
        "task",
        "list",
        "list_item"
    }

    if knowledge_type not in allowed_types:
        raise ValueError(
            f"Unsupported knowledge type: {knowledge_type}"
        )

    try:
        object_id = int(raw_id)
    except ValueError as exc:
        raise ValueError(
            "Knowledge ID must be an integer"
        ) from exc

    if object_id <= 0:
        raise ValueError(
            "Knowledge ID must be greater than zero"
        )

    return knowledge_type, object_id

def get_knowledge_record(key: str):
    knowledge_type, object_id = parse_knowledge_key(key)

    if knowledge_type == "note":
        note = get_note_record(object_id)

        if note is None:
            return None

        return {
            "key": f"note:{object_id}",
            "type": "note",
            "id": object_id,
            "title": None,
            "content": note["content"],
            "created_at": note["created_at"],
            "updated_at": note["updated_at"],
            "archived": note["archived"],
            "source_event_id": note["source_event_id"],
            "sources": get_knowledge_sources(
                "note",
                object_id
            ),
            "metadata": {
                "embedding_model": note["embedding_model"],
                "embedding_dimensions": note["embedding_dimensions"]
            }
        }

    if knowledge_type == "task":
        task = get_task_record(object_id)

        if task is None:
            return None

        return {
            "key": f"task:{object_id}",
            "type": "task",
            "id": object_id,
            "title": None,
            "content": task["content"],
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
            "archived": task["archived"],
            "source_event_id": task["source_event_id"],
            "sources": get_knowledge_sources(
                "task",
                object_id
            ),
            "metadata": {
                "due_at": task["due_at"],
                "status": task["status"],
                "priority": task["priority"],
                "urgency": task["urgency"],
                "percent_complete": task["percent_complete"],
                "embedding_model": task["embedding_model"],
                "embedding_dimensions": task["embedding_dimensions"]
            }
        }

    if knowledge_type == "list":
        item = get_list_record(object_id)

        if item is None:
            return None

        with get_db_connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    content,
                    created_at,
                    updated_at,
                    source_event_id,
                    status,
                    archived
                FROM list_items
                WHERE list_id = %s
                ORDER BY created_at ASC, id ASC
                """,
                (object_id,)
            ).fetchall()

        return {
            "key": f"list:{object_id}",
            "type": "list",
            "id": object_id,
            "title": item["title"],
            "content": item["description"],
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "archived": item["archived"],
            "source_event_id": None,
            "sources": get_knowledge_sources(
                "list",
                object_id
            ),
            "metadata": {
                "embedding_model": item["embedding_model"],
                "embedding_dimensions": item["embedding_dimensions"],
                "items": [
                    {
                        "key": f"list_item:{row[0]}",
                        "id": row[0],
                        "content": row[1],
                        "created_at": row[2].isoformat(),
                        "updated_at": row[3].isoformat(),
                        "source_event_id": row[4],
                        "status": row[5],
                        "archived": row[6]
                    }
                    for row in rows
                ]
            }
        }

    list_item = get_list_item_record(object_id)

    if list_item is None:
        return None

    parent = get_list_record(list_item["list_id"])

    return {
        "key": f"list_item:{object_id}",
        "type": "list_item",
        "id": object_id,
        "title": None,
        "content": list_item["content"],
        "created_at": list_item["created_at"],
        "updated_at": list_item["updated_at"],
        "archived": list_item["archived"],
        "source_event_id": list_item["source_event_id"],
        "sources": get_knowledge_sources(
            "list_item",
            object_id
        ),
        "metadata": {
            "status": list_item["status"],
            "embedding_model": list_item["embedding_model"],
            "embedding_dimensions": list_item["embedding_dimensions"],
            "parent": {
                "key": f"list:{list_item['list_id']}",
                "id": list_item["list_id"],
                "title": (
                    parent["title"]
                    if parent is not None
                    else None
                )
            }
        }
    }

def _trim_channel_candidates(
    candidates: list[dict],
    limit: int
):
    best_by_key = {}

    for candidate in candidates:
        key = candidate["key"]

        if (
            key not in best_by_key
            or candidate["score"] > best_by_key[key]["score"]
        ):
            best_by_key[key] = candidate

    ordered = sorted(
        best_by_key.values(),
        key=lambda item: item["score"],
        reverse=True
    )

    return ordered[:limit]

def _vector_channel_candidates(
    connection,
    selected_types: set[str],
    vector_value: str
):
    candidates = []

    if "note" in selected_types:
        rows = connection.execute(
            """
            SELECT
                id,
                1 - (embedding <=> %s::vector) AS score
            FROM notes
            WHERE archived = FALSE
              AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (
                vector_value,
                vector_value,
                HYBRID_CANDIDATE_LIMIT
            )
        ).fetchall()

        candidates.extend(
            {
                "key": f"note:{row[0]}",
                "score": float(row[1])
            }
            for row in rows
        )

    if "task" in selected_types:
        rows = connection.execute(
            """
            SELECT
                id,
                1 - (embedding <=> %s::vector) AS score
            FROM tasks
            WHERE archived = FALSE
              AND status = 'open'
              AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (
                vector_value,
                vector_value,
                HYBRID_CANDIDATE_LIMIT
            )
        ).fetchall()

        candidates.extend(
            {
                "key": f"task:{row[0]}",
                "score": float(row[1])
            }
            for row in rows
        )

    if "list" in selected_types:
        rows = connection.execute(
            """
            SELECT
                id,
                1 - (embedding <=> %s::vector) AS score
            FROM lists
            WHERE archived = FALSE
              AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (
                vector_value,
                vector_value,
                HYBRID_CANDIDATE_LIMIT
            )
        ).fetchall()

        candidates.extend(
            {
                "key": f"list:{row[0]}",
                "score": float(row[1])
            }
            for row in rows
        )

    if "list_item" in selected_types:
        rows = connection.execute(
            """
            SELECT
                li.id,
                1 - (li.embedding <=> %s::vector) AS score
            FROM list_items li
            JOIN lists l
              ON l.id = li.list_id
            WHERE li.archived = FALSE
              AND li.status = 'active'
              AND li.embedding IS NOT NULL
              AND l.archived = FALSE
            ORDER BY li.embedding <=> %s::vector
            LIMIT %s
            """,
            (
                vector_value,
                vector_value,
                HYBRID_CANDIDATE_LIMIT
            )
        ).fetchall()

        candidates.extend(
            {
                "key": f"list_item:{row[0]}",
                "score": float(row[1])
            }
            for row in rows
        )

    return _trim_channel_candidates(
        candidates,
        HYBRID_CANDIDATE_LIMIT
    )

def _fts_channel_candidates(
    connection,
    selected_types: set[str],
    query: str
):
    candidates = []

    if "note" in selected_types:
        rows = connection.execute(
            """
            SELECT
                id,
                ts_rank_cd(
                    to_tsvector('simple', content),
                    websearch_to_tsquery('simple', %s)
                ) AS score
            FROM notes
            WHERE archived = FALSE
              AND to_tsvector('simple', content)
                  @@ websearch_to_tsquery('simple', %s)
            ORDER BY score DESC
            LIMIT %s
            """,
            (
                query,
                query,
                HYBRID_CANDIDATE_LIMIT
            )
        ).fetchall()

        candidates.extend(
            {
                "key": f"note:{row[0]}",
                "score": float(row[1])
            }
            for row in rows
        )

    if "task" in selected_types:
        rows = connection.execute(
            """
            SELECT
                id,
                ts_rank_cd(
                    to_tsvector('simple', content),
                    websearch_to_tsquery('simple', %s)
                ) AS score
            FROM tasks
            WHERE archived = FALSE
              AND status = 'open'
              AND to_tsvector('simple', content)
                  @@ websearch_to_tsquery('simple', %s)
            ORDER BY score DESC
            LIMIT %s
            """,
            (
                query,
                query,
                HYBRID_CANDIDATE_LIMIT
            )
        ).fetchall()

        candidates.extend(
            {
                "key": f"task:{row[0]}",
                "score": float(row[1])
            }
            for row in rows
        )

    if "list" in selected_types:
        rows = connection.execute(
            """
            WITH searchable_lists AS (
                SELECT
                    l.id,
                    concat_ws(
                        ' ',
                        l.title,
                        l.description,
                        COALESCE(
                            (
                                SELECT string_agg(li.content, ' ')
                                FROM list_items li
                                WHERE li.list_id = l.id
                                  AND li.archived = FALSE
                                  AND li.status = 'active'
                            ),
                            ''
                        )
                    ) AS search_text
                FROM lists l
                WHERE l.archived = FALSE
            )
            SELECT
                id,
                ts_rank_cd(
                    to_tsvector('simple', search_text),
                    websearch_to_tsquery('simple', %s)
                ) AS score
            FROM searchable_lists
            WHERE to_tsvector('simple', search_text)
                  @@ websearch_to_tsquery('simple', %s)
            ORDER BY score DESC
            LIMIT %s
            """,
            (
                query,
                query,
                HYBRID_CANDIDATE_LIMIT
            )
        ).fetchall()

        candidates.extend(
            {
                "key": f"list:{row[0]}",
                "score": float(row[1])
            }
            for row in rows
        )

    if "list_item" in selected_types:
        rows = connection.execute(
            """
            SELECT
                li.id,
                ts_rank_cd(
                    to_tsvector(
                        'simple',
                        concat_ws(' ', l.title, li.content)
                    ),
                    websearch_to_tsquery('simple', %s)
                ) AS score
            FROM list_items li
            JOIN lists l
              ON l.id = li.list_id
            WHERE li.archived = FALSE
              AND li.status = 'active'
              AND l.archived = FALSE
              AND to_tsvector(
                    'simple',
                    concat_ws(' ', l.title, li.content)
                  )
                  @@ websearch_to_tsquery('simple', %s)
            ORDER BY score DESC
            LIMIT %s
            """,
            (
                query,
                query,
                HYBRID_CANDIDATE_LIMIT
            )
        ).fetchall()

        candidates.extend(
            {
                "key": f"list_item:{row[0]}",
                "score": float(row[1])
            }
            for row in rows
        )

    return _trim_channel_candidates(
        candidates,
        HYBRID_CANDIDATE_LIMIT
    )

def _trigram_score_sql(search_expression: str):
    return f"""
        GREATEST(
            similarity(
                lower({search_expression}),
                lower(%s)
            ),
            word_similarity(
                lower(%s),
                lower({search_expression})
            ),
            CASE
                WHEN position(
                    lower(%s)
                    in lower({search_expression})
                ) > 0
                THEN 1.0
                ELSE 0.0
            END
        )
    """

def _trigram_channel_candidates(
    connection,
    selected_types: set[str],
    query: str
):
    candidates = []

    if "note" in selected_types:
        score_sql = _trigram_score_sql("content")
        rows = connection.execute(
            f"""
            SELECT
                id,
                {score_sql} AS score
            FROM notes
            WHERE archived = FALSE
            ORDER BY score DESC
            LIMIT %s
            """,
            (
                query,
                query,
                query,
                HYBRID_CANDIDATE_LIMIT
            )
        ).fetchall()

        candidates.extend(
            {
                "key": f"note:{row[0]}",
                "score": float(row[1])
            }
            for row in rows
        )

    if "task" in selected_types:
        score_sql = _trigram_score_sql("content")
        rows = connection.execute(
            f"""
            SELECT
                id,
                {score_sql} AS score
            FROM tasks
            WHERE archived = FALSE
              AND status = 'open'
            ORDER BY score DESC
            LIMIT %s
            """,
            (
                query,
                query,
                query,
                HYBRID_CANDIDATE_LIMIT
            )
        ).fetchall()

        candidates.extend(
            {
                "key": f"task:{row[0]}",
                "score": float(row[1])
            }
            for row in rows
        )

    if "list" in selected_types:
        search_expression = "search_text"
        score_sql = _trigram_score_sql(search_expression)

        rows = connection.execute(
            f"""
            WITH searchable_lists AS (
                SELECT
                    l.id,
                    concat_ws(
                        ' ',
                        l.title,
                        l.description,
                        COALESCE(
                            (
                                SELECT string_agg(li.content, ' ')
                                FROM list_items li
                                WHERE li.list_id = l.id
                                  AND li.archived = FALSE
                                  AND li.status = 'active'
                            ),
                            ''
                        )
                    ) AS search_text
                FROM lists l
                WHERE l.archived = FALSE
            )
            SELECT
                id,
                {score_sql} AS score
            FROM searchable_lists
            ORDER BY score DESC
            LIMIT %s
            """,
            (
                query,
                query,
                query,
                HYBRID_CANDIDATE_LIMIT
            )
        ).fetchall()

        candidates.extend(
            {
                "key": f"list:{row[0]}",
                "score": float(row[1])
            }
            for row in rows
        )

    if "list_item" in selected_types:
        search_expression = "concat_ws(' ', l.title, li.content)"
        score_sql = _trigram_score_sql(search_expression)

        rows = connection.execute(
            f"""
            SELECT
                li.id,
                {score_sql} AS score
            FROM list_items li
            JOIN lists l
              ON l.id = li.list_id
            WHERE li.archived = FALSE
              AND li.status = 'active'
              AND l.archived = FALSE
            ORDER BY score DESC
            LIMIT %s
            """,
            (
                query,
                query,
                query,
                HYBRID_CANDIDATE_LIMIT
            )
        ).fetchall()

        candidates.extend(
            {
                "key": f"list_item:{row[0]}",
                "score": float(row[1])
            }
            for row in rows
        )

    return _trim_channel_candidates(
        candidates,
        HYBRID_CANDIDATE_LIMIT
    )

def _add_rrf_channel(
    fused: dict,
    channel_name: str,
    candidates: list[dict]
):
    for rank, candidate in enumerate(
        candidates,
        start=1
    ):
        key = candidate["key"]

        entry = fused.setdefault(
            key,
            {
                "key": key,
                "rrf_score": 0.0,
                "ranks": {},
                "scores": {}
            }
        )

        entry["ranks"][channel_name] = rank
        entry["scores"][channel_name] = candidate["score"]
        entry["rrf_score"] += (
            1.0 / (HYBRID_RRF_K + rank)
        )

def _hybrid_candidate_is_relevant(
    entry: dict,
    min_similarity: float
):
    scores = entry["scores"]

    vector_score = scores.get("vector")
    fts_score = scores.get("fts")
    trigram_score = scores.get("trigram")

    semantic_match = (
        vector_score is not None
        and vector_score >= min_similarity
    )

    lexical_match = (
        fts_score is not None
        and fts_score > 0
    )

    trigram_match = (
        trigram_score is not None
        and trigram_score >= HYBRID_TRIGRAM_MIN_SCORE
    )

    return (
        semantic_match
        or lexical_match
        or trigram_match
    )

def _knowledge_search_result_from_record(
    record: dict,
    fusion: dict
):
    metadata = record.get("metadata") or {}
    vector_score = fusion["scores"].get("vector")

    result = {
        "key": record["key"],
        "type": record["type"],
        "id": record["id"],
        "title": record["title"],
        "content": record["content"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "source_event_id": record["source_event_id"],
        "embedding_model": metadata.get(
            "embedding_model"
        ),
        # Backward-compatible field: this remains the semantic
        # cosine similarity, not the final hybrid rank.
        "similarity": (
            float(vector_score)
            if vector_score is not None
            else 0.0
        ),
        "rrf_score": fusion["rrf_score"],
        "retrieval": {
            "mode": "hybrid_rrf",
            "ranks": fusion["ranks"],
            "scores": fusion["scores"],
            "stage":next((stage for stage in ("exact","fts","trigram","vector") if stage in fusion["scores"]),None)
        },
        "record":record,
        "sources":record.get("sources",[]),
        "topics":get_knowledge_topic_links(record["type"],record["id"]),
    }

    if record["type"] == "task":
        result["due_at"] = metadata.get("due_at")
        result["status"] = metadata.get("status")
        result["priority"] = metadata.get("priority",0)
        result["urgency"] = metadata.get("urgency",0.5)
        result["percent_complete"] = metadata.get("percent_complete",0)

    elif record["type"] == "list":
        result["items"] = metadata.get("items", [])

    elif record["type"] == "list_item":
        result["status"] = metadata.get("status")

        parent = metadata.get("parent") or {}

        result["parent"] = {
            "type": "list",
            "id": parent.get("id"),
            "title": parent.get("title")
        }

    return result

async def search_knowledge(
    query: str,
    limit: int = KNOWLEDGE_RETRIEVAL_LIMIT,
    types: list[str] | None = None,
    min_similarity: float | None = KNOWLEDGE_RETRIEVAL_MIN_SIMILARITY
):
    allowed_types = {
        "note",
        "task",
        "list",
        "list_item"
    }

    if types is None:
        selected_types = allowed_types
    else:
        selected_types = {
            item.strip().lower()
            for item in types
            if item.strip()
        }

        invalid_types = selected_types - allowed_types

        if invalid_types:
            raise ValueError(
                "Unsupported knowledge types: "
                + ", ".join(sorted(invalid_types))
            )

        if not selected_types:
            selected_types = allowed_types

    limit = max(
        1,
        min(
            limit,
            KNOWLEDGE_RETRIEVAL_LIMIT
        )
    )

    if min_similarity is None:
        min_similarity = KNOWLEDGE_RETRIEVAL_MIN_SIMILARITY

    query = query.strip()

    if not query:
        return []

    with get_db_connection() as connection:
        cache_key,cache_request=_cache_identity(connection,query,selected_types,limit,min_similarity)
        cached=connection.execute("""SELECT result_refs FROM retrieval_cache WHERE cache_key=%s AND knowledge_version=%s
        AND expires_at>%s""",(cache_key,cache_request['knowledge_version'],datetime.now(TIMEZONE))).fetchone()
        if cached:
            connection.execute("UPDATE retrieval_cache SET hit_count=hit_count+1,last_hit_at=%s WHERE cache_key=%s",
                (datetime.now(TIMEZONE),cache_key));connection.commit()
    if cached:
        results=[]
        for fusion in cached[0]:
            record=get_knowledge_record(fusion['key'])
            if record:
                result=_knowledge_search_result_from_record(record,fusion);result['retrieval']['cache_hit']=True;results.append(result)
        return results

    with get_db_connection() as connection:
        exact_candidates=_exact_channel_candidates(connection,selected_types,query)
        fts_candidates = _fts_channel_candidates(
            connection,
            selected_types,
            query
        )

        trigram_candidates = _trigram_channel_candidates(
            connection,
            selected_types,
            query
        )

    fused = {};_add_rrf_channel(fused,"exact",exact_candidates)
    _add_rrf_channel(
        fused,
        "fts",
        fts_candidates
    )
    _add_rrf_channel(
        fused,
        "trigram",
        trigram_candidates
    )

    # Embeddings are the final retrieval stage, not an unconditional cost.
    lexical_relevant=[entry for entry in fused.values() if _hybrid_candidate_is_relevant(entry,min_similarity)]
    # An exact identity/title/content match is terminal: do not spend energy
    # filling the response with weaker semantic neighbors.
    vector_used=not exact_candidates and len(lexical_relevant)<limit
    if vector_used:
        embedding=await get_query_embedding(query);vector_value=embedding_to_pgvector(embedding)
        with get_db_connection() as connection:vector_candidates=_vector_channel_candidates(connection,selected_types,vector_value)
        _add_rrf_channel(fused,"vector",vector_candidates)

    relevant = [
        entry
        for entry in fused.values()
        if _hybrid_candidate_is_relevant(
            entry,
            min_similarity
        )
    ]

    relevant.sort(
        key=lambda entry: (
            entry["rrf_score"],
            entry["scores"].get("fts", 0.0),
            entry["scores"].get("trigram", 0.0),
            entry["scores"].get("vector", -1.0)
        ),
        reverse=True
    )

    results = [];result_refs=[]

    for fusion in relevant[:limit]:
        record = get_knowledge_record(
            fusion["key"]
        )

        if record is None:
            continue

        results.append(
            _knowledge_search_result_from_record(
                record,
                fusion
            )
        )
        results[-1]['retrieval']['cache_hit']=False;result_refs.append(fusion)

    now=datetime.now(TIMEZONE)
    with get_db_connection() as connection:
        connection.execute("""INSERT INTO retrieval_cache(cache_key,query_hash,knowledge_version,retrieval_version,embedding_model,
        request_metadata,result_refs,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)
        ON CONFLICT(cache_key) DO UPDATE SET result_refs=EXCLUDED.result_refs,created_at=EXCLUDED.created_at,expires_at=EXCLUDED.expires_at""",
        (cache_key,cache_request['query_hash'],cache_request['knowledge_version'],RETRIEVAL_VERSION,EMBEDDING_MODEL,
        json.dumps({k:v for k,v in cache_request.items() if k!='query_hash'}),json.dumps(result_refs),now,
        now+timedelta(hours=RETRIEVAL_CACHE_TTL_HOURS)));connection.commit()

    return results
