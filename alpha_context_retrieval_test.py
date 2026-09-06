"""Regression for incremental topics and full-record efficiency-ladder retrieval."""
import asyncio,hashlib,uuid
from datetime import datetime

from smart_notebook.config import EMBEDDING_DIMENSIONS,TIMEZONE
from smart_notebook.database import get_db_connection
from smart_notebook.services.ingestion import create_ingestion_session_record
from smart_notebook.services.lists import create_list_record,add_list_item_record
from smart_notebook.services.retrieval import search_knowledge
from smart_notebook.services.topic_detection import detect_topics_for_segments

async def main():
    token=uuid.uuid4().hex[:8];session_id=None;list_id=None
    try:
        session_id=create_ingestion_session_record("topic-retrieval-regression",source="alpha_context_retrieval_test.py")["id"]
        texts=(f"Im heutigen Meeting geht es um das Projekt Zephyr{token}.",f"Für das Projekt Zephyr{token} prüfen wir die Zeichnungen.",
            "Maria übernimmt anschließend die technische Kontrolle.")
        now=datetime.now(TIMEZONE);segments=[]
        with get_db_connection() as c:
            for sequence,text in enumerate(texts,1):
                chunk=c.execute("""INSERT INTO ingestion_chunks(session_id,sequence,client_chunk_id,text,content_hash,created_at)
                VALUES(%s,%s,%s,%s,%s,%s) RETURNING id""",(session_id,sequence,f"topic-{token}-{sequence}",text,hashlib.sha256(text.encode()).hexdigest(),now)).fetchone()[0]
                row=c.execute("""INSERT INTO semantic_segments(session_id,chunk_id,sequence,segment_index,segment_type,text,confidence,
                context_before,content_hash,processor_type,status,created_at,updated_at) VALUES(%s,%s,%s,1,'statement',%s,1,'',%s,
                'regression','confirmed',%s,%s) RETURNING id""",(session_id,chunk,sequence,text,hashlib.sha256(text.encode()).hexdigest(),now,now)).fetchone()[0]
                segments.append({"id":row,"text":text,"status":"confirmed"})
            c.commit()
        matches=await detect_topics_for_segments(session_id,segments);assert len(matches)==3,matches
        assert len({m["topic_id"] for m in matches})==1,matches
        assert [m["match_mode"] for m in matches[:2]]==["explicit","explicit"] and matches[2]["match_mode"] in {"embedding","context_inherited"},matches
        with get_db_connection() as c:
            assert c.execute("SELECT count(*) FROM session_topic_evidence WHERE session_id=%s",(session_id,)).fetchone()[0]==3
            # Repetition alone must not create durable knowledge.
            assert c.execute("SELECT 1 FROM knowledge_topics WHERE normalized_key=%s",(f"projekt-zephyr{token}",)).fetchone() is None

        title=f"RegressionList{token}";zero=[0.0]*EMBEDDING_DIMENSIONS
        list_id=await create_list_record(title,"Vollständige Dashboard-Liste",embedding_vector=zero)
        for index in range(25):await add_list_item_record(list_id,f"Eintrag {index+1}",embedding_vector=zero,refresh_embedding=False)
        results=await search_knowledge(title,limit=5,types=["list"])
        assert results and results[0]["id"]==list_id,results
        result=results[0];assert result["retrieval"]["stage"]=="exact",result["retrieval"]
        assert "vector" not in result["retrieval"]["scores"],result["retrieval"]
        assert result["retrieval"]["cache_hit"] is False
        assert len(result["record"]["metadata"]["items"])==25 and len(result["items"])==25
        assert result["sources"]==result["record"]["sources"] and "topics" in result
        cached=await search_knowledge(title,limit=5,types=["list"])
        assert cached[0]["retrieval"]["cache_hit"] is True
        await add_list_item_record(list_id,"Eintrag 26",embedding_vector=zero,refresh_embedding=False)
        invalidated=await search_knowledge(title,limit=5,types=["list"])
        assert invalidated[0]["retrieval"]["cache_hit"] is False and len(invalidated[0]["items"])==26
        print("ALPHA CONTEXT/RETRIEVAL TEST: PASS")
    finally:
        with get_db_connection() as c:
            if list_id is not None:c.execute("DELETE FROM lists WHERE id=%s",(list_id,))
            if session_id is not None:c.execute("DELETE FROM ingestion_sessions WHERE id=%s",(session_id,))
            c.commit()

if __name__=="__main__":asyncio.run(main())
