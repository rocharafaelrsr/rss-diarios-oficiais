from main import expand_rule_tokens


def test_expand_next_year_token():
    value = {"groups": [["LDO ${NEXT_YEAR}"]]}
    assert expand_rule_tokens(value, next_year=2027) == {"groups": [["LDO 2027"]]}
