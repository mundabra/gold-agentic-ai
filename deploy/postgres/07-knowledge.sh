#!/bin/sh
# Knowledge retrieval (gold/knowledge): pgvector, and the one login that manages the documents' passages.
#   gold_knowledge  owns the knowledge schema (the passages and their embeddings), and nothing else:
#                   it cannot read business data, and GOLD's other logins cannot read knowledge.
# Needs the vector extension: the pgvector/pgvector Postgres image has it, and so do most managed Postgres services.
set -eu

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -v knowledge_password="${GOLD_KNOWLEDGE_PASSWORD:-gold_knowledge}" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;

CREATE ROLE gold_knowledge LOGIN PASSWORD :'knowledge_password';
GRANT CONNECT ON DATABASE :"DBNAME" TO gold_knowledge;
CREATE SCHEMA knowledge AUTHORIZATION gold_knowledge;
REVOKE ALL ON SCHEMA knowledge FROM PUBLIC;
ALTER ROLE gold_knowledge SET statement_timeout = '30s';
ALTER ROLE gold_knowledge SET search_path = knowledge, public;
SQL
