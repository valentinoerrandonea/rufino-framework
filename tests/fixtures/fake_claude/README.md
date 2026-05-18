# fake_claude

Replaces the real `claude` CLI for testing `rufino process-batch`.

Tests put this dir on PATH (`PATH = fake_claude_dir + os.pathsep + PATH`), then
spawn workers as usual. Mode is selected via `FAKE_CLAUDE_MODE` env var; notes
to process are passed via `FAKE_CLAUDE_NOTES` (newline- or os.pathsep-separated
absolute paths).

Modes:
- `augment` (default): valid augmented/<slug>.md + deltas/<slug>.json
- `augment_bad`: outputs that fail validation
- `qa`: pending/<slug>.json (Q&A path)
- `session_expired`: exit 41
- `empty`: exit 0, no outputs
- `hang`: sleep forever (force a timeout in the caller)
