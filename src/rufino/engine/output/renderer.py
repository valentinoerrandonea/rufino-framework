from jinja2 import Environment, BaseLoader, StrictUndefined


_ENV = Environment(loader=BaseLoader(), undefined=StrictUndefined, autoescape=False)


def render_template(*, template: str, query: dict, event: dict) -> str:
    """Render a jinja2 template with `query.*` and `event.*` available."""
    tmpl = _ENV.from_string(template)
    return tmpl.render(query=query, event=event)
