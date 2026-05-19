# Casos de uso

Verticales donde Rufino Framework aplica. Cada uno con qué adapters se materializan, qué patterns se combinan, y qué experiencia tiene el usuario.

> Los ejemplos son **descriptivos**, no exhaustivos. El wizard te genera lo que vos necesitás según tu entrevista — no copia un template.

---

## 1. Notas de facultad

**Perfil del usuario:** estudiante en una carrera con varias materias en paralelo. Toma notas en clase (iPad), recibe PDFs del profesor, lee papers para TPs, tiene fechas de examen.

**Problema:** todo disperso. PDFs en Drive, notas en cuadernos digitales, papers en Zotero, screenshots en WhatsApp. Imposible cruzar.

### Patterns combinados

- `long_documents_extraction` (PDFs de clase, papers)
- `person_centric_tracking` (profesores)

### Adapters generados

| Adapter | Qué hace |
|---|---|
| `ingest/drive-pdfs` | Pulla PDFs nuevos de una carpeta de Drive al `inbox/` |
| `ingest/calendar` | Trae eventos del calendario marcados con tag "1:1" o nombre de materia, para detectar fechas de examen |
| `process/apunte-clase` | Augmenta apuntes con frontmatter (materia, profesor, fecha, topics), wikilinks a apuntes previos, triples (`tema-de`, `expuesto-por`) |
| `process/paper` | Augmenta papers con metadata bibliográfica, conexiones a apuntes que los citan |
| `output/digest-semanal` | Resumen los viernes: qué clases viste esta semana, qué topics nuevos aparecieron, qué TPs vencen pronto |
| `output/aviso-examen` | Notifica 24h antes de cada examen con lista de apuntes y papers relevantes |
| `output/bio-mensual` | "Tu bio académica del mes": qué materias avanzaste, qué temas estudiaste |
| `memory_loop/facultad` | Reglas: cuando hables de un profesor o materia nueva en Claude Code, sugerí guardar como contacto/materia |

### Vault resultante

```
~/facultad/
├── perfil.md
├── README.md
├── inbox/
├── apuntes/
│   ├── ml-i/
│   ├── stats-ii/
│   └── ...
├── papers/
├── profesores/
├── materias/
├── conceptos/        # promoción automática cuando aparece ≥2 veces
├── examenes/
├── tps/
└── _meta/
```

### Experiencia

- Tirás un PDF a `inbox/` → en minutos aparece en `apuntes/<materia>/<fecha>-<slug>.md` con todo el frontmatter armado, links a apuntes previos sobre el mismo tema, y entry en `profesores/` si era profe nuevo.
- Si el LLM no está seguro de qué materia es (porque las menciona ambiguas), te crea una Q&A en `questions/` y para. Vos editás `answer:` y el processing se reanuda.
- El viernes a la noche recibís un email con el digest de la semana.
- Si estás trabajando en otro proyecto y querés saber qué decía el profe sobre X, le preguntás a Claude desde ese proyecto (vía MCP `ask-rufino-<slug>` — un entry por vault en `~/.claude.json`).

---

## 2. 1:1 con empleados

**Perfil del usuario:** Engineering Manager con 6 reportes directos. Cada uno tiene 1:1 quincenal. Hace tracking informal en Notion pero se pierde — no recuerda qué hablaron la vez pasada, no sabe si dio el feedback que se prometió dar.

**Problema:** la memoria entre 1:1s consecutivos. Y la dificultad de hacer una bio coherente de cada persona para el career growth conversation cuatrimestral.

### Patterns combinados

- `person_centric_tracking` (core)
- `decision_log_with_rationale` (feedback formal, decisiones de career)

### Adapters generados

| Adapter | Qué hace |
|---|---|
| `ingest/calendar` | Detecta eventos `1:1` próximos en tu calendario |
| `process/1on1-note` | Augmenta notas crudas de un 1:1 con frontmatter (persona, fecha, topics), wikilinks a 1:1 previos con la misma persona, triples (`feedback-a`, `okr-de`, `bloqueante`) |
| `output/meeting-prep` | 24h antes de cada 1:1 te genera y manda por email un prep doc con: notas de los últimos 3 meses con esa persona, feedback pendiente, OKRs activos, bloqueantes mencionados que no se cerraron |
| `output/bio-mensual` | Por cada persona: resumen del mes (qué decisiones se tomaron, qué creció, qué quedó pendiente) |
| `memory_loop/team-1on1` | Reglas: cuando mencionás a una persona del equipo en Claude Code, sugerí guardar al vault como nota de 1:1 informal o feedback |

### Vault resultante

```
~/management/
├── perfil.md
├── personas/
│   ├── ana.md
│   ├── beto.md
│   └── ...
├── 1on1/
│   ├── ana/
│   │   ├── 2026-05-03-1on1.md
│   │   └── ...
│   └── beto/
├── feedback/
├── decisiones/
└── _meta/
```

### Experiencia

- Antes del 1:1 con Ana mañana, recibís email con prep: *"Última vez hablaron de X. Le diste feedback Y que no le devolviste seguimiento. Su OKR del Q es Z, último update fue hace 3 semanas."*
- Después del 1:1 escribís tres bullets en una nota cruda; al día siguiente la nota augmentada queda con frontmatter, links a 1:1 previos, y triples actualizados.
- Fin de mes te llega la bio: *"Ana este mes cerró el proyecto X, recibió feedback sobre comunicación asíncrona, expresó interés en mover a Sr."*

---

## 3. Knowledge graph de proyectos (decisiones técnicas)

**Perfil del usuario:** Tech Lead que toma decisiones arquitectónicas en varios proyectos. Quiere capturar el *por qué* detrás de cada decisión (no solo qué se hizo) para no repetir conversaciones, y poder cruzar decisiones entre proyectos.

**Problema:** los ADRs formales son fricción alta — nadie los escribe. Las decisiones quedan en Slack o en cabezas. Cuando un proyecto nuevo enfrenta el mismo dilema, se vuelve a debatir desde cero.

### Patterns combinados

- `decision_log_with_rationale` (core)
- `knowledge_graph_projects` (cross-project)

### Adapters generados

| Adapter | Qué hace |
|---|---|
| `process/decision` | Toma una nota cruda con la decisión y la augmenta con triples (`supersedes`, `contradice`, `aplica-a`, `motivado-por`) |
| `output/decision-search` | Cuando se hace una pregunta tipo "ya pensamos esto?", devuelve decisiones previas relacionadas vía embeddings + grafo |
| `output/lint-orphans` | Reporte mensual de decisiones sin `supersedes` ni `superseded-by` que se contradicen entre sí (alerta de inconsistencia) |
| `memory_loop/decisiones` | Reglas: cuando detectás que estás cerrando un debate técnico en una conversación, sugerí guardar como decisión |

### Vault resultante

```
~/decisiones/
├── perfil.md
├── decisiones/
│   ├── 2026-05-17-elegir-pipx-sobre-pip.md
│   ├── 2026-05-12-postgres-sobre-mongo.md
│   └── ...
├── proyectos/
│   ├── rufino-framework.md
│   ├── alfio.md
│   └── ...
├── tags/
└── _meta/
```

Cada decisión queda con triples como:

```yaml
triples:
  - { r: aplica-a, o: rufino-framework }
  - { r: motivado-por, o: pep-668 }
  - { r: supersedes, o: 2025-12-01-elegir-pip-con-user-flag }
```

### Experiencia

- En cualquier proyecto, le preguntás a Claude: *"¿hay alguna decisión previa sobre packaging de Python?"* → MCP responde con las decisiones registradas.
- Si una decisión nueva contradice otra previa, el wizard te avisa: *"Esto contradice la decisión de 2025-12-01. ¿Es una superseción o una contradicción?"*
- Mensualmente recibís el lint de decisiones huérfanas.

---

## 4. Coaching financiero (sincronía con oiKO)

**Perfil del usuario:** alguien que ya usa una app de tracking de gastos (oiKO, Splitwise, etc.) y quiere convertir esos datos en *insight*, no solo *log*.

**Problema:** las apps muestran categorías. No te dicen *"este mes gastaste 30% más en delivery, ¿pasó algo?"*. Y vos no recordás qué pasó.

### Patterns combinados

- `discrete_events_with_metadata` (transacciones)
- `temporal_self_observation` (cómo viene el mes/año)
- `decision_log_with_rationale` (decisiones financieras + contexto)

### Adapters generados

| Adapter | Qué hace |
|---|---|
| `ingest/belo` | Pulla transacciones de Belo cada 30 min, emite facts (`emit_fact`) |
| `ingest/splitwise` | Pulla gastos compartidos de Splitwise |
| `process/transaccion` | Augmenta transacciones con categorización fina, contraparte resuelta a persona, triple `parte-de` si es proyecto |
| `process/contexto-narrativo` | Toma notas crudas de contexto ("compré X porque…") y las linkea a transacciones del día |
| `output/digest-semanal` | Resumen del gasto + patrones inusuales |
| `output/bio-mensual` | "Tu mes financiero": top categorías, comparativo vs mes anterior, qué decisiones tomaste |
| `output/year-review` | Retrospectiva anual el 30 de diciembre |

### Vault resultante

```
~/finanzas/
├── perfil.md
├── transacciones/
│   ├── 2026-05/
│   └── ...
├── contraparte/        # personas / comercios
├── proyectos/          # gasto agrupado por proyecto (viaje, mudanza, etc.)
├── notas/              # contexto narrativo
├── decisiones/         # "vendí USDC para invertir en X"
└── _meta/
```

### Experiencia

- Las transacciones entran solas cada 30 min.
- Cuando hacés una compra grande dejás una nota corta en `inbox/`; el adapter la linkea a la transacción del día.
- Fin de semana llega el digest con los patrones del mes.
- A fin de año, el year-review te muestra: *"En 2026 gastaste X. Tu top categoría fue Y. Tus 3 viajes (París, Berlín, Buenos Aires) representaron Z%. Decidiste sí a comprar GPU 5090 y no a alquilar oficina."*

---

## 5. Memoria personal (el caso original)

**Perfil del usuario:** alguien con vida densa atravesada por muchos hilos en paralelo — trabajo, proyectos propios, familia, viajes — que quiere una memoria coherente sin volverse el archivero de sí mismo.

**Problema:** los detalles se pierden. Querés saber *"¿qué le dije a Guille sobre el viaje a Europa en marzo?"* y la respuesta vive en 3 chats, 2 fotos y un mail. La capacidad de cruzar es nula.

### Patterns combinados

- `temporal_self_observation` (cómo viene el año)
- `knowledge_graph_projects` (proyectos personales)
- `person_centric_tracking` (gente importante)
- `discrete_events_with_metadata` (eventos del calendario, transacciones)

### Adapters generados

(El set más grande — múltiples Ingest, varios Process por tipo de nota, varios Outputs.)

| Adapter | Qué hace |
|---|---|
| `ingest/whatsapp` | Backup periódico de chats clave |
| `ingest/calendar` | Eventos del calendario |
| `ingest/browsing` | Chrome history filtrado por dominios de interés |
| `ingest/spotify` | Top channels mensuales |
| `ingest/github` | Commits propios |
| `ingest/youtube` | Watch history |
| `ingest/screentime` | Apps usadas |
| `process/*` | Augmenta cada tipo |
| `output/digest-semanal` | Resumen del viernes |
| `output/bio-mensual` | Bio del mes |
| `output/year-review` | Retrospectiva del 30 de diciembre |
| `memory_loop/personal` | El memory loop más rico — reglas + skill `/remember-<slug>` + hooks (opt-in) |

### Vault resultante

(Equivalente al vault personal de Val — `~/Files/vaultlentino/`.)

```
~/vault/
├── perfil.md
├── preferencias.md
├── proyectos/
├── personas/
├── sesiones/
├── rufino/               # notas crudas augmentadas
├── decisiones/
├── aprendizajes/
├── feedback/
└── _meta/
```

### Experiencia

Esto es el caso original de `rufino-notes-and-memory` — el flow está probado. Lo que el framework agrega: lo materializa el wizard en vez de requerir clonar el repo y correr setup manual.

---

## Combinaciones híbridas

Los patterns son combinables. Algunos verticales reales no encajan en una sola categoría:

| Vertical | Combinación |
|---|---|
| **Producto de startup** | `decision_log_with_rationale` + `knowledge_graph_projects` + `person_centric_tracking` (stakeholders) |
| **Investigación académica** | `long_documents_extraction` + `knowledge_graph_projects` + `decision_log_with_rationale` (metodología) |
| **Salud personal** | `discrete_events_with_metadata` (sleep, ejercicio, peso) + `temporal_self_observation` |
| **Reading log** | `long_documents_extraction` + `temporal_self_observation` + `knowledge_graph_projects` |
| **Personal CRM** | `person_centric_tracking` + `discrete_events_with_metadata` (interactions) |

El wizard te guía hacia la combinación adecuada — vos solo describís el problema en lenguaje natural.

## Si tu vertical no encaja

Si después de 2-3 preguntas Claude no matchea un pattern claro, **construye desde primitives básicas** — modo fallback. Te genera un set mínimo (memory loop + 1-2 Process + Output digest) y deja la puerta abierta a que vayas agregando adapters después con `/init-rufino` o ediciones manuales.

La filosofía del framework no es *"tu vertical tiene que entrar"* — es *"si entra, te ahorrás la fricción; si no, igual te dejo una base utilizable"*.
