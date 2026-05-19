# process-batch — Phase Breakdown

> Index of execution phases for `2026-05-18-process-batch-via-claude-orchestration.md` (19 tasks, ~4041 lines). Each phase is one session.

Source plan: [`2026-05-18-process-batch-via-claude-orchestration.md`](./2026-05-18-process-batch-via-claude-orchestration.md)

Dependencies flow top-down — each phase unblocks the next.

---

## Fase 1 — Foundation
**Tasks 1-3 · ~460 líneas · plan L15-477**

Piezas chicas e independientes entre sí.

- **T1** `batch_size` field en el manifest del worker adapter (L15)
- **T2** Scaffold `batch/` package + jerarquía de errores `BatchError` y subclases (L141)
- **T3** Format converters: docx → md (mammoth), pptx → md (python-pptx) (L240)

---

## Fase 2 — Input pipeline
**Tasks 4-6 · ~750 líneas · plan L479-1229**

Convierte el corpus crudo en batches listos para workers. Necesita Fase 1.

- **T4** Stager: unzip, fix de encoding, dispatch a converters de T3 (L479)
- **T5** Planner: batching adaptativo según `batch_size` del manifest (L780)
- **T6** Worker prompt builder (L980)

---

## Fase 3 — Worker execution core
**Tasks 7-8 · ~570 líneas · plan L1231-1800**

Corazón de la orquestación — chokepoint cargado del diseño.

- **T7** `claude-runner` helper + fixture `fake-claude` (subprocess chokepoint único) (L1231)
- **T8** Dispatcher con paralelismo acotado: `asyncio.to_thread` + `subprocess.run` (L1547)

---

## Fase 4 — Validation, retry, Q&A capture
**Tasks 9-11 · ~680 líneas · plan L1802-2481**

Consume outputs de workers. Necesita Fase 3.

- **T9** Validator de outputs de worker: schema, frontmatter, etc. (L1802)
- **T10** Lógica de retry: re-dispatch de batches fallidos (L2054)
- **T11** Recolección de Q&A pendientes → `vault/questions/` (L2310)

---

## Fase 5 — Consolidate + commit
**Tasks 12-13 · ~425 líneas · plan L2483-2908**

Cierra el run aplicando todo al vault canon de forma atómica.

- **T12** Consolidator: merge de staging dirs (L2483)
- **T13** Committer vía `TransactionLog` con rollback all-or-nothing (L2673)

---

## Fase 6 — Top-level orchestration + CLI
**Tasks 14-15 · ~490 líneas · plan L2910-3397**

Pegamento entre todas las fases anteriores y entrypoint público.

- **T14** Top-level runner: encadena STAGE → PLAN → DISPATCH → VALIDATE+RETRY → CONSOLIDATE → COMMIT (L2910)
- **T15** `rufino process-batch <zip-or-dir>` en `cli.py` (L3262)

---

## Fase 7 — Resumption, release, docs
**Tasks 16-19 · ~470 líneas · plan L3399-EOF**

Loose ends y release plumbing.

- **T16** Resumption de `qa-poll` para Q&A originadas en process-batch (L3399)
- **T17** Version bump + migration script (L3712)
- **T18** Test de integración end-to-end (L3762)
- **T19** Update docs (L3873)
