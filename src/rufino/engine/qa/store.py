import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from rufino.engine.process.helpers.frontmatter import (
    parse_frontmatter,
    FrontmatterError,
)


_log = logging.getLogger(__name__)


class QuestionStoreError(Exception):
    """Raised on invalid slug or unsafe path access."""


@dataclass(frozen=True)
class Question:
    slug: str
    template_name: str
    answer: str | None
    path: Path


class QuestionStore:
    """Read/write question files in the vault's questions/ directory.

    Error model:
    - `_read_answer` (and therefore `get_answer`) RAISES on malformed answers
      so the caller can react (e.g. surface to the user).
    - `list_pending` SKIPS malformed files with a logged warning so a single
      bad file doesn't break enumeration.
    """

    def __init__(self, questions_dir: Path) -> None:
        self._dir = questions_dir
        (questions_dir / "answered").mkdir(parents=True, exist_ok=True)

    def write_question(self, *, slug: str, template_name: str, body: str) -> str:
        path = self._safe_path(slug, answered=False)
        # yaml.safe_dump escapes/quotes template_name if it contains YAML special
        # characters; the empty `answer:` line stays plain so the user can type
        # their answer directly after the colon.
        name_yaml = yaml.safe_dump(
            {"template_name": template_name}, default_flow_style=False
        )
        body_nl = body if body.endswith("\n") else body + "\n"
        content = f"---\n{name_yaml}answer:\n---\n{body_nl}"
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(content)
            tmp.replace(path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return slug

    def get_answer(self, slug: str) -> str | None:
        path = self._safe_path(slug, answered=False)
        if not path.exists():
            answered = self._safe_path(slug, answered=True)
            if answered.exists():
                return self._read_answer(answered)
            return None
        return self._read_answer(path)

    def list_pending(self) -> list[Question]:
        out: list[Question] = []
        for p in self._dir.glob("*.md"):
            if not p.is_file():
                continue
            try:
                fm, _ = parse_frontmatter(p.read_text())
            except FrontmatterError as e:
                _log.warning("skipping %s in list_pending: %s", p.name, e)
                continue
            answer = fm.get("answer")
            if answer is None or (isinstance(answer, str) and answer.strip() == ""):
                out.append(Question(
                    slug=p.stem,
                    template_name=fm.get("template_name", "unknown"),
                    answer=None,
                    path=p,
                ))
            elif not isinstance(answer, str):
                # Same malformed-answer condition that `_read_answer` rejects,
                # but here we skip + log to keep enumeration robust.
                _log.warning(
                    "skipping %s in list_pending: answer parsed as %s; user must quote it",
                    p.name, type(answer).__name__,
                )
        return out

    def mark_answered(self, slug: str) -> None:
        src = self._safe_path(slug, answered=False)
        dst = self._safe_path(slug, answered=True)
        src.rename(dst)

    def _safe_path(self, slug: str, *, answered: bool) -> Path:
        base = (self._dir / "answered") if answered else self._dir
        candidate = (base / f"{slug}.md").resolve()
        root = base.resolve()
        # Reject escape (ancestor check) AND reject subdirectory components
        # (slug must yield a flat filename directly under `base`).
        if candidate.parent != root:
            raise QuestionStoreError(
                f"slug must be flat (no path components or traversal): {slug!r}"
            )
        return candidate

    def _read_answer(self, path: Path) -> str | None:
        fm, _ = parse_frontmatter(path.read_text())
        ans = fm.get("answer")
        if ans is None:
            return None
        if isinstance(ans, str):
            if ans.strip() == "":
                return None
            return ans
        # YAML bareword (yes/no/true/false/numbers/dates) parsed as non-string.
        # Reject — the user must quote the answer to avoid silent type coercion.
        raise QuestionStoreError(
            f"answer in {path.name} parsed as {type(ans).__name__} "
            f"({ans!r}); wrap the value in quotes (e.g. answer: \"yes\")"
        )
