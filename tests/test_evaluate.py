from gold.evaluate import same_result


def test_same_rows_in_any_order_and_column_order_match():
    assert same_result([["USA", 85.14], ["Canada", 72.27]], [[72.27, "Canada"], ["USA", 85.140]])


def test_extra_columns_are_tolerated_but_missing_values_are_not():
    assert same_result([["Rock"]], [["Rock", 174.24]])
    assert not same_result([["Rock", 174.24]], [["Rock"]])


def test_numbers_compare_to_two_decimals_and_row_counts_must_match():
    assert same_result([[5.65]], [[5.6499999]])
    assert same_result([[2024]], [[2024.0]])
    assert not same_result([[46]], [[59]])
    assert not same_result([["USA"]], [["USA"], ["Canada"]])


def test_rows_are_matched_as_a_whole_not_greedily():
    assert same_result([[1], [2]], [[1, 2], [1, 3]])


def test_names_match_whether_in_one_column_or_two():
    assert same_result([["Jane", "Peacock"]], [["Jane Peacock", 21]])
    assert not same_result([["Jane", "Peacock"]], [["Margaret Park"]])
