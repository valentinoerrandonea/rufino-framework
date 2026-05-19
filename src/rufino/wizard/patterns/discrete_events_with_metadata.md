# Pattern: discrete_events_with_metadata

## Trigger language (señales del user)
- "trackear X"
- "registrar cada vez que"
- "saber cuánto/dónde/cuándo"
- "histórico de"
- mención de números + fechas

## Entity types típicos
- evento, transacción, sesión, log

## Combinación de primitives
- Ingest con `output_mode: emit_facts` (API/CSV/manual)
- Process opcional (categorización)
- Output digest periódico

## Casos
- Finanzas (transacciones)
- Eventos calendar
- Plays de Spotify
- Commits de GitHub
