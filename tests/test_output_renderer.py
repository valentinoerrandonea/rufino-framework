from rufino.engine.output.renderer import render_template


def test_renders_with_query_results():
    template = """# Digest

## Notas
{% for n in query.notas_semana -%}
- {{ n }}
{% endfor -%}
"""
    output = render_template(
        template=template,
        query={"notas_semana": ["nota1.md", "nota2.md"]},
        event={},
    )
    assert "- nota1.md" in output
    assert "- nota2.md" in output


def test_renders_with_event_context():
    template = "Hola {{ event.attendee }}"
    output = render_template(
        template=template,
        query={},
        event={"attendee": "beto"},
    )
    assert output == "Hola beto"
