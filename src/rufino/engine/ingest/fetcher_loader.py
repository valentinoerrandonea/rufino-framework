import importlib.util
from pathlib import Path
from typing import Callable


def load_fetcher(adapter_dir: Path) -> Callable:
    """Load adapter_dir/fetcher.py and return its `fetch` function."""
    fetcher_path = adapter_dir / "fetcher.py"
    if not fetcher_path.exists():
        raise FileNotFoundError(f"No fetcher.py in {adapter_dir}")

    spec = importlib.util.spec_from_file_location(
        f"rufino_adapter_{adapter_dir.name}", fetcher_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load fetcher.py at {fetcher_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "fetch") or not callable(module.fetch):
        raise AttributeError(f"{fetcher_path} does not define a callable `fetch`")
    return module.fetch
