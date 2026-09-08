# Smart Notebook database setup
import psycopg

from .config import (
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
)

def get_db_connection():
    return psycopg.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )

def _bootstrap_schema():
    with get_db_connection() as connection:
        connection.execute("""
            CREATE EXTENSION IF NOT EXISTS vector
        """)

        connection.execute("""
            CREATE EXTENSION IF NOT EXISTS pg_trgm
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id BIGSERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                response TEXT,
                archived BOOLEAN NOT NULL DEFAULT FALSE,
                archived_at TIMESTAMPTZ,
                source TEXT NOT NULL DEFAULT 'chat',
                client_event_id TEXT,
                capture_processed_at TIMESTAMPTZ,
                capture_result JSONB
            )
        """)

        connection.execute("""
            ALTER TABLE events
            ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE
        """)

        connection.execute("""
            ALTER TABLE events
            ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ
        """)

        connection.execute("""
            ALTER TABLE events
            ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'chat'
        """)

        connection.execute("""
            ALTER TABLE events
            ADD COLUMN IF NOT EXISTS client_event_id TEXT
        """)

        connection.execute("""
            ALTER TABLE events
            ADD COLUMN IF NOT EXISTS capture_processed_at TIMESTAMPTZ
        """)

        connection.execute("""
            ALTER TABLE events
            ADD COLUMN IF NOT EXISTS capture_result JSONB
        """)

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS events_client_event_id_uidx
            ON events(client_event_id)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id BIGSERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                source_event_id BIGINT REFERENCES events(id) ON DELETE SET NULL,
                archived BOOLEAN NOT NULL DEFAULT FALSE,
                embedding vector(1024),
                embedding_model TEXT
            )
        """)

        connection.execute("""
            ALTER TABLE notes
            ADD COLUMN IF NOT EXISTS embedding vector(1024)
        """)

        connection.execute("""
            ALTER TABLE notes
            ADD COLUMN IF NOT EXISTS embedding_model TEXT
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id BIGSERIAL PRIMARY KEY,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                due_at TIMESTAMPTZ NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                source_event_id BIGINT REFERENCES events(id) ON DELETE SET NULL,
                archived BOOLEAN NOT NULL DEFAULT FALSE,
                embedding vector(1024),
                embedding_model TEXT,
                CHECK (status IN ('open', 'done', 'expired', 'archived'))
            )
        """)

        connection.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS embedding vector(1024)
        """)

        connection.execute("""
            ALTER TABLE tasks
            ADD COLUMN IF NOT EXISTS embedding_model TEXT
        """)

        connection.execute("""
            ALTER TABLE tasks ALTER COLUMN due_at DROP NOT NULL
        """)

        connection.execute("""
            ALTER TABLE tasks ADD COLUMN IF NOT EXISTS work_start_at TIMESTAMPTZ
        """)

        connection.execute("""
            ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 0
        """)

        connection.execute("""
            ALTER TABLE tasks ADD COLUMN IF NOT EXISTS urgency DOUBLE PRECISION NOT NULL DEFAULT 0.5
        """)

        connection.execute("""
            ALTER TABLE tasks ADD COLUMN IF NOT EXISTS percent_complete INTEGER NOT NULL DEFAULT 0
        """)

        connection.execute("""DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='tasks_priority_check') THEN
                ALTER TABLE tasks ADD CONSTRAINT tasks_priority_check CHECK(priority BETWEEN 0 AND 9);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='tasks_urgency_check') THEN
                ALTER TABLE tasks ADD CONSTRAINT tasks_urgency_check CHECK(urgency BETWEEN 0 AND 1);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='tasks_percent_complete_check') THEN
                ALTER TABLE tasks ADD CONSTRAINT tasks_percent_complete_check CHECK(percent_complete BETWEEN 0 AND 100);
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='tasks_work_window_check') THEN
                ALTER TABLE tasks ADD CONSTRAINT tasks_work_window_check CHECK(
                    work_start_at IS NULL OR due_at IS NULL OR work_start_at <= due_at
                );
            END IF;
        END $$""")

        connection.execute("""
            CREATE TABLE IF NOT EXISTS lists (
                id BIGSERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                archived BOOLEAN NOT NULL DEFAULT FALSE,
                embedding vector(1024),
                embedding_model TEXT
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS list_items (
                id BIGSERIAL PRIMARY KEY,
                list_id BIGINT NOT NULL REFERENCES lists(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                source_event_id BIGINT REFERENCES events(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'active',
                archived BOOLEAN NOT NULL DEFAULT FALSE,
                embedding vector(1024),
                embedding_model TEXT,
                CHECK (status IN ('active', 'done', 'archived'))
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS list_items_list_id_idx
            ON list_items(list_id)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_sessions (
                id BIGSERIAL PRIMARY KEY,
                title TEXT,
                source_type TEXT NOT NULL,
                source TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                started_at TIMESTAMPTZ NOT NULL,
                ended_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                CHECK (
                    status IN (
                        'open',
                        'finished',
                        'processing',
                        'completed',
                        'failed'
                    )
                )
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS ingestion_sessions_status_idx
            ON ingestion_sessions(status)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS ingestion_sessions_started_at_idx
            ON ingestion_sessions(started_at DESC)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_chunks (
                id BIGSERIAL PRIMARY KEY,
                session_id BIGINT NOT NULL
                    REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
                sequence BIGINT NOT NULL,
                client_chunk_id TEXT NOT NULL,
                text TEXT NOT NULL,
                source_start_ms BIGINT,
                source_end_ms BIGINT,
                content_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                CHECK (sequence >= 1),
                CHECK (client_chunk_id <> ''),
                CHECK (text <> ''),
                CHECK (source_start_ms IS NULL OR source_start_ms >= 0),
                CHECK (source_end_ms IS NULL OR source_end_ms >= 0),
                CHECK (
                    source_start_ms IS NULL
                    OR source_end_ms IS NULL
                    OR source_end_ms >= source_start_ms
                ),
                UNIQUE (session_id, sequence),
                UNIQUE (session_id, client_chunk_id)
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS ingestion_chunks_session_id_idx
            ON ingestion_chunks(session_id, sequence)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS processing_jobs (
                id BIGSERIAL PRIMARY KEY,
                job_type TEXT NOT NULL,
                ingestion_session_id BIGINT
                    REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
                chunk_id BIGINT
                    REFERENCES ingestion_chunks(id) ON DELETE CASCADE,
                sequence BIGINT,
                status TEXT NOT NULL DEFAULT 'queued',
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                result JSONB,
                attempts INTEGER NOT NULL DEFAULT 0,
                available_at TIMESTAMPTZ NOT NULL,
                locked_at TIMESTAMPTZ,
                locked_by TEXT,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                error TEXT,
                idempotency_key TEXT,
                request_hash TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                CHECK (job_type <> ''),
                CHECK (sequence IS NULL OR sequence >= 1),
                CHECK (attempts >= 0),
                CHECK (status IN ('queued', 'running', 'done', 'failed')),
                CHECK (idempotency_key IS NULL OR idempotency_key <> ''),
                CHECK (
                    (status = 'running' AND locked_at IS NOT NULL AND locked_by IS NOT NULL)
                    OR status <> 'running'
                )
            )
        """)

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS processing_jobs_idempotency_key_uidx
            ON processing_jobs(idempotency_key)
            WHERE idempotency_key IS NOT NULL
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS processing_jobs_claim_idx
            ON processing_jobs(status, available_at, id)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS processing_jobs_session_idx
            ON processing_jobs(ingestion_session_id, sequence, id)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS processing_jobs_chunk_idx
            ON processing_jobs(chunk_id)
            WHERE chunk_id IS NOT NULL
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS ingestion_session_watermarks (
                session_id BIGINT PRIMARY KEY
                    REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
                received_through_sequence BIGINT NOT NULL DEFAULT 0,
                queued_through_sequence BIGINT NOT NULL DEFAULT 0,
                processed_through_sequence BIGINT NOT NULL DEFAULT 0,
                artifact_through_sequence BIGINT NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL,
                CHECK (received_through_sequence >= 0),
                CHECK (queued_through_sequence >= 0),
                CHECK (processed_through_sequence >= 0)
            )
        """)

        connection.execute("""
            ALTER TABLE ingestion_session_watermarks
            ADD COLUMN IF NOT EXISTS artifact_through_sequence BIGINT NOT NULL DEFAULT 0
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS chunk_processing_steps (
                id BIGSERIAL PRIMARY KEY,
                session_id BIGINT NOT NULL
                    REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
                chunk_id BIGINT NOT NULL
                    REFERENCES ingestion_chunks(id) ON DELETE CASCADE,
                sequence BIGINT NOT NULL,
                step_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                processing_job_id BIGINT
                    REFERENCES processing_jobs(id) ON DELETE SET NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                CHECK (sequence >= 1),
                CHECK (step_type <> ''),
                CHECK (attempts >= 0),
                CHECK (status IN ('pending', 'queued', 'running', 'done', 'failed')),
                UNIQUE (chunk_id, step_type)
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS chunk_processing_steps_session_idx
            ON chunk_processing_steps(session_id, step_type, sequence)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS chunk_processing_steps_job_idx
            ON chunk_processing_steps(processing_job_id)
            WHERE processing_job_id IS NOT NULL
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS semantic_segments (
                id BIGSERIAL PRIMARY KEY,
                session_id BIGINT NOT NULL
                    REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
                chunk_id BIGINT NOT NULL
                    REFERENCES ingestion_chunks(id) ON DELETE CASCADE,
                sequence BIGINT NOT NULL,
                segment_index INTEGER NOT NULL,
                segment_type TEXT NOT NULL,
                text TEXT NOT NULL,
                confidence DOUBLE PRECISION NOT NULL,
                source_start_ms BIGINT,
                source_end_ms BIGINT,
                context_before TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL,
                processor_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'confirmed',
                superseded_by_segment_id BIGINT
                    REFERENCES semantic_segments(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                CHECK (sequence >= 1),
                CHECK (segment_index >= 1),
                CHECK (text <> ''),
                CHECK (confidence >= 0 AND confidence <= 1),
                CHECK (source_start_ms IS NULL OR source_start_ms >= 0),
                CHECK (source_end_ms IS NULL OR source_end_ms >= 0),
                CHECK (
                    source_start_ms IS NULL OR source_end_ms IS NULL
                    OR source_end_ms >= source_start_ms
                ),
                CHECK (
                    segment_type IN (
                        'statement', 'note_candidate', 'task_candidate',
                        'list_item_candidate', 'question', 'other'
                    )
                ),
                CHECK (status IN ('provisional', 'confirmed', 'superseded')),
                UNIQUE (chunk_id, segment_index)
            )
        """)

        connection.execute("""
            ALTER TABLE semantic_segments
            ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'confirmed'
        """)

        connection.execute("""
            ALTER TABLE semantic_segments
            ADD COLUMN IF NOT EXISTS superseded_by_segment_id BIGINT
                REFERENCES semantic_segments(id) ON DELETE SET NULL
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS semantic_segments_session_idx
            ON semantic_segments(session_id, sequence, segment_index)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS session_artifacts (
                id BIGSERIAL PRIMARY KEY,
                session_id BIGINT NOT NULL
                    REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
                artifact_type TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                confidence DOUBLE PRECISION NOT NULL,
                origin_key TEXT NOT NULL UNIQUE,
                superseded_by_artifact_id BIGINT
                    REFERENCES session_artifacts(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                CHECK (
                    artifact_type IN (
                        'note', 'task', 'list', 'list_item', 'fact', 'decision'
                    )
                ),
                CHECK (content <> ''),
                CHECK (status IN ('active', 'confirmed', 'superseded', 'dismissed')),
                CHECK (confidence >= 0 AND confidence <= 1)
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS session_artifacts_session_idx
            ON session_artifacts(session_id, status, updated_at DESC)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS session_artifact_sources (
                artifact_id BIGINT NOT NULL
                    REFERENCES session_artifacts(id) ON DELETE CASCADE,
                segment_id BIGINT NOT NULL
                    REFERENCES semantic_segments(id) ON DELETE CASCADE,
                relation TEXT NOT NULL DEFAULT 'source',
                created_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (artifact_id, segment_id)
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS session_artifact_sources_segment_idx
            ON session_artifact_sources(segment_id)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS session_topics (
                id BIGSERIAL PRIMARY KEY,
                session_id BIGINT NOT NULL REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                normalized_key TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                confidence DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                CHECK (title <> ''),
                CHECK (normalized_key <> ''),
                CHECK (status IN ('active', 'superseded', 'dismissed')),
                CHECK (confidence >= 0 AND confidence <= 1),
                UNIQUE (session_id, normalized_key)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS session_artifact_topics (
                artifact_id BIGINT NOT NULL REFERENCES session_artifacts(id) ON DELETE CASCADE,
                topic_id BIGINT NOT NULL REFERENCES session_topics(id) ON DELETE CASCADE,
                relation TEXT NOT NULL DEFAULT 'primary_topic',
                confidence DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                CHECK (relation IN ('primary_topic', 'related_topic', 'project', 'person', 'document')),
                CHECK (confidence >= 0 AND confidence <= 1),
                PRIMARY KEY (artifact_id, topic_id, relation)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS evidence_quotes (
                id BIGSERIAL PRIMARY KEY,
                session_id BIGINT NOT NULL REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
                chunk_id BIGINT NOT NULL REFERENCES ingestion_chunks(id) ON DELETE CASCADE,
                segment_id BIGINT REFERENCES semantic_segments(id) ON DELETE SET NULL,
                artifact_id BIGINT REFERENCES session_artifacts(id) ON DELETE CASCADE,
                quote_text TEXT NOT NULL,
                char_start INTEGER NOT NULL,
                char_end INTEGER NOT NULL,
                source_start_ms BIGINT,
                source_end_ms BIGINT,
                created_at TIMESTAMPTZ NOT NULL,
                CHECK (quote_text <> ''),
                CHECK (char_start >= 0 AND char_end > char_start),
                CHECK (source_start_ms IS NULL OR source_start_ms >= 0),
                CHECK (source_end_ms IS NULL OR source_end_ms >= source_start_ms),
                UNIQUE (artifact_id, chunk_id, char_start, char_end)
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS evidence_quotes_session_idx
            ON evidence_quotes(session_id, chunk_id, char_start)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS session_questions (
                id BIGSERIAL PRIMARY KEY,
                session_id BIGINT NOT NULL REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
                topic_id BIGINT REFERENCES session_topics(id) ON DELETE SET NULL,
                question_text TEXT NOT NULL,
                normalized_key TEXT NOT NULL,
                question_kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                confidence DOUBLE PRECISION NOT NULL,
                priority DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                answer_text TEXT,
                answer_source TEXT,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                CHECK (question_text <> ''),
                CHECK (question_kind IN ('explicit', 'implicit')),
                CHECK (status IN ('open', 'answered', 'dismissed')),
                CHECK (confidence >= 0 AND confidence <= 1),
                CHECK (priority >= 0 AND priority <= 1),
                UNIQUE (session_id, normalized_key)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS session_question_sources (
                question_id BIGINT NOT NULL REFERENCES session_questions(id) ON DELETE CASCADE,
                segment_id BIGINT NOT NULL REFERENCES semantic_segments(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (question_id, segment_id)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS session_question_budgets (
                session_id BIGINT PRIMARY KEY REFERENCES ingestion_sessions(id) ON DELETE CASCADE,
                max_open_questions INTEGER NOT NULL DEFAULT 12,
                max_questions_per_topic INTEGER NOT NULL DEFAULT 4,
                updated_at TIMESTAMPTZ NOT NULL,
                CHECK (max_open_questions >= 0),
                CHECK (max_questions_per_topic >= 0)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_activity (
                id BIGSERIAL PRIMARY KEY,
                knowledge_type TEXT NOT NULL,
                knowledge_id BIGINT NOT NULL,
                activity_type TEXT NOT NULL,
                session_id BIGINT REFERENCES ingestion_sessions(id) ON DELETE SET NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL,
                CHECK (knowledge_type IN ('note','task','list','list_item','session_artifact','topic')),
                CHECK (activity_type IN ('retrieved','activated','displayed','opened','cited','updated'))
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS knowledge_activity_subject_idx
            ON knowledge_activity(knowledge_type,knowledge_id,created_at DESC)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS knowledge_activity_time_idx
            ON knowledge_activity(created_at DESC,activity_type)
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_signals (
                knowledge_type TEXT NOT NULL,
                knowledge_id BIGINT NOT NULL,
                evidence_count INTEGER NOT NULL DEFAULT 0,
                independent_session_count INTEGER NOT NULL DEFAULT 0,
                activation_count INTEGER NOT NULL DEFAULT 0,
                access_count INTEGER NOT NULL DEFAULT 0,
                last_activated_at TIMESTAMPTZ,
                last_accessed_at TIMESTAMPTZ,
                importance_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                trend_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                calculated_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY(knowledge_type,knowledge_id),
                CHECK (importance_score >= 0 AND importance_score <= 1),
                CHECK (trend_score >= -1 AND trend_score <= 1)
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_sources (
                id BIGSERIAL PRIMARY KEY,
                knowledge_type TEXT NOT NULL,
                knowledge_id BIGINT NOT NULL,
                event_id BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                relation TEXT NOT NULL DEFAULT 'source',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (knowledge_type, knowledge_id, event_id),
                CHECK (
                    knowledge_type IN (
                        'note',
                        'task',
                        'list',
                        'list_item'
                    )
                )
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS knowledge_sources_knowledge_idx
            ON knowledge_sources(knowledge_type, knowledge_id)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS knowledge_sources_event_idx
            ON knowledge_sources(event_id)
        """)

        connection.execute("""
            INSERT INTO knowledge_sources (
                knowledge_type,
                knowledge_id,
                event_id,
                relation
            )
            SELECT
                'note',
                id,
                source_event_id,
                'legacy_source'
            FROM notes
            WHERE source_event_id IS NOT NULL
            ON CONFLICT (knowledge_type, knowledge_id, event_id)
            DO NOTHING
        """)

        connection.execute("""
            INSERT INTO knowledge_sources (
                knowledge_type,
                knowledge_id,
                event_id,
                relation
            )
            SELECT
                'task',
                id,
                source_event_id,
                'legacy_source'
            FROM tasks
            WHERE source_event_id IS NOT NULL
            ON CONFLICT (knowledge_type, knowledge_id, event_id)
            DO NOTHING
        """)

        connection.execute("""
            INSERT INTO knowledge_sources (
                knowledge_type,
                knowledge_id,
                event_id,
                relation
            )
            SELECT
                'list_item',
                id,
                source_event_id,
                'legacy_source'
            FROM list_items
            WHERE source_event_id IS NOT NULL
            ON CONFLICT (knowledge_type, knowledge_id, event_id)
            DO NOTHING
        """)

        connection.execute("""
            INSERT INTO knowledge_sources (
                knowledge_type,
                knowledge_id,
                event_id,
                relation
            )
            SELECT DISTINCT
                'list',
                list_id,
                source_event_id,
                'item_source'
            FROM list_items
            WHERE source_event_id IS NOT NULL
            ON CONFLICT (knowledge_type, knowledge_id, event_id)
            DO NOTHING
        """)

        connection.commit()


def init_db():
    """Bootstrap once, then apply explicit versioned migrations."""
    with get_db_connection() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS schema_migrations(
            version TEXT PRIMARY KEY, description TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL
        )""")
        baseline=connection.execute("SELECT 1 FROM schema_migrations WHERE version='0001_baseline'").fetchone()
        connection.commit()
    if baseline is None:
        _bootstrap_schema()
        from datetime import datetime
        from .config import TIMEZONE
        with get_db_connection() as connection:
            connection.execute("INSERT INTO schema_migrations(version,description,applied_at) VALUES('0001_baseline','Existing schema baseline',%s) ON CONFLICT DO NOTHING",(datetime.now(TIMEZONE),))
            connection.commit()
    from .migrations import apply_pending_migrations
    apply_pending_migrations()
