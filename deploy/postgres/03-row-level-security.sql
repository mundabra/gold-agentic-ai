-- Row-level security: what each signed-in user may see.
--
-- GOLD's data tools set the signed-in user for each query with
--   SET LOCAL gold.user_id = '<user>'
-- (the model's own SQL cannot: SQLGlot refuses SET). Postgres then filters rows:
--   - sales reps see only their own customers, and those customers' invoices
--   - users with full access (finance, leadership) see everything
--   - a signed-in user who is not listed here sees nothing
-- When identity is not in use (no gold.user_id), rows are not filtered.
--
-- For your own data: replace gold_user_access with your entitlements (or a view over
-- your identity system) and write one policy per table that needs filtering.

CREATE TABLE gold_user_access
(
    user_id      TEXT PRIMARY KEY,
    sales_rep_id INT REFERENCES employee (employee_id),
    full_access  BOOLEAN NOT NULL DEFAULT false
);

INSERT INTO gold_user_access (user_id, sales_rep_id, full_access) VALUES
    ('finance@example.com',       NULL, true),
    ('jane.peacock@example.com',  3,    false),
    ('margaret.park@example.com', 4,    false),
    ('steve.johnson@example.com', 5,    false);

-- NULL = no filter; a rep id = only that rep's customers; -1 = nothing.
-- SECURITY DEFINER so it can read gold_user_access, which GOLD's login cannot.
CREATE FUNCTION gold_rep_scope() RETURNS INT
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
AS $$
    SELECT CASE
        WHEN coalesce(current_setting('gold.user_id', true), '') = '' THEN NULL
        WHEN a.full_access THEN NULL
        ELSE coalesce(a.sales_rep_id, -1)
    END
    FROM (SELECT 1) AS one
    LEFT JOIN gold_user_access AS a ON a.user_id = current_setting('gold.user_id', true)
$$;

ALTER TABLE customer ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_line ENABLE ROW LEVEL SECURITY;

CREATE POLICY gold_customer_scope ON customer FOR SELECT
    USING (gold_rep_scope() IS NULL OR support_rep_id = gold_rep_scope());

CREATE POLICY gold_invoice_scope ON invoice FOR SELECT
    USING (gold_rep_scope() IS NULL
           OR EXISTS (SELECT 1 FROM customer c WHERE c.customer_id = invoice.customer_id));

CREATE POLICY gold_invoice_line_scope ON invoice_line FOR SELECT
    USING (gold_rep_scope() IS NULL
           OR EXISTS (SELECT 1 FROM invoice i WHERE i.invoice_id = invoice_line.invoice_id));
