# Worker adapter

Shape usado por: **Ingest**, **Process**, **Output**.

## Estructura

```
~/.rufino/adapters/<primitive>/<adapter_name>/
├── manifest.yaml           # required
├── prompt.md               # required for Process; optional for Ingest emit_augmented
├── template.md             # required for Output
└── transform.py            # optional — solo si lógica determinista hace falta
```

## Manifest

Cada primitive define los campos requeridos. Ver `docs/primitives/<name>.md` para el schema exacto.

## transform.py

Opcional. Si declarado en el manifest, corre en sandbox después del LLM call (Process) o después del fetch (Ingest).

Firma única: `transform(input: dict) → dict`. Input vía stdin JSON, output vía stdout JSON.

## Validación

El framework valida cada manifest contra reglas de su primitive antes de instalar. Errores bloquean install; warnings loggean.
