import subprocess
from dataclasses import dataclass
from pathlib import Path

from rufino.engine.query.note_ref import NoteRef


@dataclass
class LexicalBackend:
    vault_root: Path

    def search(self, query: str) -> list[NoteRef]:
        try:
            completed = subprocess.run(
                ["rg", "-l", "--type", "md", query, str(self.vault_root)],
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
        for p in self.vault_root.rglob("*.md"):
            if query.lower() in p.read_text().lower():
                results.append(
                    NoteRef(relative_path=str(p.relative_to(self.vault_root)))
                )
        return results
