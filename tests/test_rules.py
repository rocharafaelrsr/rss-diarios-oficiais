from rules import Rule


def test_atub_unconditional_phrase_matches():
    rule = Rule.from_dict(
        {
            "id": "atub",
            "label": "ATUB",
            "sources": ["dodf"],
            "priority": 10,
            "any_phrases": ["atividades urbanas"],
            "context_any": ["concurso"],
            "unconditional_phrases": ["auditor fiscal de atividades urbanas"],
        }
    )
    assert rule.match("dodf", "Nomeia candidatos ao cargo de Auditor Fiscal de Atividades Urbanas")


def test_generic_urban_activity_does_not_match_without_context():
    rule = Rule.from_dict(
        {
            "id": "atub",
            "label": "ATUB",
            "sources": ["dodf"],
            "priority": 10,
            "any_phrases": ["atividades urbanas"],
            "context_any": ["concurso", "nomeação"],
        }
    )
    assert rule.match("dodf", "Relatório estatístico de atividades urbanas regulares") is None


def test_authorization_requires_both_groups():
    rule = Rule.from_dict(
        {
            "id": "autorizacao_concurso",
            "label": "Autorização",
            "sources": ["dou"],
            "priority": 9,
            "all_groups": [["concurso público"], ["autoriza", "autorização"]],
        }
    )
    assert rule.match("dou", "Portaria autoriza a realização de concurso público")
    assert rule.match("dou", "Resultado final do concurso público") is None


def test_exact_cargo_still_requires_contest_context():
    rule = Rule.from_dict(
        {
            "id": "atub",
            "label": "ATUB",
            "sources": ["dodf"],
            "priority": 10,
            "any_phrases": ["auditor fiscal de atividades urbanas"],
            "context_any": ["concurso", "nomeia", "candidato"],
            "unconditional_phrases": ["edital nº 01/2022"],
        }
    )
    assert rule.match("dodf", "Aposentadoria de Auditor Fiscal de Atividades Urbanas") is None
    assert rule.match("dodf", "Nomeia candidato ao cargo de Auditor Fiscal de Atividades Urbanas")


def test_proximity_rejects_terms_from_distant_acts():
    rule = Rule.from_dict(
        {
            "id": "auth",
            "label": "Autorização",
            "sources": ["dodf"],
            "priority": 9,
            "max_span_chars": 100,
            "all_groups": [["concurso público"], ["autoriza"]],
        }
    )
    text = "Autoriza despesa administrativa. " + ("x" * 500) + " Concurso público homologado."
    assert rule.match("dodf", text) is None
    assert rule.match("dodf", "Portaria autoriza a realização de concurso público")
