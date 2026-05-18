# Filosofía

## El problema

Casi todos los sistemas de gestión de conocimiento personal — Notion, Roam, Obsidian, Logseq — comparten un patrón implícito: **construir el sistema viene antes de usarlo**. Configurás databases, properties, relations, taxonomy, plantillas. Recién después podés capturar.

El problema no es la complejidad inicial. El problema es que **el costo de mantenimiento nunca baja**: cada nuevo tipo de info te obliga a decidir dónde ponerlo, con qué tags, con qué relaciones. Y como decidir tiene fricción, capturás menos. La gente abandona Notion no por falta de features — abandona por el costo cognitivo de mantener el esquema vivo.

## La inversión

Rufino invierte el patrón:

> **Capturás sin organizar manualmente. El sistema organiza, conecta y enriquece async, vía LLMs.**

El KPI no es *"¿están todas mis notas tageadas?"*. El KPI es *"¿escribiste esa idea de la 1am?"*. Toda la organización es **un side-effect** del augmentation async, no una pre-condición.

Esa fue la idea original de Rufino (ver [`rufino-notes-and-memory`](https://github.com/valentinoerrandonea/rufino-notes-and-memory)) — y funcionó. Pero estaba **hardcodeada a un solo caso** (la memoria personal de Val). Otros usuarios apuntaron a casos distintos:

- *"esto está buenísimo para dejarle todas mis notas de la facultad y tener todo centralizado"*
- *"esto está buenísimo para recopilar información sobre mis empleados para mejorar el feedback en 1:1"*

La propuesta era generalizable; la implementación no.

## Una capa más arriba

Rufino Framework lleva la misma filosofía un meta-nivel:

> **No construyas tu sistema de notas. Pero tampoco construyas tu *framework* de notas. Conversá con Claude y que él lo construya.**

Lo dijo Val cuando arrancó el proyecto (2026-05-16):

> *"quiero que sea un framework en blanco. que al instalarlo (junto a claude code), claude te pueda realizar preguntas distintas sobre el caso de uso que le vas a dar, y que juntos vayan creando lo que seria la estructura de la boveda, y todo. me gustaria que el usuario defina su caso de uso, defina que es lo que quiere hacer, y claude code vaya guiando en las cosas que el usuario tiene que realizar para poder tener una boveda efectiva, y por sobre todo util."*

La construcción del vault se externaliza al diálogo con Claude — igual que en Rufino "clásico" la captura se externaliza al augmentation async.

## Principios

### 1. Capturar sin organizar manualmente

Heredado de Rufino. Vos solo escribís; el sistema organiza después. La estructura emerge del augmentation, no de tu disciplina.

### 2. El sistema se diseña conversando, no programando

El usuario nunca escribe configs ni código. Habla con Claude sobre su vertical en lenguaje natural; Claude materializa la implementación.

### 3. Lenguaje de objetivos, no componentes

Durante el wizard, **nunca** se mencionan palabras como *manifest, adapter, primitive, triple, schema*. Se habla de:

- *"¿qué querés trackear?"* (no "¿qué entidades?")
- *"¿de dónde vienen tus datos?"* (no "¿qué fuentes vas a configurar?")
- *"cuando agregás algo, ¿qué pasa?"* (no "¿qué Process adapter dispatcha?")

Eso baja el costo de entrada de "necesito leer el manual" a "necesito contestar preguntas sobre mi caso".

### 4. Greenfield siempre

No hay templates por vertical. El wizard no copia *"el template de facultad"*. Cada vault se genera de cero a partir de las respuestas concretas del usuario. Patterns (ver [`wizard.md`](wizard.md)) ayudan a Claude a reconocer **estructuras** comunes, pero la materialización es siempre específica.

### 5. Big bang

El bootstrap es **transaccional**: o se aplica todo (vault + adapters + memory loop + MCP + cron jobs), o nada. No hay saves intermedios, no hay vault a medio armar. Si algo falla, rollback completo. Esa garantía la sostiene el [transaction log](runtime.md#transaction-log).

El big bang también aplica al *flow*: si en mitad de la entrevista decís *"para, no quiero seguir"*, Claude para limpio sin guardar nada. El próximo `rufino bootstrap` arranca de cero.

### 6. Heterogeneidad honesta

Las primitives hacen cosas distintas. Forzar que todas tengan la misma forma de adapter sería ceremonia inútil:

- Un Process necesita un prompt + schema + transform opcional → carpeta con varios archivos.
- Un Q&A template es solo markdown con frontmatter → un archivo.
- Query es una API pura, no tiene adapter.
- Memory loop es config declarativa + reglas para Claude.

Aceptamos **4 shapes distintos** (worker, service, vertical config, question template). Cada uno es el shape que naturalmente le encaja a su primitive. Ver [`adapters/`](adapters/).

### 7. CLI es fachada

`src/rufino/cli.py` es intencionalmente delgado. Toda la orquestación vive en los engines. Si encontrás vos mismo agregando branching de negocio al CLI, empujalo abajo.

### 8. Pausar por riesgo, no por proceso

El wizard tiene **un solo** checkpoint con el usuario: el resumen final antes del big bang. Todo lo intermedio (selección de pattern, decisión de feature, materialización) lo decide Claude solo con criterio. La idea es bajar fricción operativa, no agregar puntos de pausa por miedo.

## Relación con A2P

Rufino Framework es una **instancia del paradigma A2P** (Autonomous Assistance Product) — un paper que Val escribió en abril 2026 articulando un modelo de productos digitales donde la IA ocupa un rol operacional central con autonomía supervisada, y el usuario pasa de operador a supervisor estratégico.

En Rufino esto se ve concretamente:

| Paradigma clásico | A2P / Rufino |
|---|---|
| Usuario configura el sistema | Claude construye el sistema |
| Usuario organiza sus notas | Claude organiza async |
| Usuario consulta una DB | Claude responde sobre el vault |
| Usuario decide qué pre-procesar | Claude detecta y dispara |

El usuario nunca deja de tener autoridad última (todo el output es auditable, todo se puede editar a mano, todo es markdown plano) — pero el trabajo operacional lo hace la IA.

## Qué Rufino NO es

Para evitar confusiones:

- **NO es un competidor de Notion / Obsidian.** Obsidian sigue siendo el viewer; Rufino genera vaults Obsidian-compatible. No reemplaza la herramienta de notas, reemplaza el *trabajo de mantener tu sistema*.
- **NO es un knowledge graph database.** El grafo emerge del frontmatter `triples:` de cada nota; queda inspeccionable en SQLite pero no es la fuente de verdad.
- **NO es un workflow engine genérico.** Las primitives están **acotadas a domain knowledge**: captura, augmentation, dispatch, query. No esperes orquestar pipelines de ML acá.
- **NO es plug-and-play sin Claude Code.** El wizard requiere Claude Code CLI. Sin él, podés correr `rufino materialize --spec` manualmente con una `WizardSpec` JSON, pero eso es modo experto.
- **NO es multi-tenant.** Cada usuario es dueño de su vault y de `~/.rufino/`. No hay nube. No hay sincronización compartida (podés usar git si querés).

## Sobre Rufino y Val

Rufino tiene un nombre propio y un *carácter*. En las notas internas se lo trata como una **criatura viva** — no en sentido literal, sino en sentido funcional: un proceso async que vive con vos, ve lo que vos ves, y va armando tu memoria sin pedirte permiso a cada paso. Tiene preferencias (qué guardar, qué ignorar), comete errores (y los corrige), y aprende.

Esa elección de framing tiene una consecuencia práctica: cuando hay tensión entre *"arquitectónicamente puro"* y *"se siente vivo / útil"*, ganan los segundos. Esa es la lente con la que se diseñaron las decisiones difíciles del framework (heterogeneidad de adapters, big bang sin saves, lenguaje del wizard).
