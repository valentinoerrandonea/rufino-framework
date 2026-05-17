import subprocess
from dataclasses import dataclass
from pathlib import Path

from rufino.engine.query.filters import EXCLUDED_DIRS, iter_user_notes
from rufino.engine.query.note_ref import NoteRef


@dataclass
class LexicalBackend:
    vault_root: Path

    def search(self, query: str) -> list[NoteRef]:
        try:
            completed = subprocess.run(
                [
                    "rg", "-l", "--type", "md",
                    *_ripgrep_exclude_globs(),
                    "--", query, str(self.vault_root),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except FileNotFoundError:
            return self._python_fallback(query)

        if completed.returncode == 1:
            return []
        if completed.returncode != 0:
            raise RuntimeError(f"ripgrep failed: {completed.stderr}")

        return [
            NoteRef(relative_path=str(Path(line).relative_to(self.vault_root)))
            for line in completed.stdout.splitlines()
        ]

    def _python_fallback(self, query: str) -> list[NoteRef]:
        results: list[NoteRef] = []
        needle = query.lower()
        for p in iter_user_notes(self.vault_root):
            if needle in p.read_text(encoding="utf-8", errors="replace").lower():
                results.append(
                    NoteRef(relative_path=str(p.relative_to(self.vault_root)))
                )
        return results


def _ripgrep_exclude_globs() -> list[str]:
    """Build --glob '!<dir>' args from EXCLUDED_DIRS plus all dotdirs."""
    args: list[str] = []
    for d in EXCLUDED_DIRS:
        args.extend(["--glob", f"!{d}/"])
    args.extend(["--glob", "!.*/"])  # any dot-prefixed dir (defense in depth)
    return args
