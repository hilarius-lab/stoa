"""Change-based exact consolidation and mutation-free local-LLM semantic reviews."""
from datetime import datetime
import hashlib,json,math,re

import httpx
from psycopg.types.json import Jsonb

from ..config import (NIGHTLY_KNOWLEDGE_SEMANTIC_MIN_SIMILARITY,
    NIGHTLY_TOPIC_SEMANTIC_MIN_SIMILARITY,TIMEZONE)
from ..database import get_db_connection
from .ai_tasks import get_ai_task_profile
from .provenance import transfer_knowledge_sources
from .observability import emit_event

REVIEW_VERSION="nightly-semantic-review-v1"

def normalize_exact(value):return re.sub(r"[^\wäöüß]+"," ",value.casefold()).strip()

def _exact_groups():
    specs=(
        ("note","SELECT id,content FROM notes WHERE archived=FALSE ORDER BY id"),
        ("task","SELECT id,content,due_at,status,urgency,priority FROM tasks WHERE archived=FALSE ORDER BY id"),
        ("list_item","SELECT id,content,list_id FROM list_items WHERE archived=FALSE AND status='active' ORDER BY id"),
    );groups=[]
    with get_db_connection() as c:
        for kind,sql in specs:
            rows=c.execute(sql).fetchall();bucket={}
            for row in rows:
                structural=tuple(str(x) for x in row[2:]);key=(normalize_exact(row[1]),structural)
                if key[0]:bucket.setdefault(key,[]).append((row[0],row[1]))
            for _,items in bucket.items():
                if len(items)>1:
                    ranked=[]
                    for item_id,content in items:
                        sources=c.execute("SELECT count(*) FROM knowledge_sources WHERE knowledge_type=%s AND knowledge_id=%s",(kind,item_id)).fetchone()[0]
                        evidence=c.execute("""SELECT count(*) FROM artifact_knowledge_links l JOIN evidence_quotes e ON e.artifact_id=l.artifact_id
                        WHERE l.knowledge_type=%s AND l.knowledge_id=%s""",(kind,item_id)).fetchone()[0]
                        ranked.append((item_id,content,sources,evidence))
                    ranked.sort(key=lambda x:(-x[3],-len(x[1]),-x[2],x[0]));groups.append({"type":kind,"canonical_id":ranked[0][0],
                        "duplicate_ids":[x[0] for x in ranked[1:]],"normalized":normalize_exact(ranked[0][1])})
    return groups

def _apply_exact_group(group,run_id):
    kind=group['type'];canonical=group['canonical_id'];duplicates=group['duplicate_ids'];now=datetime.now(TIMEZONE)
    transfer_knowledge_sources(kind,canonical,duplicates)
    with get_db_connection() as c:
        for duplicate in duplicates:
            c.execute("""INSERT INTO knowledge_supersessions(knowledge_type,original_id,canonical_id,reason,consolidation_run_id,created_at)
            VALUES(%s,%s,%s,'exact_normalized_duplicate',%s,%s) ON CONFLICT(knowledge_type,original_id) DO NOTHING""",
            (kind,duplicate,canonical,run_id,now))
        if kind=='note':c.execute("UPDATE notes SET archived=TRUE,updated_at=%s WHERE id=ANY(%s)",(now,duplicates))
        elif kind=='task':c.execute("UPDATE tasks SET archived=TRUE,status='archived',updated_at=%s WHERE id=ANY(%s)",(now,duplicates))
        else:c.execute("UPDATE list_items SET archived=TRUE,status='archived',updated_at=%s WHERE id=ANY(%s)",(now,duplicates))
        # Artifact links remain attached to immutable originals. The supersession row
        # resolves the active canonical record without erasing provenance.
        c.execute("""INSERT INTO knowledge_topic_links(knowledge_type,knowledge_id,topic_id,relation,link_origin,confidence,created_at)
        SELECT knowledge_type,%s,topic_id,relation,link_origin,confidence,%s FROM knowledge_topic_links
        WHERE knowledge_type=%s AND knowledge_id=ANY(%s) ON CONFLICT(knowledge_type,knowledge_id,topic_id,relation)
        DO UPDATE SET confidence=GREATEST(knowledge_topic_links.confidence,EXCLUDED.confidence)""",(canonical,now,kind,duplicates))
        c.execute("DELETE FROM knowledge_topic_links WHERE knowledge_type=%s AND knowledge_id=ANY(%s)",(kind,duplicates));c.commit()

def _normalization_aliases(dry_run):
    with get_db_connection() as c:rows=c.execute("""SELECT t.id,t.title,t.normalized_key FROM knowledge_topics t
        WHERE NOT EXISTS(SELECT 1 FROM topic_aliases a WHERE a.topic_id=t.id AND a.normalized_alias=t.normalized_key)
        ORDER BY t.id""").fetchall()
    actions=[{"topic_id":r[0],"alias":r[1],"normalized_alias":r[2]} for r in rows]
    if not dry_run:
        now=datetime.now(TIMEZONE)
        with get_db_connection() as c:
            for item in actions:c.execute("""INSERT INTO topic_aliases(topic_id,alias,normalized_alias,source_kind,status,confidence,created_at)
            VALUES(%s,%s,%s,'normalization','active',1,%s) ON CONFLICT(topic_id,normalized_alias) DO NOTHING""",
            (item['topic_id'],item['alias'],item['normalized_alias'],now))
            c.commit()
    return actions

def _semantic_candidates(limit=40):
    candidates=[]
    specs=(('note','notes','content',"archived=FALSE"),('task','tasks','content',"archived=FALSE"),
        ('list','lists',"concat_ws(' ',title,description)","archived=FALSE"),('list_item','list_items','content',"archived=FALSE AND status='active'"))
    with get_db_connection() as c:
        for kind,table,content,where in specs:
            where_a="a."+where.replace(" AND "," AND a.");where_b="b."+where.replace(" AND "," AND b.")
            rows=c.execute(f"""SELECT a.id,{content.replace('title','a.title').replace('description','a.description') if table=='lists' else 'a.'+content},
            b.id,{content.replace('title','b.title').replace('description','b.description') if table=='lists' else 'b.'+content},1-(a.embedding<=>b.embedding) score
            FROM {table} a JOIN {table} b ON a.id<b.id WHERE {where_a} AND {where_b} AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL
            AND 1-(a.embedding<=>b.embedding)>=%s ORDER BY score DESC LIMIT %s""",(NIGHTLY_KNOWLEDGE_SEMANTIC_MIN_SIMILARITY,limit)).fetchall()
            for a_id,a_text,b_id,b_text,score in rows:
                if score is None or not math.isfinite(float(score)):continue
                if normalize_exact(a_text)==normalize_exact(b_text):continue
                candidates.append({"kind":"knowledge_duplicate","knowledge_type":kind,"left_id":a_id,"left_text":a_text,
                    "right_id":b_id,"right_text":b_text,"similarity":float(score)})
        rows=c.execute("""SELECT a.id,a.title,b.id,b.title,1-(a.embedding<=>b.embedding) score FROM knowledge_topics a
        JOIN knowledge_topics b ON a.id<b.id WHERE a.embedding IS NOT NULL AND b.embedding IS NOT NULL
        AND 1-(a.embedding<=>b.embedding)>=%s ORDER BY score DESC LIMIT %s""",(NIGHTLY_TOPIC_SEMANTIC_MIN_SIMILARITY,limit)).fetchall()
        for a_id,a_title,b_id,b_title,score in rows:
            if score is None or not math.isfinite(float(score)):continue
            candidates.append({"kind":"topic_relation","left_id":a_id,"left_text":a_title,
                "right_id":b_id,"right_text":b_title,"similarity":float(score)})
    for item in candidates:item['fingerprint']=hashlib.sha256(json.dumps({**item,"review":REVIEW_VERSION},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return candidates[:limit]

async def _review_candidates(candidates):
    if not candidates:return []
    profile=get_ai_task_profile('consolidation.daily')
    schema={"type":"object","properties":{"reviews":{"type":"array","items":{"type":"object","properties":{
        "fingerprint":{"type":"string"},"decision":{"type":"string","enum":["merge","synthesize","alias","hierarchy","keep_separate"]},
        "synthesized_content":{"type":"string"},"canonical_title":{"type":"string"},"parent_title":{"type":"string"},"child_title":{"type":"string"},
        "reason":{"type":"string"}},"required":["fingerprint","decision","synthesized_content","canonical_title","parent_title","child_title","reason"],
        "additionalProperties":False}}},"required":["reviews"],"additionalProperties":False}
    prompt="""Du prüfst nachts semantisch ähnliche lokale Knowledge- oder Topic-Paare. Ähnlichkeit allein ist kein Duplikat.
Für Knowledge: merge nur bei gleichem Sachverhalt, synthesize wenn eine neue vollständige Summe/Kompromiss beide Originale sinnvoll referenzieren würde,
sonst keep_separate. Für Topics: alias nur bei echter Synonymie, hierarchy nur bei echter Ober-/Unterordnung, sonst keep_separate.
Verwandte Fachgebiete (z.B. Hämatologie und Hämatoonkologie) sind weder automatisch Alias noch identisch. Erfinde nichts.
Alle Entscheidungen sind Alpha-Shadow und verändern keine Daten."""
    payload={"model":profile['model'],"messages":[{"role":"system","content":prompt},{"role":"user","content":json.dumps(candidates,ensure_ascii=False)}],
        "temperature":profile['temperature'],"response_format":{"type":"json_schema","json_schema":{"name":"nightly_semantic_review","strict":True,"schema":schema}}}
    async with httpx.AsyncClient(timeout=profile['timeout_seconds'],trust_env=False) as client:r=await client.post(profile['endpoint'],json=payload)
    r.raise_for_status();reviews=json.loads(r.json()['choices'][0]['message']['content'])['reviews'];by_fp={x['fingerprint']:x for x in reviews}
    return [by_fp[x['fingerprint']] for x in candidates if x['fingerprint'] in by_fp]

async def run_nightly_knowledge_consolidation(dry_run=False,semantic_review=True,limit=40):
    now=datetime.now(TIMEZONE);profile=get_ai_task_profile('consolidation.daily')
    with get_db_connection() as c:run_id=c.execute("""INSERT INTO nightly_consolidation_runs(dry_run,status,model,created_at)
        VALUES(%s,'running',%s,%s) RETURNING id""",(dry_run,profile['model'],now)).fetchone()[0];c.commit()
    try:
        exact=_exact_groups();aliases=_normalization_aliases(dry_run)
        if not dry_run:
            for group in exact:_apply_exact_group(group,run_id)
        candidates=_semantic_candidates(limit)
        with get_db_connection() as c:existing={r[0] for r in c.execute("SELECT fingerprint FROM nightly_consolidation_candidates WHERE model=%s",(profile['model'],)).fetchall()}
        candidates=[item for item in candidates if item['fingerprint'] not in existing]
        reviews=await _review_candidates(candidates) if semantic_review else [];review_by={r['fingerprint']:r for r in reviews}
        with get_db_connection() as c:
            for item in candidates:
                review=review_by.get(item['fingerprint']);decision=review['decision'] if review else None
                proposal=({"entity_type":item.get('knowledge_type'),"content":review['synthesized_content'],
                    "source_refs":[{"id":item['left_id']},{"id":item['right_id']}]} if review and decision=='synthesize' else (review or {}))
                c.execute("""INSERT INTO nightly_consolidation_candidates(run_id,candidate_kind,fingerprint,source_refs,similarity,
                model_decision,proposed_entity,reason,status,model,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'shadow',%s,%s)
                ON CONFLICT(fingerprint,model) DO NOTHING""",(run_id,item['kind'],item['fingerprint'],Jsonb({k:v for k,v in item.items() if k!='fingerprint'}),
                item['similarity'],decision,Jsonb(proposal),review['reason'] if review else None,profile['model'],now))
            summary={"exact_groups":len(exact),"exact_duplicates":sum(len(x['duplicate_ids']) for x in exact),"exact_applied":0 if dry_run else sum(len(x['duplicate_ids']) for x in exact),
                "normalization_aliases":len(aliases),"normalization_aliases_applied":0 if dry_run else len(aliases),
                "semantic_candidates":len(candidates),"model_reviews":len(reviews),"semantic_mutations":0,"review_version":REVIEW_VERSION}
            c.execute("UPDATE nightly_consolidation_runs SET status='completed',summary=%s,completed_at=%s WHERE id=%s",(Jsonb(summary),datetime.now(TIMEZONE),run_id));c.commit()
        emit_event("nightly_consolidation","completed",metadata={"run_id":run_id,**summary})
        return {"run_id":run_id,"dry_run":dry_run,"summary":summary,"exact_actions":exact,"alias_actions":aliases,"semantic_reviews":reviews}
    except Exception as exc:
        with get_db_connection() as c:c.execute("UPDATE nightly_consolidation_runs SET status='failed',summary=%s,completed_at=%s WHERE id=%s",
            (Jsonb({"error_type":type(exc).__name__}),datetime.now(TIMEZONE),run_id));c.commit()
        raise
