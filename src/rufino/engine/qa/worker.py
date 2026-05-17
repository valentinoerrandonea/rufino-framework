from pathlib import Path
from typing import Callable

from rufino.engine.qa.store import QuestionStore
from rufino.engine.qa.callback_registry import CallbackRegistry


def poll_and_dispatch(
    *,
    vault_root: Path,
    state_dir: Path,
    handler: Callable,
) -> int:
    """For every question with answer present, invoke handler() and mark answered.

    Returns the number of callbacks dispatched.
    """
    store = QuestionStore(vault_root / "questions")
    registry = CallbackRegistry(state_dir / "callbacks.json")
    dispatched = 0

    for p in (vault_root / "questions").glob("*.md"):
        if not p.is_file():
            continue
        slug = p.stem
        answer = store.get_answer(slug)
        if answer is None:
            continue

        cb = registry.consume(slug)
        if cb is None:
            # Question file exists with answer but no callback was registered for it
            continue

        handler(
            adapter_name=cb.adapter_name,
            adapter_state=cb.adapter_state,
            answer=answer,
        )
        store.mark_answered(slug)
        dispatched += 1

    return dispatched
