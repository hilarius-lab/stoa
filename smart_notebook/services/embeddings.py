# Embedding service
import httpx

from ..config import EMBEDDING_URL, EMBEDDING_MODEL, EMBEDDING_DIMENSIONS

async def get_embedding(text: str):
    payload = {
        "model": EMBEDDING_MODEL,
        "input": text
    }

    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        response = await client.post(
            EMBEDDING_URL,
            json=payload
        )
        response.raise_for_status()

    data = response.json()
    embedding = data["data"][0]["embedding"]

    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Unexpected embedding size: {len(embedding)} "
            f"(expected {EMBEDDING_DIMENSIONS})"
        )

    return embedding

async def get_query_embedding(query: str):
    instructed_query = (
        "Instruct: Retrieve personal notes that are relevant to the user's query.\n"
        f"Query: {query}"
    )

    return await get_embedding(instructed_query)

def embedding_to_pgvector(embedding: list[float]):
    return "[" + ",".join(str(value) for value in embedding) + "]"
