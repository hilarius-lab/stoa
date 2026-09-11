from datetime import datetime

from .config import TIMEZONE
from .database import get_db_connection


MIGRATIONS=[
    ("0002_task_due_or_urgency","Allow undated tasks only with explicit urgency",[
        "ALTER TABLE tasks ALTER COLUMN urgency DROP DEFAULT",
        "ALTER TABLE tasks ALTER COLUMN urgency DROP NOT NULL",
        "UPDATE tasks SET urgency=0.5 WHERE due_at IS NULL AND urgency IS NULL",
        """DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='tasks_due_or_urgency_check') THEN
        ALTER TABLE tasks ADD CONSTRAINT tasks_due_or_urgency_check CHECK(due_at IS NOT NULL OR urgency IS NOT NULL); END IF; END $$""",
    ]),
    ("0003_audio_foundation","Audio chunks and transcript revisions",[
        """CREATE TABLE audio_chunks(
        id BIGSERIAL PRIMARY KEY,session_id BIGINT NOT NULL REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
        sequence BIGINT NOT NULL,client_chunk_id TEXT NOT NULL,storage_key TEXT NOT NULL UNIQUE,
        content_hash TEXT NOT NULL,byte_length BIGINT NOT NULL,mime_type TEXT NOT NULL,codec TEXT,
        sample_rate_hz INTEGER,channels INTEGER,duration_ms BIGINT NOT NULL,
        source_start_ms BIGINT NOT NULL,source_end_ms BIGINT NOT NULL,captured_at TIMESTAMPTZ,
        status TEXT NOT NULL DEFAULT 'stored',retain_until TIMESTAMPTZ,retain_permanently BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        UNIQUE(session_id,sequence),UNIQUE(session_id,client_chunk_id),
        CHECK(sequence>=1),CHECK(byte_length>0),CHECK(duration_ms>0),CHECK(source_start_ms>=0),
        CHECK(source_end_ms>source_start_ms),CHECK(status IN('stored','queued','transcribing','transcribed','failed','deleted')))""",
        "CREATE INDEX audio_chunks_session_idx ON audio_chunks(session_id,sequence)",
        """CREATE TABLE audio_chunk_processing(
        audio_chunk_id BIGINT PRIMARY KEY REFERENCES audio_chunks(id) ON DELETE CASCADE,
        processing_job_id BIGINT REFERENCES processing_jobs(id) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,
        processor TEXT,model TEXT,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(status IN('pending','queued','running','done','failed')))""",
        """CREATE TABLE transcript_windows(
        id BIGSERIAL PRIMARY KEY,session_id BIGINT NOT NULL REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
        window_index INTEGER NOT NULL,source_start_ms BIGINT NOT NULL,source_end_ms BIGINT NOT NULL,
        status TEXT NOT NULL DEFAULT 'provisional',processor TEXT NOT NULL,model TEXT NOT NULL,language TEXT,
        raw_response JSONB,processing_job_id BIGINT REFERENCES processing_jobs(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        UNIQUE(session_id,window_index),CHECK(status IN('provisional','confirmed','superseded','failed')))""",
        """CREATE TABLE transcript_window_chunks(
        window_id BIGINT REFERENCES transcript_windows(id) ON DELETE CASCADE,
        audio_chunk_id BIGINT REFERENCES audio_chunks(id) ON DELETE CASCADE,
        PRIMARY KEY(window_id,audio_chunk_id))""",
        """CREATE TABLE transcript_segments(
        id BIGSERIAL PRIMARY KEY,window_id BIGINT NOT NULL REFERENCES transcript_windows(id) ON DELETE CASCADE,
        session_id BIGINT NOT NULL REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
        segment_index INTEGER NOT NULL,text TEXT NOT NULL,source_start_ms BIGINT NOT NULL,source_end_ms BIGINT NOT NULL,
        confidence DOUBLE PRECISION,status TEXT NOT NULL DEFAULT 'provisional',content_hash TEXT NOT NULL,
        superseded_by_segment_id BIGINT REFERENCES transcript_segments(id) ON DELETE SET NULL,
        materialized_chunk_id BIGINT REFERENCES ingestion_chunks(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        UNIQUE(window_id,segment_index),CHECK(status IN('provisional','confirmed','superseded')),
        CHECK(source_end_ms>source_start_ms))""",
        "CREATE INDEX transcript_segments_session_idx ON transcript_segments(session_id,source_start_ms,status)",
    ]),
    ("0004_artifact_promotion","Durable knowledge promotion links",[
        "ALTER TABLE session_artifacts ADD COLUMN promoted_knowledge_type TEXT",
        "ALTER TABLE session_artifacts ADD COLUMN promoted_knowledge_id BIGINT",
        "ALTER TABLE session_artifacts ADD COLUMN promoted_at TIMESTAMPTZ",
        "ALTER TABLE session_artifacts ADD COLUMN promotion_error TEXT",
        """CREATE TABLE artifact_knowledge_links(
        artifact_id BIGINT PRIMARY KEY REFERENCES session_artifacts(id) ON DELETE CASCADE,
        knowledge_type TEXT NOT NULL,knowledge_id BIGINT NOT NULL,created_at TIMESTAMPTZ NOT NULL,
        CHECK(knowledge_type IN('note','task','list','list_item')),
        UNIQUE(knowledge_type,knowledge_id))""",
    ]),
    ("0005_semantic_router","Validated artifact classification metadata",[
        """CREATE TABLE artifact_classifications(
        artifact_id BIGINT PRIMARY KEY REFERENCES session_artifacts(id) ON DELETE CASCADE,
        candidate_type TEXT NOT NULL,alternative_type TEXT,
        normalized_data JSONB NOT NULL DEFAULT '{}'::jsonb,
        evidence_spans JSONB NOT NULL DEFAULT '[]'::jsonb,
        reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        missing_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
        confidence DOUBLE PRECISION NOT NULL,decision_source TEXT NOT NULL,
        abstained BOOLEAN NOT NULL DEFAULT FALSE,validated BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(candidate_type IN('note','fact','decision','task','list','list_item','question')),
        CHECK(alternative_type IS NULL OR alternative_type IN('note','fact','decision','task','list','list_item','question')),
        CHECK(confidence>=0 AND confidence<=1),
        CHECK(decision_source IN('rules','embedding','llm','policy_default','hybrid')))""",
        "CREATE INDEX artifact_classifications_type_idx ON artifact_classifications(candidate_type,validated,confidence)",
    ]),
    ("0006_task_urgency_source","Track whether urgency was explicit, inferred or policy default",[
        "ALTER TABLE tasks ADD COLUMN urgency_source TEXT",
        """ALTER TABLE tasks ADD CONSTRAINT tasks_urgency_source_check CHECK(
        urgency_source IS NULL OR urgency_source IN('explicit','inferred','policy_default','manual'))""",
    ]),
    ("0007_claim_conflict_foundation","Atomic claims, evidence, relations and conflict cases",[
        """CREATE TABLE claims(
        id BIGSERIAL PRIMARY KEY,claim_type TEXT NOT NULL,statement TEXT NOT NULL,
        subject TEXT NOT NULL,normalized_subject TEXT NOT NULL,predicate TEXT NOT NULL,
        object_value TEXT,polarity TEXT NOT NULL DEFAULT 'positive',modality TEXT NOT NULL DEFAULT 'asserted',
        valid_from TIMESTAMPTZ,valid_until TIMESTAMPTZ,status TEXT NOT NULL DEFAULT 'active',
        confidence DOUBLE PRECISION NOT NULL,source_knowledge_type TEXT,source_knowledge_id BIGINT,
        derived BOOLEAN NOT NULL DEFAULT FALSE,metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(claim_type IN('fact','opinion','prediction','requirement','decision')),
        CHECK(polarity IN('positive','negative')),
        CHECK(modality IN('asserted','required','probable','possible','uncertain')),
        CHECK(status IN('active','disputed','superseded','retracted')),
        CHECK(confidence>=0 AND confidence<=1),CHECK(valid_until IS NULL OR valid_from IS NULL OR valid_until>=valid_from))""",
        "CREATE INDEX claims_comparison_idx ON claims(normalized_subject,predicate,status)",
        """CREATE TABLE claim_evidence(
        id BIGSERIAL PRIMARY KEY,claim_id BIGINT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
        evidence_quote_id BIGINT REFERENCES evidence_quotes(id) ON DELETE SET NULL,
        source_type TEXT NOT NULL,source_id TEXT,relation TEXT NOT NULL,excerpt TEXT NOT NULL,
        source_quality DOUBLE PRECISION,expertise DOUBLE PRECISION,independence DOUBLE PRECISION,
        directness DOUBLE PRECISION,extraction_confidence DOUBLE PRECISION NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,created_at TIMESTAMPTZ NOT NULL,
        CHECK(relation IN('supports','contradicts','mentions')),
        CHECK(extraction_confidence>=0 AND extraction_confidence<=1),
        UNIQUE(claim_id,source_type,source_id,excerpt,relation))""",
        "CREATE INDEX claim_evidence_claim_idx ON claim_evidence(claim_id)",
        """CREATE TABLE claim_relations(
        source_claim_id BIGINT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
        target_claim_id BIGINT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
        relation TEXT NOT NULL,confidence DOUBLE PRECISION NOT NULL,reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,PRIMARY KEY(source_claim_id,target_claim_id,relation),
        CHECK(source_claim_id<>target_claim_id),
        CHECK(relation IN('supports','contradicts','qualifies','supersedes','equivalent_to','derived_from','applies_to','broader_than','narrower_than')),
        CHECK(confidence>=0 AND confidence<=1))""",
        """CREATE TABLE conflict_cases(
        id BIGSERIAL PRIMARY KEY,conflict_key TEXT NOT NULL UNIQUE,conflict_type TEXT NOT NULL,
        affected_dimension TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'detected',summary TEXT NOT NULL,
        assessment JSONB NOT NULL DEFAULT '{}'::jsonb,resolution_claim_id BIGINT REFERENCES claims(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(conflict_type IN('value','temporal','negation','status','source','expert_opinion','context')),
        CHECK(status IN('detected','investigating','resolved','unresolved')))""",
        """CREATE TABLE conflict_case_claims(
        conflict_case_id BIGINT NOT NULL REFERENCES conflict_cases(id) ON DELETE CASCADE,
        claim_id BIGINT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,role TEXT NOT NULL DEFAULT 'position',
        PRIMARY KEY(conflict_case_id,claim_id),CHECK(role IN('position','resolution','context')))""",
    ]),
    ("0008_artifact_claim_materialization","Idempotent provenance from validated artifacts to claims",[
        """CREATE TABLE artifact_claim_links(
        artifact_id BIGINT NOT NULL REFERENCES session_artifacts(id) ON DELETE CASCADE,
        claim_id BIGINT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
        claim_key TEXT NOT NULL,relation TEXT NOT NULL DEFAULT 'derived_from',created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(artifact_id,claim_id),UNIQUE(artifact_id,claim_key),
        CHECK(relation IN('derived_from','supports')))""",
        "CREATE INDEX artifact_claim_links_claim_idx ON artifact_claim_links(claim_id)",
    ]),
    ("0009_semantic_shadow","Mutation-free semantic router comparison runs",[
        """CREATE TABLE semantic_shadow_runs(
        id BIGSERIAL PRIMARY KEY,session_id BIGINT NOT NULL REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
        shadow_mode TEXT NOT NULL,status TEXT NOT NULL,summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        detail_retain_until TIMESTAMPTZ NOT NULL,created_at TIMESTAMPTZ NOT NULL,completed_at TIMESTAMPTZ,
        CHECK(shadow_mode IN('llm_only','deterministic_test')),CHECK(status IN('running','completed','failed')))""",
        """CREATE TABLE semantic_shadow_results(
        id BIGSERIAL PRIMARY KEY,run_id BIGINT NOT NULL REFERENCES semantic_shadow_runs(id) ON DELETE CASCADE,
        segment_id BIGINT NOT NULL REFERENCES semantic_segments(id) ON DELETE CASCADE,text_hash TEXT NOT NULL,
        active_type TEXT,active_confidence DOUBLE PRECISION,shadow_type TEXT,shadow_confidence DOUBLE PRECISION,
        shadow_abstained BOOLEAN NOT NULL DEFAULT FALSE,agrees BOOLEAN NOT NULL,reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        latency_ms INTEGER,created_at TIMESTAMPTZ NOT NULL,UNIQUE(run_id,segment_id))""",
        "CREATE INDEX semantic_shadow_results_run_idx ON semantic_shadow_results(run_id,agrees)",
    ]),
    ("0010_claim_extraction_candidates","Isolated dry-run claim proposals for free notes",[
        """CREATE TABLE claim_extraction_runs(
        id BIGSERIAL PRIMARY KEY,note_id BIGINT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
        mode TEXT NOT NULL,status TEXT NOT NULL,prompt_version TEXT NOT NULL,summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,completed_at TIMESTAMPTZ,
        CHECK(mode IN('llm','deterministic_test')),CHECK(status IN('running','completed','failed')))""",
        """CREATE TABLE claim_extraction_candidates(
        id BIGSERIAL PRIMARY KEY,run_id BIGINT NOT NULL REFERENCES claim_extraction_runs(id) ON DELETE CASCADE,
        note_id BIGINT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,candidate_index INTEGER NOT NULL,
        claim_type TEXT NOT NULL,statement TEXT NOT NULL,subject TEXT NOT NULL,predicate TEXT NOT NULL,object_value TEXT,
        polarity TEXT NOT NULL,modality TEXT NOT NULL,evidence_excerpt TEXT NOT NULL,confidence DOUBLE PRECISION NOT NULL,
        reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,status TEXT NOT NULL DEFAULT 'proposed',validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,UNIQUE(run_id,candidate_index),
        CHECK(claim_type IN('fact','opinion','prediction','requirement','decision')),
        CHECK(polarity IN('positive','negative')),CHECK(modality IN('asserted','required','probable','possible','uncertain')),
        CHECK(status IN('proposed','rejected','promoted')),CHECK(confidence>=0 AND confidence<=1))""",
        "CREATE INDEX claim_extraction_candidates_note_idx ON claim_extraction_candidates(note_id,status,confidence DESC)",
    ]),
    ("0011_evidence_source_identity","Explicit source identity and nullable evidence dimensions",[
        """CREATE TABLE evidence_sources(
        id BIGSERIAL PRIMARY KEY,source_type TEXT NOT NULL,provider TEXT,external_id TEXT,display_name TEXT,
        privacy_class TEXT NOT NULL DEFAULT 'local_only',metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(privacy_class IN('local_only','pseudonymizable','anonymizable','public')),
        UNIQUE(source_type,provider,external_id))""",
        "ALTER TABLE claim_evidence ADD COLUMN source_identity_id BIGINT REFERENCES evidence_sources(id) ON DELETE SET NULL",
        "ALTER TABLE claim_evidence ADD COLUMN recency DOUBLE PRECISION",
        "ALTER TABLE claim_evidence ADD COLUMN evidence_strength DOUBLE PRECISION",
        """ALTER TABLE claim_evidence ADD CONSTRAINT claim_evidence_score_ranges CHECK(
        (source_quality IS NULL OR source_quality BETWEEN 0 AND 1) AND
        (expertise IS NULL OR expertise BETWEEN 0 AND 1) AND
        (independence IS NULL OR independence BETWEEN 0 AND 1) AND
        (directness IS NULL OR directness BETWEEN 0 AND 1) AND
        (recency IS NULL OR recency BETWEEN 0 AND 1) AND
        (evidence_strength IS NULL OR evidence_strength BETWEEN 0 AND 1))""",
    ]),
    ("0012_change_based_conflict_scan","Track incremental nightly claim conflict scans",[
        "ALTER TABLE claims ADD COLUMN conflict_checked_at TIMESTAMPTZ",
        "CREATE INDEX claims_conflict_pending_idx ON claims(updated_at,conflict_checked_at) WHERE status IN('active','disputed')",
        """CREATE TABLE conflict_scan_runs(
        id BIGSERIAL PRIMARY KEY,dry_run BOOLEAN NOT NULL,status TEXT NOT NULL,changed_claim_count INTEGER NOT NULL,
        candidate_claim_count INTEGER NOT NULL,result JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,completed_at TIMESTAMPTZ,
        CHECK(status IN('running','completed','failed')))""",
    ]),
    ("0013_job_parking","Park repeatedly failing live jobs and bound nightly repair",[
        "ALTER TABLE processing_jobs DROP CONSTRAINT processing_jobs_status_check",
        "ALTER TABLE processing_jobs ADD CONSTRAINT processing_jobs_status_check CHECK(status IN('queued','running','done','failed','parked','attention_required'))",
        "ALTER TABLE processing_jobs ADD COLUMN parked_at TIMESTAMPTZ",
        "ALTER TABLE processing_jobs ADD COLUMN error_class TEXT",
        "ALTER TABLE processing_jobs ADD COLUMN night_repair_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE processing_jobs ADD CONSTRAINT processing_jobs_night_repair_attempts_check CHECK(night_repair_attempts>=0 AND night_repair_attempts<=1)",
        "CREATE INDEX processing_jobs_parked_idx ON processing_jobs(status,parked_at,id) WHERE status='parked'",
    ]),
    ("0014_claim_semantic_neighbors","Versioned local embeddings for semantic claim neighbors",[
        "ALTER TABLE claims ADD COLUMN embedding vector(1024)",
        "ALTER TABLE claims ADD COLUMN embedding_model TEXT",
        "CREATE INDEX claims_embedding_hnsw_idx ON claims USING hnsw(embedding vector_cosine_ops)",
    ]),
    ("0015_queue_priority_observability","Fair priority queue, worker heartbeats and attempt history",[
        "ALTER TABLE processing_jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 50",
        "ALTER TABLE processing_jobs ADD CONSTRAINT processing_jobs_priority_check CHECK(priority BETWEEN 0 AND 200)",
        "CREATE INDEX processing_jobs_priority_claim_idx ON processing_jobs(status,priority DESC,available_at,id)",
        """CREATE TABLE processing_job_attempts(
        id BIGSERIAL PRIMARY KEY,job_id BIGINT NOT NULL REFERENCES processing_jobs(id) ON DELETE CASCADE,
        attempt_number INTEGER NOT NULL,worker_id TEXT NOT NULL,phase TEXT NOT NULL,error_class TEXT,error TEXT,
        started_at TIMESTAMPTZ NOT NULL,completed_at TIMESTAMPTZ,duration_ms BIGINT,
        UNIQUE(job_id,attempt_number),CHECK(phase IN('running','done','failed','parked','attention_required')))""",
        """CREATE TABLE worker_heartbeats(
        worker_id TEXT PRIMARY KEY,worker_kind TEXT NOT NULL,status TEXT NOT NULL,current_job_id BIGINT REFERENCES processing_jobs(id) ON DELETE SET NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,started_at TIMESTAMPTZ NOT NULL,last_seen_at TIMESTAMPTZ NOT NULL,
        CHECK(status IN('starting','idle','working','stopping','stopped','error')))""",
    ]),
    ("0016_durable_topics_retention","Durable topic graph and audited audio retention",[
        """CREATE TABLE knowledge_topics(
        id BIGSERIAL PRIMARY KEY,title TEXT NOT NULL,normalized_key TEXT NOT NULL UNIQUE,description TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL)""",
        """CREATE TABLE knowledge_topic_links(
        knowledge_type TEXT NOT NULL,knowledge_id BIGINT NOT NULL,topic_id BIGINT NOT NULL REFERENCES knowledge_topics(id) ON DELETE CASCADE,
        relation TEXT NOT NULL,link_origin TEXT NOT NULL DEFAULT 'direct',confidence DOUBLE PRECISION NOT NULL,created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(knowledge_type,knowledge_id,topic_id,relation),CHECK(link_origin IN('direct','inherited')),CHECK(confidence BETWEEN 0 AND 1))""",
        """CREATE TABLE knowledge_topic_relations(
        parent_topic_id BIGINT NOT NULL REFERENCES knowledge_topics(id) ON DELETE CASCADE,
        child_topic_id BIGINT NOT NULL REFERENCES knowledge_topics(id) ON DELETE CASCADE,relation TEXT NOT NULL DEFAULT 'parent',
        confidence DOUBLE PRECISION NOT NULL,created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(parent_topic_id,child_topic_id,relation),CHECK(parent_topic_id<>child_topic_id),CHECK(relation IN('parent','broader_than')))""",
        """CREATE TABLE retention_audit(
        id BIGSERIAL PRIMARY KEY,object_type TEXT NOT NULL,object_id BIGINT NOT NULL,action TEXT NOT NULL,storage_key TEXT,
        reason TEXT NOT NULL,occurred_at TIMESTAMPTZ NOT NULL,metadata JSONB NOT NULL DEFAULT '{}'::jsonb)""",
    ]),
    ("0017_alpha_observability_semantics","Short-lived structured logs, semantic examples and topic evidence",[
        """CREATE TABLE system_logs(
        id BIGSERIAL PRIMARY KEY,occurred_at TIMESTAMPTZ NOT NULL,level TEXT NOT NULL,component TEXT NOT NULL,event TEXT NOT NULL,
        request_id TEXT,session_id BIGINT,job_id BIGINT,metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        CHECK(level IN('debug','info','warning','error','critical')))""",
        "CREATE INDEX system_logs_time_idx ON system_logs(occurred_at DESC)",
        "CREATE INDEX system_logs_event_idx ON system_logs(component,event,occurred_at DESC)",
        """CREATE TABLE semantic_gold_examples(
        id BIGSERIAL PRIMARY KEY,text TEXT NOT NULL,artifact_type TEXT NOT NULL,label TEXT NOT NULL,source_kind TEXT NOT NULL,
        source_artifact_id BIGINT REFERENCES session_artifacts(id) ON DELETE SET NULL,embedding vector(1024),embedding_model TEXT,
        active BOOLEAN NOT NULL DEFAULT TRUE,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(artifact_type IN('note','fact','decision','task','list','list_item','question')),
        CHECK(label IN('positive','negative')),CHECK(source_kind IN('curated','user_correction')),UNIQUE(text,artifact_type,label))""",
        "CREATE INDEX semantic_gold_examples_embedding_idx ON semantic_gold_examples USING hnsw(embedding vector_cosine_ops)",
        """CREATE TABLE semantic_example_evaluations(
        id BIGSERIAL PRIMARY KEY,segment_id BIGINT REFERENCES semantic_segments(id) ON DELETE CASCADE,best_type TEXT,
        best_similarity DOUBLE PRECISION,runner_up_type TEXT,runner_up_similarity DOUBLE PRECISION,margin DOUBLE PRECISION,
        out_of_distribution BOOLEAN NOT NULL,direct_decision_allowed BOOLEAN NOT NULL DEFAULT FALSE,created_at TIMESTAMPTZ NOT NULL)""",
        """CREATE TABLE session_topic_evidence(
        session_id BIGINT NOT NULL REFERENCES ingestion_sessions(id) ON DELETE CASCADE,topic_id BIGINT NOT NULL REFERENCES session_topics(id) ON DELETE CASCADE,
        segment_id BIGINT NOT NULL REFERENCES semantic_segments(id) ON DELETE CASCADE,match_mode TEXT NOT NULL,confidence DOUBLE PRECISION NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,PRIMARY KEY(topic_id,segment_id),CHECK(match_mode IN('explicit','exact_alias','trigram','embedding','llm')),
        CHECK(confidence BETWEEN 0 AND 1))""",
    ]),
    ("0018_topic_embeddings","Local embeddings for incremental session and durable topic matching",[
        "ALTER TABLE session_topics ADD COLUMN embedding vector(1024)",
        "ALTER TABLE session_topics ADD COLUMN embedding_model TEXT",
        "ALTER TABLE knowledge_topics ADD COLUMN embedding vector(1024)",
        "ALTER TABLE knowledge_topics ADD COLUMN embedding_model TEXT",
        "CREATE INDEX session_topics_embedding_idx ON session_topics USING hnsw(embedding vector_cosine_ops)",
        "CREATE INDEX knowledge_topics_embedding_idx ON knowledge_topics USING hnsw(embedding vector_cosine_ops)",
    ]),
    ("0019_semantic_negative_margin","Track positive versus negative semantic example separation",[
        "ALTER TABLE semantic_example_evaluations ADD COLUMN best_negative_similarity DOUBLE PRECISION",
        "ALTER TABLE semantic_example_evaluations ADD COLUMN positive_negative_margin DOUBLE PRECISION",
    ]),
    ("0020_topic_context_origin","Distinguish conversationally inherited topic evidence",[
        "ALTER TABLE session_topic_evidence DROP CONSTRAINT session_topic_evidence_match_mode_check",
        "ALTER TABLE session_topic_evidence ADD CONSTRAINT session_topic_evidence_match_mode_check CHECK(match_mode IN('explicit','exact_alias','trigram','embedding','llm','context_inherited'))",
    ]),
    ("0021_nightly_consolidation_cache","Auditable exact supersessions, semantic shadow reviews and versioned retrieval cache",[
        """CREATE TABLE knowledge_supersessions(
        knowledge_type TEXT NOT NULL,original_id BIGINT NOT NULL,canonical_id BIGINT NOT NULL,reason TEXT NOT NULL,
        consolidation_run_id BIGINT,created_at TIMESTAMPTZ NOT NULL,PRIMARY KEY(knowledge_type,original_id),
        CHECK(original_id<>canonical_id),CHECK(knowledge_type IN('note','task','list','list_item')))""",
        """CREATE TABLE nightly_consolidation_runs(
        id BIGSERIAL PRIMARY KEY,dry_run BOOLEAN NOT NULL,status TEXT NOT NULL,model TEXT,summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,completed_at TIMESTAMPTZ,CHECK(status IN('running','completed','failed')))""",
        "ALTER TABLE knowledge_supersessions ADD CONSTRAINT knowledge_supersessions_run_fk FOREIGN KEY(consolidation_run_id) REFERENCES nightly_consolidation_runs(id) ON DELETE SET NULL",
        """CREATE TABLE nightly_consolidation_candidates(
        id BIGSERIAL PRIMARY KEY,run_id BIGINT NOT NULL REFERENCES nightly_consolidation_runs(id) ON DELETE CASCADE,
        candidate_kind TEXT NOT NULL,fingerprint TEXT NOT NULL,source_refs JSONB NOT NULL,similarity DOUBLE PRECISION,
        model_decision TEXT,proposed_entity JSONB,reason TEXT,status TEXT NOT NULL DEFAULT 'shadow',model TEXT,
        created_at TIMESTAMPTZ NOT NULL,UNIQUE(fingerprint,model),
        CHECK(candidate_kind IN('knowledge_duplicate','topic_relation')),
        CHECK(model_decision IS NULL OR model_decision IN('merge','synthesize','alias','hierarchy','keep_separate')),
        CHECK(status IN('shadow','applied','rejected')))""",
        """CREATE TABLE topic_aliases(
        topic_id BIGINT NOT NULL REFERENCES knowledge_topics(id) ON DELETE CASCADE,alias TEXT NOT NULL,normalized_alias TEXT NOT NULL,
        source_kind TEXT NOT NULL,status TEXT NOT NULL,confidence DOUBLE PRECISION NOT NULL,created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(topic_id,normalized_alias),CHECK(source_kind IN('normalization','explicit','llm_shadow')),
        CHECK(status IN('active','shadow','rejected')),CHECK(confidence BETWEEN 0 AND 1))""",
        "CREATE UNIQUE INDEX topic_aliases_active_key_idx ON topic_aliases(normalized_alias) WHERE status='active'",
        """CREATE TABLE retrieval_cache(
        cache_key TEXT PRIMARY KEY,query_hash TEXT NOT NULL,knowledge_version TEXT NOT NULL,retrieval_version TEXT NOT NULL,
        embedding_model TEXT NOT NULL,request_metadata JSONB NOT NULL,result_refs JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,last_hit_at TIMESTAMPTZ,hit_count BIGINT NOT NULL DEFAULT 0)""",
        "CREATE INDEX retrieval_cache_expiry_idx ON retrieval_cache(expires_at)",
    ]),
    ("0022_client_session_lifecycle","Stable client session identity, lifecycle and abort audit",[
        """CREATE TABLE client_sessions(
        client_session_id UUID PRIMARY KEY,ingestion_session_id BIGINT UNIQUE REFERENCES ingestion_sessions(id) ON DELETE SET NULL,
        state TEXT NOT NULL,device_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        expected_final_sequence BIGINT,final_source_end_ms BIGINT,paused_at TIMESTAMPTZ,finish_requested_at TIMESTAMPTZ,
        finalized_at TIMESTAMPTZ,aborted_at TIMESTAMPTZ,last_error TEXT,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(state IN('created','recording','paused','draining','processing','completed','failed','attention_required','aborted')),
        CHECK(expected_final_sequence IS NULL OR expected_final_sequence>=0),
        CHECK(final_source_end_ms IS NULL OR final_source_end_ms>=0))""",
        "CREATE INDEX client_sessions_state_updated_idx ON client_sessions(state,updated_at DESC)",
        """CREATE TABLE client_session_audit(
        id BIGSERIAL PRIMARY KEY,client_session_id UUID NOT NULL,event_type TEXT NOT NULL,from_state TEXT,to_state TEXT,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,occurred_at TIMESTAMPTZ NOT NULL,
        CHECK(event_type IN('created','started','paused','resumed','finish_requested','finalized','aborted','state_reconciled')))""",
        "CREATE INDEX client_session_audit_session_idx ON client_session_audit(client_session_id,occurred_at)",
    ]),
    ("0023_client_upload_conflicts","Durable client upload conflict reconciliation",[
        """CREATE TABLE client_upload_conflicts(
        id BIGSERIAL PRIMARY KEY,client_session_id UUID NOT NULL REFERENCES client_sessions(client_session_id) ON DELETE CASCADE,
        sequence BIGINT,client_chunk_id TEXT,conflict_code TEXT NOT NULL,expected JSONB NOT NULL DEFAULT '{}'::jsonb,
        received JSONB NOT NULL DEFAULT '{}'::jsonb,occurred_at TIMESTAMPTZ NOT NULL)""",
        "CREATE INDEX client_upload_conflicts_session_idx ON client_upload_conflicts(client_session_id,occurred_at DESC)",
    ]),
    ("0024_client_dashboard_revisions","Atomic revisioned client dashboard snapshots",[
        """CREATE TABLE client_dashboard_snapshots(
        scope_key TEXT PRIMARY KEY,revision BIGINT NOT NULL,content_hash TEXT NOT NULL,snapshot JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,CHECK(revision>=1))""",
    ]),
    ("0025_offline_knowledge_sync","Versioned libraries, stable knowledge UUIDs, immutable cursors and usage batches",[
        """CREATE TABLE knowledge_libraries(
        id UUID PRIMARY KEY,library_key TEXT NOT NULL UNIQUE,library_type TEXT NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',
        version BIGINT NOT NULL DEFAULT 1,privacy_class TEXT NOT NULL,offline_enabled BOOLEAN NOT NULL,sync_mode TEXT NOT NULL,
        scope JSONB NOT NULL DEFAULT '{}'::jsonb,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(library_type IN('personal','curated_reference','general_knowledge','external_reference')),
        CHECK(sync_mode IN('off','metadata','full_text')),CHECK(version>=1))""",
        """INSERT INTO knowledge_libraries(id,library_key,library_type,title,description,privacy_class,offline_enabled,sync_mode,created_at,updated_at)
        VALUES('00000000-0000-4000-8000-000000000001','personal','personal','Persönliches Wissen','Lokale Notes, Facts und Topics','private',TRUE,'full_text',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
        ('00000000-0000-4000-8000-000000000002','curated','curated_reference','Kuratierte Referenzen','Serverseitig freigegebene Referenzen','curated',TRUE,'metadata',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
        ('00000000-0000-4000-8000-000000000003','general','general_knowledge','Allgemeinwissen','Explizit freigegebenes Allgemeinwissen','reviewed',FALSE,'off',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP),
        ('00000000-0000-4000-8000-000000000004','external','external_reference','Externe Quellen','Temporäre externe Suchtreffer','external',FALSE,'off',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
        """CREATE TABLE client_knowledge_entities(
        public_id UUID PRIMARY KEY,entity_type TEXT NOT NULL,internal_id BIGINT NOT NULL,library_id UUID NOT NULL REFERENCES knowledge_libraries(id),
        revision BIGINT NOT NULL,state TEXT NOT NULL,fingerprint TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        UNIQUE(entity_type,internal_id),CHECK(entity_type IN('note','fact','topic')),CHECK(state IN('active','archived','deleted','superseded')),CHECK(revision>=1))""",
        """CREATE TABLE client_knowledge_changes(
        sequence BIGSERIAL PRIMARY KEY,library_id UUID NOT NULL REFERENCES knowledge_libraries(id),public_id UUID NOT NULL,
        operation TEXT NOT NULL,entity_type TEXT NOT NULL,revision BIGINT NOT NULL,payload JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL,
        CHECK(operation IN('upsert','delete','redirect')),CHECK(entity_type IN('note','fact','topic')),CHECK(revision>=1))""",
        "CREATE INDEX client_knowledge_changes_library_seq_idx ON client_knowledge_changes(library_id,sequence)",
        """CREATE TABLE client_knowledge_cursors(
        token UUID PRIMARY KEY,cursor_kind TEXT NOT NULL,library_ids UUID[] NOT NULL,after_sequence BIGINT NOT NULL,
        snapshot_sequence BIGINT,position_public_id UUID,expires_at TIMESTAMPTZ NOT NULL,created_at TIMESTAMPTZ NOT NULL,
        CHECK(cursor_kind IN('snapshot','delta')))""",
        "CREATE INDEX client_knowledge_cursors_expiry_idx ON client_knowledge_cursors(expires_at)",
        """CREATE TABLE client_knowledge_usage_batches(
        batch_id UUID PRIMARY KEY,client_installation_id UUID NOT NULL,payload_hash TEXT NOT NULL,accepted_count INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL)""",
        "ALTER TABLE knowledge_activity DROP CONSTRAINT IF EXISTS knowledge_activity_knowledge_type_check",
        "ALTER TABLE knowledge_activity ADD CONSTRAINT knowledge_activity_knowledge_type_check CHECK(knowledge_type IN('note','fact','task','list','list_item','session_artifact','topic'))",
    ]),
    ("0026_note_fact_promotion","Auditable evidence-gated nightly note to fact promotion",[
        """CREATE TABLE note_fact_promotions(
        id BIGSERIAL PRIMARY KEY,note_id BIGINT NOT NULL REFERENCES notes(id) ON DELETE RESTRICT,
        claim_id BIGINT NOT NULL REFERENCES claims(id) ON DELETE RESTRICT,original_content TEXT NOT NULL,reformulated_statement TEXT NOT NULL,
        evidence_score DOUBLE PRECISION NOT NULL,reason JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL,
        UNIQUE(note_id),UNIQUE(claim_id),CHECK(evidence_score BETWEEN 0 AND 1))""",
    ]),
    ("0027_client_conversations","Server-owned resumable client conversations and turn events",[
        """CREATE TABLE client_conversations(
        id UUID PRIMARY KEY,client_conversation_id UUID NOT NULL UNIQUE,title TEXT NOT NULL,status TEXT NOT NULL,revision BIGINT NOT NULL DEFAULT 1,
        agent_key TEXT NOT NULL DEFAULT 'smart_notebook',created_at TIMESTAMPTZ NOT NULL,last_activity_at TIMESTAMPTZ NOT NULL,
        dashboard_until TIMESTAMPTZ NOT NULL,delete_after TIMESTAMPTZ NOT NULL,
        CHECK(status IN('open','processing','completed','failed','aborted')),CHECK(revision>=1))""",
        "CREATE INDEX client_conversations_retention_idx ON client_conversations(delete_after)",
        """CREATE TABLE client_conversation_messages(
        id UUID PRIMARY KEY,conversation_id UUID NOT NULL REFERENCES client_conversations(id) ON DELETE CASCADE,
        client_message_id UUID,sequence BIGINT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,content_format TEXT NOT NULL DEFAULT 'plain_text',
        retained_as_knowledge BOOLEAN NOT NULL DEFAULT FALSE,created_at TIMESTAMPTZ NOT NULL,
        UNIQUE(conversation_id,sequence),UNIQUE(conversation_id,client_message_id),
        CHECK(role IN('user','assistant','system')),CHECK(content_format IN('plain_text','markdown')),CHECK(sequence>=1))""",
        """CREATE TABLE client_conversation_turns(
        id UUID PRIMARY KEY,conversation_id UUID NOT NULL REFERENCES client_conversations(id) ON DELETE CASCADE,
        client_turn_id UUID NOT NULL,user_message_id UUID NOT NULL REFERENCES client_conversation_messages(id) ON DELETE CASCADE,
        assistant_message_id UUID REFERENCES client_conversation_messages(id) ON DELETE SET NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT,created_at TIMESTAMPTZ NOT NULL,started_at TIMESTAMPTZ,completed_at TIMESTAMPTZ,updated_at TIMESTAMPTZ NOT NULL,
        UNIQUE(conversation_id,client_turn_id),CHECK(status IN('queued','running','completed','failed','aborted')),CHECK(attempts>=0))""",
        "CREATE INDEX client_conversation_turns_queue_idx ON client_conversation_turns(status,created_at)",
        """CREATE TABLE client_conversation_turn_events(
        sequence BIGSERIAL PRIMARY KEY,turn_id UUID NOT NULL REFERENCES client_conversation_turns(id) ON DELETE CASCADE,
        event_type TEXT NOT NULL,payload JSONB NOT NULL DEFAULT '{}'::jsonb,created_at TIMESTAMPTZ NOT NULL,
        CHECK(event_type IN('started','delta','citation','action','completed','failed','aborted')) )""",
        "CREATE INDEX client_conversation_turn_events_idx ON client_conversation_turn_events(turn_id,sequence)",
    ]),
    ("0028_unified_push","Multi-device encrypted UnifiedPush registration and delivery audit",[
        """CREATE TABLE unified_push_registrations(
        id UUID PRIMARY KEY,client_installation_id UUID NOT NULL,distributor TEXT NOT NULL,endpoint TEXT NOT NULL,endpoint_hash TEXT NOT NULL,
        client_public_key TEXT NOT NULL,status TEXT NOT NULL,challenge_hash TEXT,challenge_expires_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,last_success_at TIMESTAMPTZ,last_failure_at TIMESTAMPTZ,
        failure_count INTEGER NOT NULL DEFAULT 0,UNIQUE(client_installation_id,endpoint_hash),
        CHECK(status IN('pending','active','disabled')),CHECK(failure_count>=0))""",
        "CREATE INDEX unified_push_active_idx ON unified_push_registrations(status,updated_at)",
        """CREATE TABLE unified_push_delivery_audit(
        id BIGSERIAL PRIMARY KEY,registration_id UUID NOT NULL REFERENCES unified_push_registrations(id) ON DELETE CASCADE,
        event_type TEXT NOT NULL,revision BIGINT,outcome TEXT NOT NULL,http_status INTEGER,error_type TEXT,created_at TIMESTAMPTZ NOT NULL,
        CHECK(outcome IN('delivered','failed')))""",
    ]),
    ("0029_client_entity_identity","Opaque dashboard identities and explicit topic redirects",[
        """CREATE TABLE client_entity_identities(
        public_id UUID PRIMARY KEY,entity_type TEXT NOT NULL,internal_id BIGINT NOT NULL,created_at TIMESTAMPTZ NOT NULL,
        UNIQUE(entity_type,internal_id),CHECK(entity_type IN('session_artifact','session_topic','question')))""",
        """CREATE TABLE knowledge_topic_redirects(
        source_topic_id BIGINT PRIMARY KEY REFERENCES knowledge_topics(id) ON DELETE RESTRICT,
        target_topic_id BIGINT NOT NULL REFERENCES knowledge_topics(id) ON DELETE RESTRICT,reason TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL,
        CHECK(source_topic_id<>target_topic_id))""",
    ]),
    ("0030_client_capture_mode","Server-owned meeting, memo and query intent on audio sessions",[
        "ALTER TABLE client_sessions ADD COLUMN capture_mode TEXT NOT NULL DEFAULT 'meeting'",
        "ALTER TABLE client_sessions ADD COLUMN context_ref JSONB",
        "ALTER TABLE client_sessions ADD COLUMN capture_result JSONB",
        "ALTER TABLE client_sessions ADD CONSTRAINT client_sessions_capture_mode_check CHECK(capture_mode IN('meeting','memo','query','auto'))",
    ]),
    ("0031_client_text_capture","Idempotent server-classified text memo and query capture",[
        """CREATE TABLE client_text_captures(
        id UUID PRIMARY KEY,mode TEXT NOT NULL,resolved_intent TEXT NOT NULL,content TEXT NOT NULL,content_hash TEXT NOT NULL,
        context_ref JSONB,event_id BIGINT REFERENCES events(id) ON DELETE SET NULL,conversation_id UUID REFERENCES client_conversations(id) ON DELETE SET NULL,
        turn_id UUID REFERENCES client_conversation_turns(id) ON DELETE SET NULL,status TEXT NOT NULL,result JSONB,error TEXT,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(mode IN('memo','query','auto')),CHECK(resolved_intent IN('memo','query')),
        CHECK(status IN('queued','processing','completed','failed')))""",
        "CREATE INDEX client_text_captures_queue_idx ON client_text_captures(status,created_at)",
    ]),
    ("0032_nextcloud_caldav_sync","Marked two-way Nextcloud VTODO projection with conflicts and tombstones",[
        "ALTER TABLE tasks ADD COLUMN archived_at TIMESTAMPTZ",
        "ALTER TABLE tasks ADD COLUMN archive_reason TEXT",
        "ALTER TABLE lists ADD COLUMN archived_at TIMESTAMPTZ",
        "ALTER TABLE lists ADD COLUMN archive_reason TEXT",
        "ALTER TABLE list_items ADD COLUMN archived_at TIMESTAMPTZ",
        "ALTER TABLE list_items ADD COLUMN archive_reason TEXT",
        """CREATE TABLE caldav_sync_entities(
        public_id UUID PRIMARY KEY,entity_type TEXT NOT NULL,internal_id BIGINT NOT NULL,uid TEXT NOT NULL UNIQUE,
        href TEXT,etag TEXT,remote_hash TEXT,local_fingerprint TEXT,parent_public_id UUID REFERENCES caldav_sync_entities(public_id) ON DELETE SET NULL,
        sync_state TEXT NOT NULL DEFAULT 'active',last_synced_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        UNIQUE(entity_type,internal_id),CHECK(entity_type IN('task','list','list_item')),
        CHECK(sync_state IN('active','archived','remote_deleted')))""",
        "CREATE INDEX caldav_sync_entities_href_idx ON caldav_sync_entities(href) WHERE href IS NOT NULL",
        """CREATE TABLE caldav_sync_state(
        profile_key TEXT PRIMARY KEY,calendar_url TEXT,sync_token TEXT,collection_etag TEXT,last_sync_started_at TIMESTAMPTZ,
        last_sync_completed_at TIMESTAMPTZ,last_outcome TEXT,last_error_type TEXT,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(last_outcome IS NULL OR last_outcome IN('success','partial','failed')))""",
        """CREATE TABLE caldav_sync_conflicts(
        id BIGSERIAL PRIMARY KEY,public_id UUID NOT NULL REFERENCES caldav_sync_entities(public_id) ON DELETE CASCADE,
        conflict_type TEXT NOT NULL,local_snapshot JSONB NOT NULL,remote_snapshot JSONB NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',resolution TEXT,detected_at TIMESTAMPTZ NOT NULL,resolved_at TIMESTAMPTZ,
        CHECK(status IN('open','resolved','dismissed')),CHECK(resolution IS NULL OR resolution IN('keep_local','keep_remote','merged')))""",
        "CREATE INDEX caldav_sync_conflicts_open_idx ON caldav_sync_conflicts(status,detected_at DESC)",
        """CREATE TABLE caldav_sync_audit(
        id BIGSERIAL PRIMARY KEY,public_id UUID,event_type TEXT NOT NULL,direction TEXT NOT NULL,outcome TEXT NOT NULL,
        href TEXT,etag TEXT,metadata JSONB NOT NULL DEFAULT '{}'::jsonb,occurred_at TIMESTAMPTZ NOT NULL,
        CHECK(direction IN('local_to_remote','remote_to_local','system')),
        CHECK(outcome IN('planned','applied','ignored','conflict','failed')))""",
    ]),
    ("0033_internal_reference_resolver","Short-lived validated internal reference candidates",[
        """CREATE TABLE reference_resolver_runs(
        id UUID PRIMARY KEY,query_hash TEXT NOT NULL,status TEXT NOT NULL,adequacy TEXT NOT NULL,
        escalation_target TEXT,assessment JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,expires_at TIMESTAMPTZ NOT NULL,
        CHECK(status IN('completed','failed')),CHECK(adequacy IN('sufficient','insufficient','conflicting')),
        CHECK(escalation_target IS NULL OR escalation_target IN('external','research')))""",
        "CREATE INDEX reference_resolver_runs_expiry_idx ON reference_resolver_runs(expires_at)",
        """CREATE TABLE reference_candidates(
        source_id UUID PRIMARY KEY,run_id UUID NOT NULL REFERENCES reference_resolver_runs(id) ON DELETE CASCADE,
        source_type TEXT NOT NULL,source_record_id BIGINT NOT NULL,title TEXT,content TEXT NOT NULL,
        confidence DOUBLE PRECISION NOT NULL,retrieval_stage TEXT NOT NULL,metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        used_at TIMESTAMPTZ,created_at TIMESTAMPTZ NOT NULL,expires_at TIMESTAMPTZ NOT NULL,
        CHECK(source_type IN('note','fact')),CHECK(confidence BETWEEN 0 AND 1))""",
        "CREATE INDEX reference_candidates_run_idx ON reference_candidates(run_id,confidence DESC)",
    ]),
    ("0034_esp_dashboard_identities","Opaque read-only task and list identities for the ESP dashboard surface",[
        "ALTER TABLE client_entity_identities DROP CONSTRAINT client_entity_identities_entity_type_check",
        "ALTER TABLE client_entity_identities ADD CONSTRAINT client_entity_identities_entity_type_check CHECK(entity_type IN('session_artifact','session_topic','question','task','list'))",
    ]),
    ("0035_client_device_credentials","Hashed per-installation credentials with enrollment, rotation and revocation",[
        """CREATE TABLE client_installations(
        id UUID PRIMARY KEY,device_model TEXT NOT NULL,firmware_version TEXT NOT NULL,status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,last_seen_at TIMESTAMPTZ,
        CHECK(status IN('active','revoked')))""",
        """CREATE TABLE client_enrollment_codes(
        code_hash TEXT PRIMARY KEY,expires_at TIMESTAMPTZ NOT NULL,used_at TIMESTAMPTZ,
        installation_id UUID REFERENCES client_installations(id),created_at TIMESTAMPTZ NOT NULL)""",
        "CREATE INDEX client_enrollment_codes_expiry_idx ON client_enrollment_codes(expires_at)",
        """CREATE TABLE client_device_credentials(
        id UUID PRIMARY KEY,installation_id UUID NOT NULL REFERENCES client_installations(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,status TEXT NOT NULL,issued_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,rotate_after TIMESTAMPTZ NOT NULL,revoked_at TIMESTAMPTZ,
        CHECK(status IN('active','revoked')))""",
        "CREATE INDEX client_device_credentials_installation_idx ON client_device_credentials(installation_id,status)",
        """CREATE TABLE client_credential_rotations(
        request_id UUID PRIMARY KEY,installation_id UUID NOT NULL REFERENCES client_installations(id) ON DELETE CASCADE,
        credential_id UUID NOT NULL REFERENCES client_device_credentials(id),created_at TIMESTAMPTZ NOT NULL)""",
    ]),
    ("0036_client_audio_release","Explicit monotone per-session release for client-held audio",[
        "ALTER TABLE client_sessions ADD COLUMN local_audio_release_allowed BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE client_sessions ADD COLUMN local_audio_release_at TIMESTAMPTZ",
        "ALTER TABLE client_sessions ADD CONSTRAINT client_audio_release_time_check CHECK(NOT local_audio_release_allowed OR local_audio_release_at IS NOT NULL)",
    ]),
    ("0037_client_audio_release_audit","Permit the explicit local-audio release audit event",[
        "ALTER TABLE client_session_audit DROP CONSTRAINT client_session_audit_event_type_check",
        "ALTER TABLE client_session_audit ADD CONSTRAINT client_session_audit_event_type_check CHECK(event_type IN('created','started','paused','resumed','finish_requested','finalized','aborted','state_reconciled','local_audio_released'))",
    ]),
    ("0038_client_session_sequence_base","Move wire sequence semantics out of mutable device metadata",[
        "ALTER TABLE client_sessions ADD COLUMN sequence_base SMALLINT NOT NULL DEFAULT 1",
        "UPDATE client_sessions SET sequence_base=0 WHERE device_metadata->>'sequence_base'='0'",
        "ALTER TABLE client_sessions ADD CONSTRAINT client_sessions_sequence_base_check CHECK(sequence_base IN(0,1))",
    ]),
    ("0039_task_work_window","Persist when a task should enter active work",[
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS work_start_at TIMESTAMPTZ",
        """UPDATE tasks SET work_start_at=LEAST(
        date_trunc('day',created_at AT TIME ZONE 'Europe/Berlin') AT TIME ZONE 'Europe/Berlin',due_at)
        WHERE due_at IS NOT NULL AND work_start_at IS NULL""",
        """DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='tasks_work_window_check') THEN
        ALTER TABLE tasks ADD CONSTRAINT tasks_work_window_check CHECK(
        work_start_at IS NULL OR due_at IS NULL OR work_start_at <= due_at); END IF; END $$""",
        "CREATE INDEX IF NOT EXISTS tasks_open_work_window_idx ON tasks(work_start_at,due_at) WHERE archived=FALSE AND status='open'",
    ]),
    ("0040_client_list_item_identity","Opaque identities for client-visible list items",[
        "ALTER TABLE client_entity_identities DROP CONSTRAINT client_entity_identities_entity_type_check",
        "ALTER TABLE client_entity_identities ADD CONSTRAINT client_entity_identities_entity_type_check CHECK(entity_type IN('session_artifact','session_topic','question','task','list','list_item'))",
    ]),
    ("0041_unified_text_capture_pipeline","Route direct client text through the ingestion session pipeline",[
        "ALTER TABLE client_text_captures ADD COLUMN client_session_id UUID REFERENCES client_sessions(client_session_id) ON DELETE SET NULL",
        "CREATE UNIQUE INDEX client_text_captures_client_session_idx ON client_text_captures(client_session_id) WHERE client_session_id IS NOT NULL",
        "ALTER TABLE client_text_captures DROP CONSTRAINT client_text_captures_status_check",
        "ALTER TABLE client_text_captures ADD CONSTRAINT client_text_captures_status_check CHECK(status IN('queued','processing','completed','failed','attention_required'))",
    ]),
    ("0042_session_content_intent","Persist content-based intent decisions for completed auto captures",[
        """CREATE TABLE session_intent_decisions(
        session_id BIGINT PRIMARY KEY REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
        primary_intent TEXT NOT NULL,target_type TEXT NOT NULL,target_text TEXT NOT NULL DEFAULT '',
        confidence DOUBLE PRECISION NOT NULL,multiple_intents_detected BOOLEAN NOT NULL DEFAULT FALSE,
        reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,decision_source TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(primary_intent IN('memo','query','change','complete','archive')),
        CHECK(target_type IN('none','unknown','note','task','list','list_item')),
        CHECK(confidence BETWEEN 0 AND 1))""",
        "ALTER TABLE client_text_captures DROP CONSTRAINT client_text_captures_resolved_intent_check",
        "ALTER TABLE client_text_captures ADD CONSTRAINT client_text_captures_resolved_intent_check CHECK(resolved_intent IN('memo','query','change','complete','archive'))",
    ]),
    ("0043_session_intent_parts","Persist ordered source-bound intent parts for auto captures",[
        """CREATE TABLE session_intent_parts(
        id BIGSERIAL PRIMARY KEY,session_id BIGINT NOT NULL REFERENCES session_intent_decisions(session_id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL,primary_intent TEXT NOT NULL,target_type TEXT NOT NULL,target_text TEXT NOT NULL DEFAULT '',
        source_text TEXT NOT NULL,source_start INTEGER NOT NULL,source_end INTEGER NOT NULL,confidence DOUBLE PRECISION NOT NULL,
        reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,decision_source TEXT NOT NULL,created_at TIMESTAMPTZ NOT NULL,
        UNIQUE(session_id,ordinal),CHECK(ordinal BETWEEN 1 AND 12),
        CHECK(primary_intent IN('memo','query','change','complete','archive')),
        CHECK(target_type IN('none','unknown','note','task','list','list_item')),
        CHECK(source_text<>''),CHECK(source_start>=0 AND source_end>source_start),CHECK(confidence BETWEEN 0 AND 1))""",
        """CREATE TABLE session_intent_part_segments(
        part_id BIGINT NOT NULL REFERENCES session_intent_parts(id) ON DELETE CASCADE,
        segment_id BIGINT NOT NULL REFERENCES semantic_segments(id) ON DELETE CASCADE,
        PRIMARY KEY(part_id,segment_id))""",
        "CREATE INDEX session_intent_part_segments_segment_idx ON session_intent_part_segments(segment_id)",
    ]),
    ("0044_unified_content_types","Add the canonical list segment candidate",[
        "ALTER TABLE semantic_segments DROP CONSTRAINT semantic_segments_segment_type_check",
        """ALTER TABLE semantic_segments ADD CONSTRAINT semantic_segments_segment_type_check CHECK(
        segment_type IN('statement','note_candidate','task_candidate','list_candidate','list_item_candidate','question','other'))""",
    ]),
    ("0045_knowledge_preflight","Persist A05 knowledge and possible-target assessments",[
        """CREATE TABLE knowledge_preflight_assessments(
        id BIGSERIAL PRIMARY KEY,session_id BIGINT NOT NULL REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
        artifact_id BIGINT REFERENCES session_artifacts(id) ON DELETE CASCADE,
        intent_part_id BIGINT REFERENCES session_intent_parts(id) ON DELETE CASCADE,
        input_kind TEXT NOT NULL,input_type TEXT NOT NULL,input_text TEXT NOT NULL,
        classification TEXT NOT NULL,confidence DOUBLE PRECISION NOT NULL,
        candidate_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
        related_candidate_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
        reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,decision_source TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK((artifact_id IS NULL) <> (intent_part_id IS NULL)),
        CHECK(input_kind IN('artifact','mutation_intent')),
        CHECK(input_type IN('unknown','note','task','list','list_item','fact','decision')),
        CHECK(input_text<>''),
        CHECK(classification IN('new','identical','complementary','contradictory','targeted')),
        CHECK(confidence BETWEEN 0 AND 1))""",
        "CREATE UNIQUE INDEX knowledge_preflight_artifact_uidx ON knowledge_preflight_assessments(artifact_id) WHERE artifact_id IS NOT NULL",
        "CREATE UNIQUE INDEX knowledge_preflight_intent_part_uidx ON knowledge_preflight_assessments(intent_part_id) WHERE intent_part_id IS NOT NULL",
        "CREATE INDEX knowledge_preflight_session_idx ON knowledge_preflight_assessments(session_id,id)",
    ]),
    ("0046_mutation_target_resolution","Persist A06 mutation targets and clarification links",[
        """CREATE TABLE mutation_target_resolutions(
        id BIGSERIAL PRIMARY KEY,session_id BIGINT NOT NULL REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
        intent_part_id BIGINT NOT NULL UNIQUE REFERENCES session_intent_parts(id) ON DELETE CASCADE,
        preflight_assessment_id BIGINT NOT NULL UNIQUE REFERENCES knowledge_preflight_assessments(id) ON DELETE CASCADE,
        status TEXT NOT NULL,target_type TEXT,target_id BIGINT,target_key TEXT,
        confidence DOUBLE PRECISION NOT NULL,candidate_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
        reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,decision_source TEXT NOT NULL,
        clarification_question_id BIGINT REFERENCES session_questions(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(status IN('resolved','ambiguous','unresolved')),
        CHECK(target_type IS NULL OR target_type IN('note','task','list','list_item')),
        CHECK(confidence BETWEEN 0 AND 1),
        CHECK((status='resolved')=(target_type IS NOT NULL AND target_id IS NOT NULL AND target_key IS NOT NULL)),
        CHECK(status='resolved' OR clarification_question_id IS NOT NULL))""",
        "CREATE INDEX mutation_target_resolution_session_idx ON mutation_target_resolutions(session_id,id)",
    ]),
    ("0047_mutation_action_execution","Persist and audit idempotent A07 object actions",[
        "ALTER TABLE notes ADD COLUMN archived_at TIMESTAMPTZ",
        "ALTER TABLE notes ADD COLUMN archive_reason TEXT",
        """CREATE TABLE mutation_action_executions(
        id BIGSERIAL PRIMARY KEY,session_id BIGINT NOT NULL REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
        intent_part_id BIGINT NOT NULL UNIQUE REFERENCES session_intent_parts(id) ON DELETE CASCADE,
        target_resolution_id BIGINT NOT NULL UNIQUE REFERENCES mutation_target_resolutions(id) ON DELETE CASCADE,
        operation TEXT,payload JSONB NOT NULL DEFAULT '{}'::jsonb,status TEXT NOT NULL,
        confidence DOUBLE PRECISION NOT NULL,reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        decision_source TEXT NOT NULL,before_state JSONB,after_state JSONB,
        clarification_question_id BIGINT REFERENCES session_questions(id) ON DELETE SET NULL,
        executed_at TIMESTAMPTZ,error_code TEXT,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(operation IS NULL OR operation IN('note_update','note_archive','task_update','task_complete','task_reopen',
        'task_archive','list_rename','list_add_item','list_archive','list_item_update','list_item_complete',
        'list_item_reopen','list_item_archive')),
        CHECK(status IN('planned','completed','clarification_required','failed')),
        CHECK(confidence BETWEEN 0 AND 1),
        CHECK((status='clarification_required')=(clarification_question_id IS NOT NULL)),
        CHECK(status='clarification_required' OR operation IS NOT NULL),
        CHECK(status<>'completed' OR (before_state IS NOT NULL AND after_state IS NOT NULL AND executed_at IS NOT NULL)))""",
        "CREATE INDEX mutation_action_execution_session_idx ON mutation_action_executions(session_id,id)",
    ]),
    ("0048_clarification_answer_loop","Persist source-bound W05 answers and resumable mutation outcomes",[
        "ALTER TABLE mutation_target_resolutions DROP CONSTRAINT mutation_target_resolutions_status_check",
        "ALTER TABLE mutation_target_resolutions ADD CONSTRAINT mutation_target_resolutions_status_check CHECK(status IN('resolved','ambiguous','unresolved','cancelled'))",
        "ALTER TABLE mutation_action_executions DROP CONSTRAINT mutation_action_executions_status_check",
        "ALTER TABLE mutation_action_executions ADD CONSTRAINT mutation_action_executions_status_check CHECK(status IN('planned','completed','clarification_required','failed','cancelled'))",
        "ALTER TABLE mutation_action_executions DROP CONSTRAINT mutation_action_executions_check",
        "ALTER TABLE mutation_action_executions ADD CONSTRAINT mutation_action_executions_check CHECK(status<>'clarification_required' OR clarification_question_id IS NOT NULL)",
        "ALTER TABLE mutation_action_executions DROP CONSTRAINT mutation_action_executions_check1",
        "ALTER TABLE mutation_action_executions ADD CONSTRAINT mutation_action_executions_check1 CHECK(status NOT IN('planned','completed') OR operation IS NOT NULL)",
        "ALTER TABLE client_text_captures DROP CONSTRAINT client_text_captures_resolved_intent_check",
        "ALTER TABLE client_text_captures ADD CONSTRAINT client_text_captures_resolved_intent_check CHECK(resolved_intent IN('memo','query','change','complete','archive','clarification'))",
        """CREATE TABLE clarification_answer_attempts(
        id BIGSERIAL PRIMARY KEY,question_id BIGINT NOT NULL REFERENCES session_questions(id) ON DELETE CASCADE,
        answer_session_id BIGINT NOT NULL UNIQUE REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
        answer_text TEXT NOT NULL,answer_source TEXT NOT NULL,status TEXT NOT NULL,
        result JSONB NOT NULL DEFAULT '{}'::jsonb,created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,
        CHECK(answer_text<>''),CHECK(answer_source IN('audio_capture','text_capture','suggested_answer')),
        CHECK(status IN('processing','completed','cancelled','needs_clarification','failed')))""",
        "CREATE INDEX clarification_answer_question_idx ON clarification_answer_attempts(question_id,id)",
    ]),
    ("0049_knowledge_clarification_loop","Persist W05 knowledge-conflict dependencies and audited outcomes",[
        """CREATE TABLE knowledge_clarification_resolutions(
        id BIGSERIAL PRIMARY KEY,session_id BIGINT NOT NULL REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
        artifact_id BIGINT NOT NULL UNIQUE REFERENCES session_artifacts(id) ON DELETE CASCADE,
        preflight_assessment_id BIGINT NOT NULL UNIQUE REFERENCES knowledge_preflight_assessments(id) ON DELETE CASCADE,
        clarification_question_id BIGINT NOT NULL UNIQUE REFERENCES session_questions(id) ON DELETE CASCADE,
        status TEXT NOT NULL,resolution TEXT,selected_candidate_key TEXT,
        candidate_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
        answer_session_id BIGINT UNIQUE REFERENCES ingestion_sessions(id) ON DELETE SET NULL,
        before_state JSONB,after_state JSONB,reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,updated_at TIMESTAMPTZ NOT NULL,resolved_at TIMESTAMPTZ,
        CHECK(status IN('pending','completed','cancelled','needs_clarification','failed')),
        CHECK(resolution IS NULL OR resolution IN('keep_existing','replace_existing','revised_statement')),
        CHECK(status NOT IN('completed','cancelled') OR resolved_at IS NOT NULL),
        CHECK(status<>'completed' OR resolution IS NOT NULL))""",
        "CREATE INDEX knowledge_clarification_session_idx ON knowledge_clarification_resolutions(session_id,id)",
    ]),
    ("0050_client_session_night_repair","One nightly retry for client_sessions stuck in attention_required",[
        "ALTER TABLE client_sessions ADD COLUMN night_repair_attempts INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE client_sessions ADD CONSTRAINT client_sessions_night_repair_attempts_check CHECK(night_repair_attempts>=0 AND night_repair_attempts<=1)",
    ]),
]


def apply_pending_migrations():
    with get_db_connection() as connection:
        applied={r[0] for r in connection.execute("SELECT version FROM schema_migrations").fetchall()}
        for version,description,statements in MIGRATIONS:
            if version in applied:continue
            for statement in statements:connection.execute(statement)
            connection.execute("INSERT INTO schema_migrations(version,description,applied_at) VALUES(%s,%s,%s)",(version,description,datetime.now(TIMEZONE)))
        connection.commit()
