#!/bin/sh
# The Sales copilot app (apps/sales_copilot): CRM activities, and the one login that can write them.
#   gold_reader      (04) can read activities; row-level security shows each rep their own accounts' activities
#   gold_crm_writer  can add an activity, only for an account the signed-in rep can see, and nothing else:
#                    no updates, no deletes, no other tables. GOLD only uses it after a person approves.
set -eu

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -v crm_password="${GOLD_CRM_PASSWORD:-gold_crm_writer}" <<'SQL'
CREATE TABLE crm_activity
(
    activity_id  SERIAL PRIMARY KEY,
    customer_id  INT NOT NULL REFERENCES customer (customer_id),
    kind         TEXT NOT NULL CHECK (kind IN ('call', 'email', 'meeting', 'note')),
    note         TEXT NOT NULL CHECK (length(note) BETWEEN 1 AND 1000),
    follow_up_on DATE,
    logged_by    TEXT NOT NULL,
    approved_by  TEXT,
    action_id    TEXT UNIQUE,            -- the approval's id: an approval replayed adds nothing
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX crm_activity_customer_idx ON crm_activity (customer_id);

-- The sample data is a snapshot that ends on its latest invoice, so "today" for the
-- Sales copilot is that date. With live data, make this return current_date.
-- SECURITY DEFINER: the latest invoice overall, not just the rep's own.
CREATE FUNCTION crm_as_of() RETURNS DATE
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
AS $$ SELECT MAX(invoice_date)::date FROM invoice $$;

-- Reps see and add activities only for accounts they can see (the customer policy in 03).
ALTER TABLE crm_activity ENABLE ROW LEVEL SECURITY;
CREATE POLICY crm_activity_read ON crm_activity FOR SELECT
    USING (gold_rep_scope() IS NULL
           OR EXISTS (SELECT 1 FROM customer c WHERE c.customer_id = crm_activity.customer_id));
CREATE POLICY crm_activity_add ON crm_activity FOR INSERT
    WITH CHECK (gold_rep_scope() IS NULL
                OR EXISTS (SELECT 1 FROM customer c WHERE c.customer_id = crm_activity.customer_id));

GRANT SELECT ON crm_activity TO gold_reader;

CREATE ROLE gold_crm_writer LOGIN PASSWORD :'crm_password';
GRANT CONNECT ON DATABASE :"DBNAME" TO gold_crm_writer;
GRANT USAGE ON SCHEMA public TO gold_crm_writer;
GRANT SELECT, INSERT ON crm_activity TO gold_crm_writer;
GRANT USAGE ON SEQUENCE crm_activity_activity_id_seq TO gold_crm_writer;
GRANT SELECT (customer_id, support_rep_id) ON customer TO gold_crm_writer;   -- for the policy check only
ALTER ROLE gold_crm_writer SET statement_timeout = '10s';

-- The Sales copilot's business term, so every agent means the same thing by it.
INSERT INTO glossary (term, synonyms, definition, sql_hint, owner) VALUES
(
    'at-risk account',
    'at risk, accounts at risk, needs attention, lapsed customer, churn risk, slipping accounts',
    'An at-risk account is a customer whose last purchase was more than 180 days before the latest invoice date in the data.',
    '(SELECT MAX(invoice_date) FROM invoice) - MAX(invoice.invoice_date) > INTERVAL ''180 days''',
    'Sales Operations'
);

-- A few activities so the first account brief has history.
INSERT INTO crm_activity (customer_id, kind, note, follow_up_on, logged_by, approved_by, created_at) VALUES
    (1,  'call',    'Quarterly check-in. Happy with the catalogue; asked about Latin jazz bundles.', '2026-01-15',
         'jane.peacock@example.com', 'jane.peacock@example.com', '2025-12-01 10:00+00'),
    (3,  'email',   'Sent the holiday offer. No reply yet.', '2025-12-30',
         'jane.peacock@example.com', 'jane.peacock@example.com', '2025-12-10 15:30+00'),
    (19, 'meeting', 'Met the media team; interested in a volume licence for internal events.', '2026-01-08',
         'jane.peacock@example.com', 'jane.peacock@example.com', '2025-12-15 09:00+00'),
    (4,  'call',    'Renewal conversation; wants invoices per department.', '2026-01-20',
         'margaret.park@example.com', 'margaret.park@example.com', '2025-12-05 14:00+00'),
    (2,  'note',    'Moved to a new office; update the billing contact.', NULL,
         'steve.johnson@example.com', 'steve.johnson@example.com', '2025-11-28 11:00+00');
SQL
