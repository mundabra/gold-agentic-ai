#!/bin/sh
# Creates the login GOLD's tools use. The database enforces the rules, so they
# hold even if every check in the application were bypassed:
#   - read-only: SELECT rights only, and read-only transactions by default
#   - personal data: the columns below cannot be read at all, whatever the SQL
#   - no temp tables, no server-administration functions, a statement timeout
# For your own database, grant only the columns GOLD may read in the same way.
set -eu

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -v reader_password="${GOLD_READER_PASSWORD:-gold_reader}" <<'SQL'
CREATE ROLE gold_reader LOGIN PASSWORD :'reader_password';
GRANT CONNECT ON DATABASE :"DBNAME" TO gold_reader;
REVOKE TEMPORARY ON DATABASE :"DBNAME" FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO gold_reader;

-- Tables without personal data: every column.
GRANT SELECT ON album, artist, genre, media_type, playlist, playlist_track, track, invoice_line, glossary TO gold_reader;

-- Tables with personal data: only the columns analysis needs. Email, phone,
-- fax, street address, postal code and birth date are not readable.
GRANT SELECT (customer_id, first_name, last_name, company, city, state, country, support_rep_id) ON customer TO gold_reader;
GRANT SELECT (employee_id, first_name, last_name, title, reports_to, hire_date, city, state, country) ON employee TO gold_reader;
GRANT SELECT (invoice_id, customer_id, invoice_date, billing_city, billing_state, billing_country, total) ON invoice TO gold_reader;

-- Server-administration functions (belt and braces with the SQL checks).
REVOKE EXECUTE ON FUNCTION pg_terminate_backend(integer, bigint), pg_cancel_backend(integer),
    pg_sleep(double precision), pg_sleep_for(interval), pg_sleep_until(timestamp with time zone),
    pg_advisory_lock(bigint), pg_notify(text, text), set_config(text, text, boolean)
    FROM PUBLIC;

ALTER ROLE gold_reader SET default_transaction_read_only = on;
ALTER ROLE gold_reader SET statement_timeout = '10s';
SQL
