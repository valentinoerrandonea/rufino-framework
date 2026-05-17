from dataclasses import dataclass
from pathlib import Path
import yaml


@dataclass(frozen=True)
class Question:
    slug: str
    template_name: str
    answer: str | None
    path: Path


class QuestionStore:
    """Read/write question files in the vault's questions/ directory."""

    def __init__(self, questions_dir: Path) -> None:
        self._dir = questions_dir
        (questions_dir / "answered").mkdir(exist_ok=True)

    def write_question(self, *, slug: str, template_name: str, body: str) -> str:
        path = self._dir / f"{slug}.md"
        path.write_text(
            "---\n"
            f"template_name: {template_name}\n"
            f"answer:\n"
            "---\n"
            f"{body}\n"
        )
        return slug

    def get_answer(self, slug: str) -> str | None:
        path = self._dir / f"{slug}.md"
        if not path.exists():
            answered = self._dir / "answered" / f"{slug}.md"
            if answered.exists():
                return self._read_answer(answered)
            return None
        return self._read_answer(path)

    def list_pending(self) -> list[Question]:
        out: list[Question] = []
        for p in self._dir.glob("*.md"):
            if not p.is_file():
                continue
            fm = self._read_frontmatter(p)
            answer = fm.get("answer")
            if answer is None or (isinstance(answer, str) and answer.strip() == ""):
                out.append(Question(
                    slug=p.stem,
                    template_name=fm.get("template_name", "unknown"),
                    answer=None,
                    path=p,
                ))
        return out

    def mark_answered(self, slug: str) -> None:
        src = self._dir / f"{slug}.md"
        dst = self._dir / "answered" / f"{slug}.md"
        src.rename(dst)

    def _read_answer(self, path: Path) -> str | None:
        fm = self._read_frontmatter(path)
        ans = fm.get("answer")
        if ans is None:
            return None
        if isinstance(ans, str) and ans.strip() == "":
            return None
        return str(ans)

    def _read_frontmatter(self, path: Path) -> dict:
        text = path.read_text()
        if not text.startswith("---\n"):
            return {}
        _, block, _ = text.split("---\n", 2)
        return yaml.safe_load(block) or {}
