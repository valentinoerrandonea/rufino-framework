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

Opcional. **Deferido a un plan futuro**: el manifest acepta y parsea el campo `transform_hook`, pero el framework v1 todavía no invoca el script. Si lo declarás hoy, no se ejecuta.

Cuando se implemente, la firma planificada es `transform(input: dict) → dict` corriendo en sandbox (input por stdin JSON, output por stdout JSON), después del LLM call en Process o del fetch en Ingest.

## Validación

El framework valida cada manifest contra reglas de su primitive antes de instalar. Errores bloquean install; warnings loggean.
