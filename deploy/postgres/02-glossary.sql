-- GOLD business glossary: the agreed meaning of each business term.
-- The Definitions agent searches this table so that "revenue" means the same
-- thing no matter who asks. Replace these rows with your own definitions.

CREATE TABLE glossary
(
    term        TEXT PRIMARY KEY,
    synonyms    TEXT NOT NULL DEFAULT '',
    definition  TEXT NOT NULL,
    sql_hint    TEXT NOT NULL DEFAULT '',
    owner       TEXT NOT NULL DEFAULT 'Finance',
    search      TSVECTOR GENERATED ALWAYS AS (
                    setweight(to_tsvector('english', term), 'A') ||
                    setweight(to_tsvector('english', synonyms), 'A') ||
                    setweight(to_tsvector('english', definition), 'B')
                ) STORED
);

CREATE INDEX glossary_search_idx ON glossary USING GIN (search);

INSERT INTO glossary (term, synonyms, definition, sql_hint, owner) VALUES
(
    'revenue',
    'sales, net sales, turnover, income, money made, earnings',
    'Revenue is the sum of unit price times quantity over invoice lines. Attribute it to a country with invoice.billing_country and to a period with invoice.invoice_date. There are no discounts, taxes or refunds in this dataset.',
    'SUM(invoice_line.unit_price * invoice_line.quantity) FROM invoice_line JOIN invoice USING (invoice_id)',
    'Finance'
),
(
    'last year',
    'previous year, prior year, latest full year, most recent year',
    '"Last year" means the most recent calendar year that has invoices in the data, not the current calendar year. Find it with MAX(EXTRACT(YEAR FROM invoice_date)).',
    'EXTRACT(YEAR FROM invoice.invoice_date) = (SELECT MAX(EXTRACT(YEAR FROM invoice_date)) FROM invoice)',
    'Finance'
),
(
    'active customer',
    'active customers, active accounts, current customers, inactive customers, been active, were active',
    'An active customer has at least one invoice in the 12 months up to the latest invoice date in the data.',
    'invoice_date > (SELECT MAX(invoice_date) FROM invoice) - INTERVAL ''12 months''',
    'Sales Operations'
),
(
    'average order value',
    'aov, average basket, average invoice value, average deal size',
    'Average order value is revenue divided by the number of invoices in the same period.',
    'SUM(il.unit_price * il.quantity) / COUNT(DISTINCT i.invoice_id)',
    'Finance'
),
(
    'units sold',
    'units, volume, tracks sold, quantity sold',
    'Units sold is the sum of invoice_line.quantity. Each unit is one purchased track.',
    'SUM(invoice_line.quantity)',
    'Sales Operations'
),
(
    'top genre',
    'best selling genre, most popular genre, leading genre',
    'The top genre is ranked by revenue, not by number of tracks in the catalogue, unless the question explicitly asks about the catalogue.',
    'JOIN track USING (track_id) JOIN genre USING (genre_id) ... ORDER BY revenue DESC',
    'Marketing'
),
(
    'customer lifetime value',
    'clv, ltv, lifetime value, total customer spend',
    'Customer lifetime value is all revenue from one customer across every invoice in the data.',
    'SUM(il.unit_price * il.quantity) GROUP BY invoice.customer_id',
    'Finance'
),
(
    'sales rep performance',
    'sales rep, sales reps, rep performance, account manager, support rep, quota attainment',
    'A sales rep is credited with revenue from the customers assigned to them through customer.support_rep_id, which points to employee.employee_id.',
    'JOIN customer c ON c.customer_id = i.customer_id JOIN employee e ON e.employee_id = c.support_rep_id',
    'Sales Operations'
),
(
    'region',
    'territory, geography, market, area',
    'This dataset has no region hierarchy. Treat "region" as billing country, and say so in the answer.',
    'invoice.billing_country',
    'Sales Operations'
),
(
    'personal data',
    'pii, customer contact details, email, phone number, address',
    'Customer email, phone, fax and street address are personal data. Query results mask them. Never try to reveal or reconstruct them.',
    '',
    'Legal'
);

-- Verified queries: questions an analyst has answered with SQL they vouch for.
-- The Definitions agent retrieves the closest ones for each question and passes them
-- to the SQL agent as worked examples. `gold verify-queries` checks every one in CI.
-- Keep them out of apps/data_analyst/evals/questions.jsonl, or the evaluation stops being a fair test.

CREATE TABLE verified_queries
(
    id          SERIAL PRIMARY KEY,
    question    TEXT NOT NULL UNIQUE,
    sql         TEXT NOT NULL,
    verified_by TEXT NOT NULL,
    verified_at DATE NOT NULL DEFAULT CURRENT_DATE,
    search      TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', question)) STORED
);

CREATE INDEX verified_queries_search_idx ON verified_queries USING GIN (search);

INSERT INTO verified_queries (question, sql, verified_by, verified_at) VALUES
(
    'What was revenue in each country for the latest year?',
    'SELECT i.billing_country, ROUND(SUM(il.unit_price * il.quantity), 2) AS revenue FROM invoice_line il JOIN invoice i ON i.invoice_id = il.invoice_id WHERE EXTRACT(YEAR FROM i.invoice_date) = (SELECT MAX(EXTRACT(YEAR FROM invoice_date)) FROM invoice) GROUP BY i.billing_country ORDER BY revenue DESC',
    'finance.analytics@example.com', '2026-09-01'
),
(
    'How many active customers are there in each country?',
    'SELECT c.country, COUNT(DISTINCT c.customer_id) AS active_customers FROM customer c JOIN invoice i ON i.customer_id = c.customer_id WHERE i.invoice_date > (SELECT MAX(invoice_date) FROM invoice) - INTERVAL ''12 months'' GROUP BY c.country ORDER BY active_customers DESC',
    'salesops.analytics@example.com', '2026-09-01'
),
(
    'Which sales rep generated the most revenue in the latest year?',
    'SELECT e.first_name || '' '' || e.last_name AS sales_rep, ROUND(SUM(il.unit_price * il.quantity), 2) AS revenue FROM invoice_line il JOIN invoice i ON i.invoice_id = il.invoice_id JOIN customer c ON c.customer_id = i.customer_id JOIN employee e ON e.employee_id = c.support_rep_id WHERE EXTRACT(YEAR FROM i.invoice_date) = (SELECT MAX(EXTRACT(YEAR FROM invoice_date)) FROM invoice) GROUP BY e.employee_id, e.first_name, e.last_name ORDER BY revenue DESC LIMIT 1',
    'salesops.analytics@example.com', '2026-09-01'
),
(
    'What is the average order value by year?',
    'SELECT EXTRACT(YEAR FROM i.invoice_date) AS year, ROUND(SUM(il.unit_price * il.quantity) / COUNT(DISTINCT i.invoice_id), 2) AS average_order_value FROM invoice_line il JOIN invoice i ON i.invoice_id = il.invoice_id GROUP BY 1 ORDER BY 1',
    'finance.analytics@example.com', '2026-09-01'
),
(
    'Which genres earned the most revenue overall?',
    'SELECT g.name AS genre, ROUND(SUM(il.unit_price * il.quantity), 2) AS revenue FROM invoice_line il JOIN track t ON t.track_id = il.track_id JOIN genre g ON g.genre_id = t.genre_id GROUP BY g.name ORDER BY revenue DESC LIMIT 5',
    'marketing.analytics@example.com', '2026-09-01'
),
(
    'How many units were sold per month in the latest year?',
    'SELECT EXTRACT(MONTH FROM i.invoice_date) AS month, SUM(il.quantity) AS units_sold FROM invoice_line il JOIN invoice i ON i.invoice_id = il.invoice_id WHERE EXTRACT(YEAR FROM i.invoice_date) = (SELECT MAX(EXTRACT(YEAR FROM invoice_date)) FROM invoice) GROUP BY 1 ORDER BY 1',
    'salesops.analytics@example.com', '2026-09-01'
);
