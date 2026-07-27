from main import compact_title, expand_rule_tokens


def test_expand_next_year_token():
    value = {"groups": [["LDO ${NEXT_YEAR}"]]}
    assert expand_rule_tokens(value, next_year=2027) == {"groups": [["LDO 2027"]]}


def test_compact_title_limits_length():
    value = compact_title("palavra " * 100, limit=80)
    assert len(value) <= 80
    assert value.endswith("…")
