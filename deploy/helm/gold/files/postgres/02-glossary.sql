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
