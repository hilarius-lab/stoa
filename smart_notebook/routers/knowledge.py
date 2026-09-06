# Knowledge routes
from fastapi import APIRouter, HTTPException

from ..config import HYBRID_CANDIDATE_LIMIT, HYBRID_RRF_K, HYBRID_TRIGRAM_MIN_SCORE

from ..schemas import KnowledgeSearch
from ..services.retrieval import parse_knowledge_key, get_knowledge_record, search_knowledge
from ..services.provenance import get_knowledge_sources
from ..services.activity import record_activity

router = APIRouter()

@router.get("/api/knowledge/{key}/sources")
async def api_get_knowledge_sources(key: str):
    try:
        knowledge_type, object_id = parse_knowledge_key(key)
        item = get_knowledge_record(key)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

    if item is None:
        raise HTTPException(
            status_code=404,
            detail="Knowledge object not found"
        )

    sources = get_knowledge_sources(
        knowledge_type,
        object_id
    )

    return {
        "key": key,
        "count": len(sources),
        "sources": sources
    }

@router.get("/api/knowledge/{key}")
async def api_get_knowledge(key: str):
    try:
        item = get_knowledge_record(key)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

    if item is None:
        raise HTTPException(
            status_code=404,
            detail="Knowledge object not found"
        )

    record_activity(item["type"],item["id"],"opened",metadata={"endpoint":"knowledge"})

    return item

@router.post("/api/search-knowledge")
async def api_search_knowledge(search: KnowledgeSearch):
    try:
        results = await search_knowledge(
            query=search.query,
            limit=search.limit,
            types=search.types,
            min_similarity=search.min_similarity
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc

    for rank,item in enumerate(results,start=1):
        record_activity(item["type"],item["id"],"retrieved",metadata={"query":search.query,"rank":rank,"retrieval_mode":"efficiency_ladder"})

    return {
        "query": search.query,
        "types": (
            search.types
            if search.types is not None
            else [
                "note",
                "task",
                "list",
                "list_item"
            ]
        ),
        "min_similarity": search.min_similarity,
        "retrieval_mode": "efficiency_ladder",
        "stages_used":list(dict.fromkeys(stage for item in results for stage in item["retrieval"]["scores"])),
        "llm_synthesis":False,
        "candidate_limit_per_channel": HYBRID_CANDIDATE_LIMIT,
        "rrf_k": HYBRID_RRF_K,
        "trigram_min_score": HYBRID_TRIGRAM_MIN_SCORE,
        "count": len(results),
        "results": results
    }
