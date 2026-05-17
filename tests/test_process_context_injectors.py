from rufino.engine.process.context_injectors import (
    apply_context_injectors,
    StubQueryLayer,
)


def test_injector_renders_query_into_context():
    query_stub = StubQueryLayer(canned_results={
        "tag=materia/ml-i, last 10 by date": ["clase1.md", "clase2.md"],
    })
    injectors = [
        {"name": "apuntes_previos", "query": "tag=materia/<materia>, last 10 by date"},
    ]
    context = apply_context_injectors(
        injectors=injectors,
        variables={"materia": "ml-i"},
        query=query_stub,
    )
    assert "apuntes_previos" in context
    assert "clase1.md" in context["apuntes_previos"]
    assert "clase2.md" in context["apuntes_previos"]


def test_injector_skips_when_variable_missing():
    query_stub = StubQueryLayer(canned_results={})
    injectors = [
        {"name": "x", "query": "tag=<missing_var>"},
    ]
    context = apply_context_injectors(
        injectors=injectors,
        variables={},
        query=query_stub,
    )
    assert context["x"] == "(unable to resolve query — missing variables)"
