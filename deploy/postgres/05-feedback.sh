#!/bin/sh
# The feedback loop's review queue, and the two logins that touch it:
#   gold_feedback  used by the orchestrator: can add feedback, and nothing else
#   gold_curator   used by analysts (gold feedback ...): can review feedback and add verified queries
# GOLD's query login (gold_reader) stays read-only and cannot see this table.
set -eu

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -v feedback_password="${GOLD_FEEDBACK_PASSWORD:-gold_feedback}" \
     -v curator_password="${GOLD_CURATOR_PASSWORD:-gold_curator}" <<'SQL'
CREATE TABLE feedback
(
    id            SERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    answer_id     TEXT NOT NULL,
    user_id       TEXT,
    question      TEXT NOT NULL,
    sql_ran       TEXT,
    rating        TEXT NOT NULL CHECK (rating IN ('up', 'down')),
    comment       TEXT,
    corrected_sql TEXT,
    status        TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'promoted', 'dismissed')),
    reviewed_by   TEXT,
    reviewed_at   TIMESTAMPTZ
);

CREATE ROLE gold_feedback LOGIN PASSWORD :'feedback_password';
GRANT CONNECT ON DATABASE :"DBNAME" TO gold_feedback;
GRANT USAGE ON SCHEMA public TO gold_feedback;
GRANT INSERT ON feedback TO gold_feedback;
GRANT USAGE ON SEQUENCE feedback_id_seq TO gold_feedback;

CREATE ROLE gold_curator LOGIN PASSWORD :'curator_password';
GRANT CONNECT ON DATABASE :"DBNAME" TO gold_curator;
GRANT USAGE ON SCHEMA public TO gold_curator;
GRANT SELECT, UPDATE (status, reviewed_by, reviewed_at) ON feedback TO gold_curator;
GRANT SELECT, INSERT ON verified_queries TO gold_curator;
GRANT USAGE ON SEQUENCE verified_queries_id_seq TO gold_curator;
SQL
