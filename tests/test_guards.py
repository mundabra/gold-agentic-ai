import pytest

from gold.guards import UnsafeQuery, check_read_only, mask_rows


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select * from invoice;",
        "WITH t AS (SELECT 1 AS x) SELECT x FROM t",
        "SELECT name FROM artist WHERE name = 'Do It; Drop It'",  # keywords inside a string are fine
        "-- a comment\nSELECT 1",
        "SELECT description AS comment, 'set' AS note FROM t",  # SQL words as names are fine
        "SELECT a FROM t UNION SELECT b FROM u",
    ],
)
def test_reads_are_allowed(sql):
    assert check_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM customer",
        "UPDATE invoice SET total = 0",
        "DROP TABLE customer",
        "SELECT 1; DROP TABLE customer",
        "WITH gone AS (DELETE FROM customer RETURNING *) SELECT * FROM gone",
        "SELECT * INTO backup FROM customer",
        "SELECT pg_sleep(100)",
        "SELECT pg_terminate_backend(42)",
        "SELECT set_config('default_transaction_read_only', 'off', false)",
        "SELECT query_to_xml('select 1', true, true, '')",
        "SELECT E'\\'' AS x; COMMIT; DELETE FROM glossary; SELECT ''",
        "COPY customer TO '/tmp/x'",
        "SELECT a FROM t FOR UPDATE",
        "LOCK TABLE customer",
        "SET search_path TO other",
        "TRUNCATE customer",
        "CALL refresh_everything()",
        "",
    ],
)
def test_writes_and_tricks_are_refused(sql):
    with pytest.raises(UnsafeQuery):
        check_read_only(sql)


def test_mask_rows_hides_pii_columns_and_scrubs_free_text():
    cols = ["customer", "email", "billing_address", "note", "invoice_date"]
    rows = [["Ana", "ana@example.com", "1 Main St", "call +1 (555) 123-4567 or ana@example.com", "2021-01-01"]]
    masked, which = mask_rows(cols, rows, {"email", "address", "phone"})
    assert which == ["email", "billing_address"]
    assert masked[0][0] == "Ana"
    assert masked[0][1] == masked[0][2] == "[masked]"
    assert masked[0][3] == "call [masked phone] or [masked email]"
    assert masked[0][4] == "2021-01-01"  # dates are not phone numbers
