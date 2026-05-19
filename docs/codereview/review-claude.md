# Code Review — `rufino process-batch` (v0.1.0)

> **Reviewer:** Claude (Opus 4.7) — multi-agent review (4 reviewers, paralelizados)
> **Fecha:** 2026-05-19
> **Scope:** plan `docs/superpowers/plans/2026-05-18-process-batch-via-claude-orchestration.md` (19 tasks, 4041 líneas)
> **Commits revisados:** 37 commits, 78 archivos, +8959 / −180 líneas (rango `d0a2bd1^..HEAD`)
> **Tests:** 90/90 green en `pytest`
> **Versión:** 0.0.3 → 0.1.0

---

## Executive summary

La implementación es **sólida en lo grueso** y mejora el plan en varios puntos materiales (zip-slip guard out-of-plan, módulo `committer` con state-in-target reemplazando closures, atomic backup/restore en retry, YAML-serialized frontmatter en Q&A, validator con exception types narrowed). El subprocess chokepoint disciplina — toda invocación de `claude` pasa por `runner_helper.run_claude` — se sostiene.

**Pero hay 3 fallas críticas que bloquean shipping:**

1. **`qa-resume` no commitea la nota augmentada al vault.** La feature T16 valida y archiva la pregunta pero nunca mueve la nota al canon. El usuario contesta una Q&A, ve "dispatched=1", la pregunta se va a `answered/`, y su vault queda igual. La nota queda huérfana en `.rufino/runs/<id>/workers/<wid>/augmented/<slug>.md`.
2. **Path traversal vía question YAML en `qa-resume`.** `run_id`, `worker_id` y `slug` se leen del frontmatter de la pregunta y se concatenan a paths sin re-validar. Una pregunta con `run_id: ../../../etc` redirige reads/writes fuera de `.rufino/runs/`.
3. **9 tests fallan en una install limpia** porque `mammoth` y `python-pptx` se importan sin guard, y aunque están en `pyproject.toml`, no hay CI ni `pytest.importorskip`. En cualquier env donde las deps no estén instaladas el suite colapsa.

**Y 2 fallas críticas de documentación:**

4. **`docs/cli-reference.md` no tiene sección de `process-batch`** — y es la doc canonical del CLI, referenciada desde README.
5. **Docs todavía dicen "v0.0.2"** en 7+ archivos con afirmaciones falsas sobre features (e.g. "QA resumption stubbed", "process light/full operativo en v0.0.2").

Las 3 fallas de código (#1, #2, #3) son fixes chicos (< 200 líneas combinadas). Las de docs son sweep + agregar 1 sección.

---

## Recommended action ordering

1. **Bloqueante para release** — fix Critical #1 (qa-resume commit), #2 (qa-resume path traversal), agregar test que falle sin el fix. Sweep v0.0.2 → v0.1.0 en docs.
2. **Antes de README pública** — agregar sección `process-batch` a `docs/cli-reference.md`, documentar `batch_size` en `docs/writing-adapters.md`, decidir si `mammoth`/`python-pptx` son hard deps (entonces CI debe instalarlas) u optional extras (entonces `pytest.importorskip` + reorganizar `pyproject.toml`).
3. **Hardening del happy path** — fix High issues de Q&A pending (per-item degradation en bad slug, defensive try alrededor de `parse_frontmatter` en `_existing_answer_filled`), fix #FAKE_CLAUDE_NOTES leak en qa-resume, demote consolidator-dropped notes a `notes_failed`.
4. **Antes de scaling** — bound stdout/stderr capture en `run_claude` (DoS surface), advisory lock por vault (concurrent process-batch), `:04d` worker_id format si se espera >999 workers.
5. **Test coverage gaps** — E2E con ZIP + CLI + negative path, consolidator happy-path test, NUL-encoded LogEntry round-trip, dispatcher cancellation behavior.

---

## Critical findings (consolidados)

### C1. `qa-resume` no commitea la nota al vault

**File:** `src/rufino/engine/process/batch/qa_resume.py:147-166`
**Plan ref:** T16 (L3399-3711), Design spec §9.
**Impacto:** Pérdida silenciosa de trabajo del usuario. Contradice spec §9: *"The worker's output goes through VALIDATE+RETRY+COMMIT just like a fresh note (a mini-COMMIT scoped to that note's destination + index deltas, under a fresh transaction log)."*

Después de re-ejecutar el worker, la función valida `augmented/<slug>.md` y archiva la pregunta. **No hay `commit()`, no hay `TransactionLog`, no hay movimiento al destino**. El test `tests/test_cli_qa_poll_resumption.py:82-89` no asserta que la nota landea en el vault — solo que la pregunta se movió a `answered/` — así que la falla pasó TDD.

**Fix:** después de `validation.passed`, construir un `ConsolidationPlan` de una sola nota (análogo a `_naive_commit_plan` en `runner.py`), invocar `commit(plan, vault_root, run_dir, tx_log=TransactionLog(run_dir/"qa-resume-<slug>.tx.json"))`, y *después* archivar la pregunta.

**Verificación TDD:** agregar `assert (vault / "<destination_path>").exists()` en el test existente — debe fallar antes del fix.

### C2. Path traversal vía YAML de question en `qa-resume`

**File:** `src/rufino/engine/process/batch/qa_resume.py:70-73, 106`
**Impacto:** Lectura/escritura arbitraria en filesystem. `run_id`, `worker_id` y `pending_note` se concatenan a paths sin validar (`run_dir = vault_root / ".rufino" / "runs" / run_id`). Una pregunta con `run_id: ../../../etc` redirige a cualquier lado. `qa_pending._validate_slug` aplica el regex `[A-Za-z0-9._-]+` **solo en el write side**; el read side de `qa-resume` lo skipea.

**Fix:** importar `_validate_slug` (o duplicar el regex check) y validar `run_id`, `worker_id`, `pending_note` antes de cualquier path join.

### C3. 9 tests crashean en install limpia (mammoth/python-pptx sin guard)

**Files:** `tests/test_batch_converters.py:91-92,126`, `tests/test_batch_stager.py::test_stage_docx_converted_to_md` y `test_stage_pptx_converted_to_md`, `tests/integration/test_batch_end_to_end.py`, `src/rufino/engine/process/batch/converters.py:22,36`
**Impacto:** En cualquier máquina donde `pyproject.toml` no se haya pipx-installado (CI fresh, contributor's clone), el test suite colapsa con `ModuleNotFoundError`. No hay CI hoy que detecte esto.

**Fix opciones:**
- **(a)** mover `mammoth` y `python-pptx` a `[project.optional-dependencies] batch = [...]` y agregar `pytest.importorskip("mammoth")` / `pytest.importorskip("pptx")` a nivel módulo en los tests que las usan; documentar `pip install -e .[batch]` para devs.
- **(b)** mantener como hard deps y agregar paso de CI que instale el paquete (`pip install -e .` antes de `pytest`) + nota en `docs/getting-started.md`.

### C4. `docs/cli-reference.md` no tiene sección de `process-batch`

**File:** `docs/cli-reference.md` (entero)
**Impacto:** El README y otros docs apuntan a este archivo como referencia canonical. La feature headline de v0.1.0 no figura. Cualquier usuario que llegue por README → cli-reference no sabe que existe `process-batch`.

**Fix:** agregar sección paralela a las existentes (`rufino process`), documentando `--adapter`, `--vault`, `--workers`, `--batch-size`, `--dry-run`, exit codes (0/1/127), y el wording de `WorkerSessionExpiredError`.

### C5. Docs claiman v0.0.2 / features stubbed que ya están operativos

**Files:** `docs/cli-reference.md:17,181,182,212,241,272,318`; `docs/getting-started.md:50,163`; `docs/architecture.md:158,241`; `docs/concepts.md:25,209`; `docs/runtime.md:104`; `docs/troubleshooting.md:202,321`.
**Impacto:** Los docs activamente desinforman. `getting-started.md` instruye `rufino version → 0.0.3`; `cli-reference.md` dice "qa-poll: stubbed en v0.0.2", "process --mode full: stubbed".

**Fix:** sweep `v0.0.2` → `v0.1.0` (y `v0.0.3` donde corresponda), actualizar status statements de features que ahora operan (QA resumption, process-batch, etc.).

---

## High severity findings

| # | File:line | Issue | Impacto |
|---|---|---|---|
| H1 | `batch/qa_pending.py:107-109` | Q&A pipeline aborta en primer slug malformado en lugar de degradar per-item | Una pregunta con slug inválido tira al piso TODAS las siguientes en el mismo batch. Wrap los 3 `_validate_slug` en try/except y append a `failed`. |
| H2 | `batch/qa_pending.py:90` | `_existing_answer_filled` crashea el write phase entero si la frontmatter del file existente está corrupta | `parse_frontmatter` raisea `FrontmatterError` sin catch. Un archivo editado a mano por Obsidian-crash mata todas las escrituras restantes. Wrap en try y tratar como not-filled. |
| H3 | `batch/runner_helper.py:30-37` | `capture_output=True` sin tope → DoS si `claude` emite MB/s | OOM en orquestador antes del timeout. Documentar el bound asumido o streamear con cap. |
| H4 | `batch/qa_resume.py:124-125` | `FAKE_CLAUDE_NOTES` env var seteado **en producción** | Variable de test leakea al subprocess real. Además qa-resume no escribe `assignment.json` — el worker real no sabría qué nota procesar. Usar el helper de retry (`_write_single_note_assignment`). |
| H5 | `batch/runner.py:255-272` | Consolidator-dropped notes no se demotan a `notes_failed` | Si el consolidator devuelve un plan con menos `moves` que `all_passed`, el resumen reporta `notes_ok` incorrecto y nadie sabe qué pasó con las notas omitidas. Computar `dropped = {nv.slug for nv in all_passed} - {Path(m["to"]).stem for m in plan_obj.moves}` y demote. |
| H6 | `batch/committer.py:147-166` | Tag-index snapshot compartido entre N tag writes, rollback handler **debe** ser idempotente | Funcionalmente correcto hoy, pero un futuro refactor que elimine el snap tras primer restore crashea en el segundo. Comentar el invariante en el código. |
| H7 | `batch/committer.py:25,115,134,155,175` | `\x00` como separator en `target` no tiene test de round-trip JSON | Funciona en POSIX (NUL ilegal en filenames) y `json.dumps` lo escribe como `" "`, pero un refactor que cambie el separator a `\|` pasa todos los tests existentes y rompe rollback en producción. Agregar low-level round-trip test. |
| H8 | `tests/integration/test_batch_end_to_end.py` | E2E test mucho más estrecho que el título del commit ("mixed formats") | Sin ZIP, sin `.txt`, sin CLI (`run_batch` directo), sin negative path, `skip_consolidator=True`, `assert >= 3` permite regresión silenciosa. Agregar ≥3 variantes. |
| H9 | `docs/writing-adapters.md:172-206` | `batch_size` field undocumented en Process manifest schema | Adapter authors no saben que existe. Agregar al YAML block con las reglas de rechazo. |
| H10 | (no test exists) | Consolidator happy path no testeado | Sólo el fallback naive está cubierto. Agregar `consolidate` mode al fake_claude + runner test con `skip_consolidator=False`. |

---

## Medium severity findings

| # | File:line | Issue |
|---|---|---|
| M1 | `batch/qa_pending.py:91-95` | "answer:" detection naive: matchea substring en cualquier línea del body. Un question text que contenga "answer: blabla" se marca como answered. Mover `answer` al frontmatter o parsear estructuralmente. |
| M2 | `batch/qa_pending.py:135` | Question file writes no atómicos (`path.write_text`). SIGKILL mid-write deja archivo truncado. Usar tmp+replace como `runner.py:_ensure_gitignore`. |
| M3 | `batch/stager.py:112-119` | Stager no respeta `applies_when.matches_pattern` del manifest (extrae todo lo de extensiones soportadas). Coherente con T1-T6 pero contrato implícito — comentar o resolverlo en T7+. |
| M4 | `batch/worker_prompt.py:38-53` | Prompt no enumera `qa_triggers` del manifest. Worker depende de que `adapter_prompt_text` los repita. Mejora: agregar `qa_triggers_block` similar a `vocab_block`. |
| M5 | `batch/worker_prompt.py:92-96` | `output_schema.required` con valores mapping (`type: enum_dynamic, source: ...`) se rendea como Python dict-repr. Funciona pero queda ruidoso. Renderizar inline-yaml. |
| M6 | `batch/qa_pending.py:71-79` | Pending QA acepta non-string values silently. Si LLM emite `"pending_note": 42`, `_validate_slug(42, ...)` raisea `TypeError` no `InvalidPendingSlugError`. Agregar `isinstance(..., str)` check. |
| M7 | `batch/dispatcher.py:43` | String "Procesá las notas listadas en assignment.json siguiendo el system prompt." hardcoded en 2 lugares (dispatcher + retry). Mover a constante módulo. |
| M8 | `process/helpers/triples.py:8-22` | `extract_triples` ignora el subject `s`. Schema documentado al LLM diverge del enforced. |
| M9 | `batch/qa_resume.py:137-155` | Worker exit non-zero + augmented preexistente (stale) → falsa victoria. Limpiar `staging_dir/augmented/<slug>.md` antes de invocar. |
| M10 | `batch/committer.py:86-89` | Module docstring claima "backups never leak into the user's vault tree" — técnicamente sí están bajo `<vault>/.rufino/runs/<id>/.backups/`. Tightenear el wording. |
| M11 | `migrations/0.0.3-to-0.1.0.sh` | Migration es no-op marker. Acceptable per spec §10, pero debería `mkdir -p "${RUFINO_HOME}"` defensive. |
| M12 | `cli.py:359-363` | Handler `FileNotFoundError("claude")` checkea `getattr(e, "filename", None) == "claude"` — bien, pero sin test que pinche la rama 127. |
| M13 | 3 test files | CWD-dependent fixture paths (`Path("tests/fixtures/...")` en `test_batch_retry.py:15`, `test_batch_stager.py:78,93`, `tests/integration/test_batch_end_to_end.py:12-13`). Reproduce: `cd /tmp && pytest <file>` → FileNotFoundError. Estandarizar a `Path(__file__).parent / "fixtures" / ...`. |
| M14 | 6 test files | `FAKE_DIR` + `_make_adapter` helpers duplicados en `test_batch_runner_helper.py:13`, `test_batch_dispatcher.py:16`, `test_batch_runner.py:15`, `test_cli_process_batch.py:15`, `test_batch_retry.py:15`, `tests/integration/test_batch_end_to_end.py:12`. Mover a `conftest.py`. |
| M15 | `batch/dispatcher.py:103-110` | Cancellation behavior documentada pero no testeada. Agregar test N=2 donde w001 raisea `session_expired` y w002 está mid-flight. |
| M16 | `batch/planner.py:63,73` | `worker_id` width hardcoded `:03d`. Con 10k notas y batch_size=10 → 1000 workers → `w1000` ordena lexically antes que `w999`. `:04d` o assert sobre orden. |
| M17 | `tests/test_batch_validator.py:116-126` | "pending_only is skipped" silenciosamente — el runner no puede distinguir "worker hitó qa_trigger" vs "worker crasheó silently". Agregar invariante: cada `assignment.note` produce *algo* (augmented/pending) o va a failed. |
| M18 | `tests/test_batch_validator.py:164-180` | Test couples a `AttributeError` específico, no al policy ("Rufino bugs propagate, no se misreport como LLM errors"). Loosen. |

---

## Low / nits

- `tests/test_batch_planner.py:4` — `import pytest` sin uso, fallará `ruff F401`.
- `tests/test_batch_planner.py:38` — `assert sizes == [10, 10, 5]` acopla a left-to-right chunking. Loosen a sum + max.
- `tests/integration/test_batch_end_to_end.py:69` — `assert result.notes_ok >= 3` permite drop silencioso de 1 de 4. Pinchar `== 4` o assertear slugs.
- `tests/test_cli_process_batch.py:53` — `assert "plan" in result.output.lower()` matchea "Planet". Más estructurado.
- `batch/stager.py:30-33` — `StagedCorpus` es `@dataclass` mutable; resto del codebase usa `frozen=True`. Builder pattern o frozen final.
- `process/manifest.py:29,80` — magic number `10` (`batch_size` default) literal dos veces. `_DEFAULT_BATCH_SIZE = 10`.
- `process/manifest.py:83` — error "must be a positive integer" técnicamente correcto pero mensaje podría aclarar `>= 1`.
- `batch/stager.py:61` — `shutil.copyfileobj` sin buffer size; para PDFs grandes pasar `length=1024*1024`.
- `batch/converters.py:9` vs `batch/stager.py:23` — un módulo usa `_log`, otro `log`. Nit de consistencia.
- `batch/retry.py:62,89` — mezcla `shutil.copy2` + `shutil.move`. Pickear uno; mismo filesystem permite `Path.rename`.
- `batch/retry.py:30` — `_STDERR_TAIL_CHARS = 500` sin justificación. Comentar.
- `batch/runner.py:53-54` — `run_id` con hex suffix (mejora vs plan, evita colisión sub-second). Bien.
- `batch/consolidator.py:97-103` — argv correctamente sin `--cwd` (no existe en claude headless; usar `cwd=`). Mejora.
- `batch/runner.py:57-67` — `_concepts_head_alphabetical` documentado como "no relevance", pero prompt lo presenta como "preferí reusar". Worker va a inventar/dupliar. Comentar limitación v0.1.
- `batch/runner.py:125-126` — `dest_rel.format(**variables)` con frontmatter no-string list/dict → `KeyError` → nota a `dropped`. Mejor error message.
- `batch/committer.py:107` — `dest.parent.mkdir(parents=True)` en rollback no `rmdir_if_empty`. Cosmetic.
- (design §9) — Advisory lock por vault NO implementado. Out-of-scope pero documentar en CLAUDE.md "deferred".
- `README.md:140` — línea sobre `process-batch` muy terse. Link directo a cli-reference cuando exista.

---

## Plan adherence summary

| Task | Status | Notas |
|---|---|---|
| T1 — `batch_size` field | ✅ implementado al pie de la letra |
| T2 — `BatchError` hierarchy | ✅ implementado al pie de la letra |
| T3 — converters (docx/pptx) | ✅ + mejoras (logging warnings, hard-break) |
| T4 — stager | ✅ + **mejora crítica de seguridad** (zip-slip guard out-of-plan) |
| T5 — planner | ✅ implementado al pie de la letra |
| T6 — worker prompt builder | ✅ + mejoras (vocab_block, required_block; `run_id` ahora kwarg requerido) |
| T7 — `run_claude` + fake-claude | ✅ extendido (fake lee `assignment.json` además de env var) |
| T8 — dispatcher | ✅ desvío bueno (notes via `assignment.json` en lugar de env; sin `--cwd`) |
| T9 — validator | ✅ + mejora (narrowed exception types) |
| T10 — retry | ✅ + mejora (canonical `assignment.json` backup/restore, `error.json` con exit_code + stderr_tail) |
| T11 — qa_pending | ✅ + mejoras (slug regex, `_existing_answer_filled`, YAML frontmatter) |
| T12 — consolidator | ✅ + tightening en validación |
| T13 — committer | ✅ + hardening importante (snapshots en `run_dir/.backups/`, state-in-target rollback handlers) |
| T14 — top-level runner | ✅ + defensive `_coerce_tag_list` |
| T15 — CLI process-batch | ✅ + mejora (`FileNotFoundError` detection más robusta) |
| T16 — qa-poll resumption | ⚠️ **major deviation: missing commit step** (C1) + **path traversal** (C2) |
| T17 — version bump + migration | ✅ marker only (acceptable per spec §10, falta `mkdir -p` defensivo) |
| T18 — end-to-end integration test | ⚠️ scope mucho más estrecho que título del commit (H8) |
| T19 — docs | ⚠️ parcial (`primitives/process.md` OK; `cli-reference.md` falta entera, varios v0.0.2 stale) (C4, C5) |

---

## Cross-cutting observations

### Strengths (worth preserving)
- **Subprocess chokepoint discipline.** `grep -rn subprocess src/rufino/engine/process/batch/` → solo `runner_helper.py`. Toda invocación de `claude` pasa por `run_claude`. Argv siempre lista, no `shell=True`, no PATH ambiguity.
- **Validator narrowed exceptions** + test que codifica el policy "Rufino bugs propagate, no son LLM errors" (`test_validator_propagates_unexpected_bug`).
- **Committer rollback es serio**: test `test_rollback_after_successful_commit_reverts_all_categories` exercita moves + concept overwrites + tag indices + log entries en un único rollback. Hace al committer confiable.
- **Q&A protege user data**: `test_write_questions_skips_existing_with_filled_answer` evita clobbering de respuestas del usuario.
- **Stager security surface bien cubierta**: zip-slip, cp437, corrupt zip. Estos son los que rompen en ZIPs hechos en Windows-tooling real.
- **No `time.sleep`, no network, no claude real**. Suite de 90 tests corre en ~2 segundos.
- **`runner.py:_coerce_tag_list`** defensive guard contra `tags: "math"` scalar (LLM-shape mismatch que iteraría caracteres).
- **`run_id` con hex suffix** previene colisión sub-segundo entre runs concurrentes (mitiga parcialmente la falta de advisory lock).
- **Fake-claude fixture excelente**: 7 modes (augment, augment_bad, qa, session_expired, empty, hang, fail), documentado, determinístico.
- **Module docstring del committer** explica explícitamente por qué se eligió state-in-target sobre closures. Futuro-vos te lo va a agradecer.
- **CLI exit code mapping** distingue `BatchError` / `WorkerSessionExpiredError` / `FileNotFoundError("claude")` — Unix-y y scriptable.

### Weaknesses (recurrentes)

- **TDD parcial**: el bug C1 (qa-resume no commitea) existe porque el test que debió haberlo prevenido (`test_cli_qa_poll_resumption.py`) asserta sobre artefactos (pregunta archivada) en lugar de comportamiento observable (nota en vault canon). Mirror: el dry-run test del CLI asserta `"plan" in output.lower()`. Tests behavior-oriented son la única defensa real.
- **Path traversal mitigations inconsistentes**: `_validate_slug` cubre el write side de Q&A, pero NO el read side de `qa_resume`. Stager tiene zip-slip guard pero `qa_resume` no tiene equivalente. Recommendation: centralizar validaciones de paths en un módulo `batch/path_safety.py` y hacer que cualquier path-join de input externo pase por ahí.
- **Test path conventions inconsistentes**: 6 archivos duplican `FAKE_DIR` y `_make_adapter`; 3 archivos usan path relativos al CWD que rompen si pytest corre desde otro directorio. Mover a `conftest.py`.
- **Magic number `10`** (batch_size default) duplicado. Width `:03d` worker_id hardcoded. `_STDERR_TAIL_CHARS = 500` sin comentario. Pattern: constants módulo-level.
- **String prompts** ("Procesá las notas listadas...") duplicado entre dispatcher y retry. Inevitable cuando un prompt se va a usar en N call sites — moverlos a constante.

### Architectural fit
La arquitectura del batch package respeta las convenciones del repo (archivos chicos 200-400 líneas, error hierarchy clara, repository-pattern donde aplica, immutability con `frozen=True` mayormente). El committer integra correctamente con el `TransactionLog` primitive de runtime. La excepción es `StagedCorpus` (mutable) — minor.

La heterogeneidad entre `cli.py` (thin façade) y el engine (donde vive la lógica) se mantiene: `cli.py:process_batch_command` solo parsea flags y delega a `run_batch()`. Bien.

---

## Test coverage gaps (consolidado)

### Por componente

**Stager:**
- `_fix_zip_name` con utf-8 puro (no destrozar) y con `UnicodeDecodeError` fallback
- ZIP con paths absolutos (`/etc/passwd`) — solo cubre `../`
- ZIP con symlinks
- `.md` de 0 bytes

**Planner:**
- `batch_size=1` (cada nota un worker)

**Converters:**
- `.pptx` con shapes sin `text_frame` (tablas, imágenes)
- `.docx` vacío (sin párrafos)

**Worker prompt:**
- `output_schema.required` ausente

**Dispatcher:**
- Timeout propagation through `dispatch()` (solo cubierto en `run_claude` directo)
- Mix de N workers: 1 falla session_expired mid-flight, otros 1+ siguen
- N workers concurrentes con outcomes mixtos

**Retry:**
- `_retry_one` raisea `WorkerSessionExpiredError` (assertion que propaga, no bounce-to-failed)
- Multi-failure case con uno OK on retry 1 y otro fail all (verifica isolation per-nota)

**Q&A pending:**
- Partial-batch behavior con un pending de slug inválido (hoy aborta todo)
- `_existing_answer_filled` con frontmatter malformada (hoy crashea)

**Validator:**
- Oversize augmented file (defensive)

**Committer:**
- Crash-and-resume via `TransactionLog.load()` para batch entries
- NUL-encoded target JSON round-trip
- `dest.parent.mkdir` orphan cleanup on rollback

**Consolidator:**
- **Happy path NO testeado** (sólo fallback). Agregar `consolidate` mode a fake_claude.

**Runner:**
- Crash entre stages (DISPATCH/VALIDATE, VALIDATE/COMMIT)
- `_ensure_gitignore` con `.gitignore` pre-existente
- `_coerce_tag_list` con `tags: 42`, `tags: {a: b}`, `tags: null`
- `run.json` summary contract (schema de keys)
- Empty `concept_writes` + non-empty `tag_index_updates`

**qa-resume:**
- **Note lands in vault** (cubriría C1)
- **Path traversal con malicious YAML** (cubriría C2)
- `vault_slug=""` produce MCP server name malformado

**CLI:**
- Happy path full pipeline via `CliRunner` (no solo dry-run)
- Negative E2E (session-expired, retry exhausts → exit code 1)
- Missing claude binary (exit 127)

**E2E:**
- ZIP input
- `.txt` input
- CLI driven (no `run_batch()` directo)
- Negative path (FAKE_CLAUDE_MODE=augment_bad, asserts `notes_failed >= 1` y `failed/` markers)

### Cross-cutting
- Sin advisory lock por vault → sin test de concurrent process-batch (out-of-scope per design, pero documentar).

---

## Documentation gaps

| File | Issue | Severidad |
|---|---|---|
| `docs/cli-reference.md` | Sin sección `rufino process-batch` | Critical (C4) |
| `docs/cli-reference.md` + 6 archivos | Referencias stale a v0.0.2 | Critical (C5) |
| `docs/writing-adapters.md:172-206` | `batch_size` no documentado en manifest schema | High (H9) |
| `docs/getting-started.md` | No menciona `process-batch` como workflow primario | Medium |
| `docs/architecture.md` | No menciona batch como caso especial de Process | Low |
| `docs/troubleshooting.md` | Sin entries para batch failures (session expired, partial fail, `failed/<slug>/error.json` location, consolidator timeout) | Medium |
| `migrations/README.md` | Sin actualizar para reflejar `0.0.3-to-0.1.0.sh` (marker only) | Low |
| `README.md:140` | Línea sobre `process-batch` muy terse | Low |
| `docs/primitives/process.md` | OK — cubre batch flow bien | — |

---

## Detalle por fase (appendices)

Los reviewers individuales escribieron findings detallados con file:line refs. Se consolidaron arriba pero el detalle por fase está en los siguientes anexos:

### Appendix A — Fase 1-2: Foundation + Input pipeline (T1-T6)
Reviewer encontró 0 críticos, 1 high (nit `import pytest`), 5 medium, 7 low/nits. Highlights:
- Zip-slip guard out-of-plan (`stager.py:54-58`) + test dedicado
- Logging de mammoth warnings (`converters.py:26-28`)
- Hard-break entre párrafos pptx (`converters.py:52`)
- Worker prompt enriquecido con `vocab_block` y `required_block`

### Appendix B — Fase 3-4: Execution + Validation/Retry/Q&A (T7-T11)
Reviewer encontró 0 críticos en subprocess chokepoint, 4 high (H1-H3 de Q&A + retry race documentation), 7 medium, 4 low. Highlights:
- Subprocess discipline ironclad (argv list, no shell, no PATH injection)
- `test_unreadable_augmented_reports_os_error_not_frontmatter` cubre la disambiguation OSError-vs-FrontmatterError
- `_existing_answer_filled` con `parse_frontmatter` crashea en YAML inválido (H2)
- Dispatcher cancellation behavior documentado en docstring pero untested

### Appendix C — Fase 5-7: Consolidate + Commit + Orchestration + CLI + QA-resume + Version (T12-T17)
Reviewer encontró **3 críticos** (C1 qa-resume no commit, C2 path traversal, test que masked el bug), 4 high (FAKE_CLAUDE_NOTES leak, consolidator-dropped no demote, NUL round-trip, tag rollback fragility), 6 medium, 7 low. Highlights:
- Committer hardening genuino sobre el plan (snapshots scoped, state-in-target)
- `test_commit_does_not_leak_backups_into_vault` exemplar
- qa-resume es el slice más débil del entregable

### Appendix D — Tests + Integration + Docs (T18-T19)
Reviewer encontró **3 críticos** (C3 mammoth/pptx sin guard, C4 cli-reference sin process-batch section, C5 stale v0.0.2), 4 high (E2E narrow, batch_size undocumented, consolidator happy untested, pytest.importorskip), 6 medium, 5 low. Highlights:
- 90/90 tests green, behavior-oriented mayormente
- Suite corre en ~2s sin sleep/network/real-claude
- E2E test es 77 líneas pero el commit lo vende como "mixed formats"
- `docs/cli-reference.md` no menciona `process-batch` (la headline feature)

---

## Conclusión

**¿Está listo para v0.1.0?** Casi. Los 3 bugs críticos de código son fixes chicos (< 200 líneas combinadas) y tienen tests escribibles que los pinchan. Los 2 críticos de docs son sweep + 1 sección. Una vez aplicados, el slice queda en buen estado: subprocess chokepoint sólido, transaction log apropiadamente usado, security surface (zip-slip, slug regex) cubierta donde se aplicó, tests behavior-oriented mayormente.

**El patrón a internalizar:** los 2 bugs más serios (C1 y C2) viven en el mismo módulo (`qa_resume.py`), que tenía 1 solo test que asserta sobre artefactos secundarios. La lección: cualquier feature que toca el vault canon necesita un test que asserta sobre el estado del vault canon, no sobre side-effects intermedios. Y cualquier path-join de input externo necesita pasar por validación — aunque "el escritor ya validó".
