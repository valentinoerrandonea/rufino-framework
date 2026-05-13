# Apple Health ingestor — notas operativas

Ingestor mensual (día 2 @ 06:00) que procesa el **mes anterior** leyendo JSONs que un **Apple Shortcut iOS** programado escribe en iCloud Drive (`RufinoHealth/`). La carpeta se sincroniza al Mac y el cron del Mac la consume.

A diferencia de los otros ingestors, **acá no hay API** — Apple no expone HealthKit fuera del iPhone. La única forma de sacar data es vía la app Shortcuts del iOS, que sí tiene acceso a HealthKit y puede escribir archivos a iCloud Drive.

## Por qué Apple Shortcut → iCloud Drive

- **HealthKit es local al iPhone**. No hay endpoint cloud para leer workouts, sleep, HR, HRV, steps.
- **Apple Shortcuts** (app nativa de iOS) puede leer HealthKit con las actions "Find Health Samples Where" y "Find All Workouts Where". Es la única vía sin jailbreak ni Apple Watch dev tooling.
- **iCloud Drive** es el puente más simple Mac↔iPhone para archivos. Una carpeta dentro de `iCloud Drive/RufinoHealth/` aparece en el Mac en `~/Library/Mobile Documents/com~apple~CloudDocs/RufinoHealth/`.

Trade-off aceptado: el Shortcut tiene que estar armado en el iPhone de Val (one-time) y dejarse corriendo en automation diaria. Si Val cambia de iPhone, hay que rearmar el Shortcut (los Shortcuts se sincronizan vía iCloud entre devices del mismo Apple ID, así que en práctica solo hay que tocarlo una vez).

## Setup en el iPhone — blueprint del Apple Shortcut

> **Objetivo**: armar 1 Automation que corra todos los días a las 23:55 y escriba 4 archivos JSON a `iCloud Drive/RufinoHealth/`.

Si nunca armaste un Shortcut programático, leé esta sección entera antes de tocar el iPhone. Los nombres de las actions cambian entre versiones de iOS — los pasos abajo asumen **iOS 17 o superior**. Si una action no aparece literal, buscala con keywords parecidas en el picker (lupa arriba a la derecha del editor de Shortcuts).

### Paso 0: Permisos previos

1. **Settings → Privacy & Security → Health → Shortcuts** → asegurate que Shortcuts tenga acceso a todas las categorías que vamos a leer (Workouts, Sleep, Heart Rate, Steps, HRV, Flights Climbed). Si todavía no le diste permiso, la primera vez que el Shortcut corra te lo va a pedir.
2. **Settings → iCloud → iCloud Drive** → ON. Verificá que "Shortcuts" esté en la lista de apps que usan iCloud Drive.
3. **Files app** → andá a iCloud Drive → tap "New Folder" → llamala **`RufinoHealth`** exactly así (case-sensitive). Sin la carpeta, las primeras corridas del Shortcut van a crear archivos sueltos en el root de iCloud Drive.

### Paso 1: crear la Automation (no un Shortcut suelto)

Un Shortcut suelto Val tendría que correrlo manualmente todos los días — no sirve. Necesitamos una **Automation** (que el sistema dispara solo en el horario).

1. Abrir **Shortcuts** (app nativa, viene preinstalada).
2. Tab inferior **Automation**.
3. Tap **`+`** (esquina superior derecha) → **New Automation**.
4. Elegir trigger: **Time of Day**.
5. Time: **11:55 PM** (23:55).
6. Repeat: **Daily**.
7. **IMPORTANT**: desmarcá "Ask Before Running" (en iOS 17+ es un toggle). Si lo dejás marcado, te pinga cada noche pidiendo confirmación y no es desatendido.
8. Tap **Next**.

Ahora estás en el editor de la automation, vacío. Vamos a armar 4 bloques (uno por categoría), cada uno termina escribiendo un JSON a iCloud Drive.

### Paso 2: bloque WORKOUTS

#### 2.1 Find All Workouts

Action: **Find Workouts Where** (o "Find All Workouts" según versión).

Filtros:
- **Start Date** is **Yesterday** (24h hacia atrás desde la corrida — capturamos workouts del día que está terminando).
- Sort by: Start Date, Order: Ascending.

> Nota: si "Yesterday" no aparece, usá "is in the last 1 day" o "Start Date is after Yesterday's midnight".

#### 2.2 Repeat con cada workout

Action: **Repeat with Each** (input = el output de "Find Workouts").

Adentro del Repeat:

- Action: **Get Details of Workout** — extraer 1 por 1 los campos:
  - Workout Type (string, ej "Running")
  - Start Date (date)
  - Duration (number, en seconds o minutes según opción)
  - Distance (number, en km — Configurá la unidad en el detail, default a metros)
  - Active Energy Burned (number, kcal)
  - Average Heart Rate (number, bpm)
  - Maximum Heart Rate (number, bpm)

- Action: **Dictionary** (crear un nuevo dict para este workout):
  ```
  workout_type     → <Workout Type>
  start            → <Start Date formatted as ISO 8601 UTC, ej "2026-05-12T07:30:00Z">
  duration_min     → <Duration in minutes, rounded int>
  distance_km      → <Distance in km, 2 decimals>
  active_calories_kcal → <Active Energy as int>
  avg_hr_bpm       → <Average Heart Rate as int>
  max_hr_bpm       → <Maximum Heart Rate as int>
  ```

  > Para format ISO 8601: action "Format Date" → Date Format: Custom → `yyyy-MM-dd'T'HH:mm:ss'Z'`, Time Zone: UTC.

- Action: **Add to Variable** "WorkoutsList" (variable que vas a inicializar antes del Repeat con un "Set Variable WorkoutsList to (empty list)" — o usá "Add to List" si tu versión soporta lists directamente).

#### 2.3 Serializar a JSON y escribir archivo

Después del Repeat:

- Action: **Get Dictionary from Input** → input = WorkoutsList (puede que necesites convertir la lista de dicts a un dict-array primero, depende de la versión).
- Action: **Get Text from Input** → Input = la lista, Format = **JSON** (en iOS 17+ está la opción "Make JSON from Dictionary/Array" directamente).
- Action: **Save File** (o "Add File to Folder" según versión):
  - **Service**: iCloud Drive.
  - **Folder**: `RufinoHealth`.
  - **File Name**: `workouts-` + Current Date formatted as `yyyy-MM-dd` (date de **ayer**, no de hoy — porque corremos a las 23:55 buscando el día que termina). Action "Format Date" → Date = "Yesterday", Format = `yyyy-MM-dd`. Resultado típico: `workouts-2026-05-12.json`.
  - **Overwrite**: ON (idempotente — si el Shortcut corre 2 veces, pisa).

### Paso 3: bloque SLEEP

Sleep es diferente: HealthKit guarda sleep como **Sleep Analysis samples** (categoría), no como workouts.

#### 3.1 Find Health Samples Where (Sleep Analysis)

Action: **Find Health Samples Where**.
- Category: **Sleep Analysis**.
- Start Date is **Yesterday** (la noche que está terminando).
- Sort by Start Date Ascending.

#### 3.2 Agregar samples → 1 record diario

Sleep viene fragmentado: típicamente 1 sample por cada cambio de stage (asleep core, deep, REM, awake). Tu objetivo es producir UN objeto del día con:

```
date          → "2026-05-12" (Yesterday formatted)
total_min     → suma de minutos en stages distintos a "In Bed" y "Awake"
in_bed_start  → min(Start Date de samples con value = "In Bed")
in_bed_end    → max(End Date de samples con value = "In Bed")
stages:
  deep_min   → suma minutos value = "Deep" (o "Asleep Deep")
  core_min   → suma minutos value = "Core" (o "Asleep Core")
  rem_min    → suma minutos value = "REM" (o "Asleep REM")
  awake_min  → suma minutos value = "Awake"
```

Implementación en Shortcuts:
- Inicializá 4 variables a 0 (`DeepMin`, `CoreMin`, `RemMin`, `AwakeMin`).
- Inicializá `InBedStart` y `InBedEnd` a null.
- Repeat with each sample:
  - Get Details of Health Sample → Value, Start Date, End Date.
  - Calcular duración del sample en minutos: action "Get Time Between Dates" → Date 1 = End, Date 2 = Start, Unit = Minutes.
  - Branch (action "If") según Value: sumá al bucket correspondiente.
  - Si Value es "In Bed" y InBedStart es null, asignalo. Updateá InBedEnd al max.
- Después del Repeat, armá el dictionary con esos valores. Convertí a JSON.

> Nota: el naming de stages cambia entre iOS 15 / 16 / 17. En iOS 17 los values son `Asleep Core`, `Asleep Deep`, `Asleep REM`, `Awake`, `In Bed`. Si tu iPhone está más viejo y solo expone `Asleep` / `In Bed` / `Awake`, suma todo lo de `Asleep` a `core_min` y dejá deep/REM en 0 — el prompt es tolerante a fields ausentes.

#### 3.3 Escribir archivo

- Filename: `sleep-` + Yesterday as `yyyy-MM-dd` + `.json`. Ej `sleep-2026-05-12.json`.
- Folder: iCloud Drive → RufinoHealth.

### Paso 4: bloque HEART RATE

#### 4.1 Find Health Samples Where

- Category: **Heart Rate**.
- Start Date is **Yesterday**.

#### 4.2 Agregar

```
date            → Yesterday yyyy-MM-dd
resting_hr_bpm  → (de Resting Heart Rate samples, ver abajo)
avg_hr_bpm      → average de Quantity de los samples de HR del día
max_hr_bpm      → max de Quantity de los samples
samples_count   → cantidad de samples
```

Para **resting_hr_bpm**: hay una categoría separada en HealthKit: **Resting Heart Rate**. Hacé un segundo "Find Health Samples Where" con Category = "Resting Heart Rate", Start Date = Yesterday → tomá el sample más reciente. Si no hay (el Watch lo calcula 1-2 veces por día con días no completos), poné el campo como null y el prompt lo va a omitir.

Para **hrv_ms**: categoría HealthKit = **Heart Rate Variability SDNN**. Idem — segundo "Find Health Samples Where", tomá el último valor del día. Output en milliseconds (Apple ya devuelve en ms).

#### 4.3 Escribir

- Filename: `heart-rate-2026-05-12.json`.

### Paso 5: bloque STEPS

#### 5.1 Find Health Samples Where

- Category: **Step Count**.
- Start Date is **Yesterday**.

#### 5.2 Agregar

```
date            → Yesterday yyyy-MM-dd
steps           → suma de Quantity de todos los samples del día
distance_km     → suma de Quantity de samples de "Walking + Running Distance" (segunda query)
flights_climbed → suma de Quantity de samples de "Flights Climbed" (tercera query)
```

> Cada métrica es una categoría separada de HealthKit, así que vas a necesitar 3 queries dentro del bloque steps. Esperable — los Shortcuts de salud típicamente tienen 8-15 actions por bloque.

#### 5.3 Escribir

- Filename: `steps-2026-05-12.json`.

### Paso 6: guardar la Automation

- Tap **Done** (esquina superior derecha del editor).
- En la lista de Automations vas a ver la nueva entrada. Tappeala para abrirla → verificá que "Run Without Asking" está ON.

### Paso 7: probar manualmente

No esperes hasta las 23:55 para ver si funciona. En el editor de la automation, tappear el **`▶`** (play) corre el shortcut on-demand. La primera vez:

1. iOS te va a pedir permisos para todas las categorías de HealthKit usadas. Allow All.
2. Va a pedir permiso para escribir a iCloud Drive. Allow.
3. Cuando termine, abrí **Files app → iCloud Drive → RufinoHealth/** — tenés que ver 4 archivos JSON con el filename de ayer.
4. Abrí cualquiera con tap largo → "Quick Look" → confirmá que el JSON es válido y los campos están.

### Paso 8: verificar sync al Mac

En el Mac, después de 5-10min:

```bash
ls -la "~/Library/Mobile Documents/com~apple~CloudDocs/RufinoHealth/"
```

Si los archivos aparecen, iCloud sincronizó. Si no, abrí Finder → iCloud Drive → la carpeta tiene que estar visible. A veces hay que abrir uno manualmente para forzar el download (íconos con la nube y flecha hacia abajo = no descargado todavía).

### Paso 9: dejar correr 2-3 días

Antes de cargar el cron, dejá la automation correr 2-3 noches. Después verificá:

```bash
ls -la "~/Library/Mobile Documents/com~apple~CloudDocs/RufinoHealth/" | wc -l
# Esperás ~12 archivos (4 por día × 3 días).
```

Si todo bien, el cron mensual del Mac (instalado abajo) va a empezar a procesar.

## Filename pattern (resumen)

| Categoría | Pattern |
|-----------|---------|
| Workouts | `workouts-YYYY-MM-DD.json` |
| Sleep | `sleep-YYYY-MM-DD.json` |
| Heart Rate | `heart-rate-YYYY-MM-DD.json` |
| Steps | `steps-YYYY-MM-DD.json` |

Date = **fecha de ayer** (porque el Shortcut corre a las 23:55 pero busca el día completo que recién termina). El ingestor del Mac agrupa todos los días del mes target.

## Schema esperado de cada archivo

Ver `docs/schema-fact-externo.md` y la sección "Schema esperado del Shortcut output" del plan agéntico. Resumen rápido:

- `workouts-*.json`: **array** de workout objects.
- `sleep-*.json`: **objeto** del día (1 sleep record).
- `heart-rate-*.json`: **objeto** del día.
- `steps-*.json`: **objeto** del día.

El wrapper del Mac (`rufino-ingest-applehealth.sh`) tolera ambos: arrays o objetos. Cualquier campo faltante se omite del fact (no se inventa).

## Frecuencia y target

- Cron en Mac: **día 2 de cada mes a las 06:00**. Procesa el **mes anterior**.
- Override manual: `RUFINO_APPLEHEALTH_FORCE_MONTH=2026-05 ~/.claude/scripts/rufino-ingest-applehealth.sh`.

## Path en el Mac

- Source (iCloud Drive synced): `~/Library/Mobile Documents/com~apple~CloudDocs/RufinoHealth/`
- Vault raw: `${RUFINO_VAULT_PATH}/applehealth/raw/<YYYY-MM>.json`
- Vault facts: `${RUFINO_VAULT_PATH}/applehealth/facts/<slug>.md`

Override del source: `RUFINO_APPLEHEALTH_DIR=/some/other/path`.

## Comportamiento cuando no hay data

El wrapper es **tolerante**:

- Si `~/Library/.../RufinoHealth/` no existe → log claro "Val tiene que armar el Shortcut" + exit 0. **No error**.
- Si la carpeta existe pero no hay archivos del mes target → log "no-op, empty month" + exit 0. **No error**.
- Si hay archivos pero todos son JSON inválido → log de los archivos rotos + exit 0 (sin invocar Claude).

Esto permite cargar el cron antes de que el Shortcut esté armado — el cron corre vacío hasta que aparezcan archivos.

## Output esperado por mes

Por mes con data (ver `claude/prompts/rufino-ingest-applehealth.md` para detalle):

- 1 fact `applehealth-summary-<YYYY-MM>` (siempre, si hay ≥1 categoría con data).
- 0–N facts `applehealth-workout-<type>-<YYYY-MM>` (1 por workout type con ≥3 sesiones).
- 0–1 fact `applehealth-sleep-trend-<YYYY-MM>` (si ≥15 noches).
- 0–1 fact `applehealth-hr-trend-<YYYY-MM>` (si ≥15 días HR).
- 0–1 fact `applehealth-steps-trend-<YYYY-MM>` (si ≥15 días steps).

## Instalar el cron

```bash
# Reemplazar __HOME__ por $HOME en el plist
sed "s|__HOME__|$HOME|g" system/launchd/com.user.rufino-ingest-applehealth.plist \
    > ~/Library/LaunchAgents/com.user.rufino-ingest-applehealth.plist

# Editar el plist: completar RUFINO_VAULT_PATH y RUFINO_DISPLAY_NAME en EnvironmentVariables

# Load
launchctl load ~/Library/LaunchAgents/com.user.rufino-ingest-applehealth.plist

# Trigger manual para test (corre el mes anterior — debería ser no-op si todavía no armaste el Shortcut)
launchctl start com.user.rufino-ingest-applehealth
tail -f ~/.claude/logs/rufino/rufino-ingest-applehealth.log
```

## Troubleshooting

- **"la carpeta no existe todavía"** en el log: la carpeta `RufinoHealth/` no se creó. Andá a Files app en el iPhone → iCloud Drive → New Folder → "RufinoHealth". O dejá que el Shortcut la cree solo en su primera corrida (la action "Save File" la crea si no existe, aunque a veces da problemas — más seguro crearla a mano).
- **Los archivos no llegan al Mac**: abrí Finder → iCloud Drive → RufinoHealth/. Si los íconos tienen la nube con flecha hacia abajo, no se descargaron todavía. Tap derecho → "Download Now". Si la carpeta aparece vacía y el iPhone tiene los archivos, esperá 10-15min — iCloud sync a veces es lento. Si después de 1h sigue vacía, restart iCloud Drive en el Mac: System Settings → Apple ID → iCloud → desactivar y reactivar iCloud Drive.
- **JSON inválido en algún día**: el script ya skipea archivos inválidos con un log. Abrí el archivo problemático con `cat` para ver qué quedó mal. Causas comunes: la serialización a Text/JSON no se aplicó (output quedó como dict text), o un campo numérico quedó como string con unidad ("45 min" en vez de `45`). Editá el bloque del Shortcut.
- **La Automation no corre a las 23:55**: en iOS 17+ las automations time-of-day **sólo corren si el iPhone está desbloqueado o si el dispositivo no está en Low Power Mode** y la Automation tiene "Run Without Asking" en ON. Si Val deja el iPhone en silencio en la mesa de luz, debería correr — pero si el iPhone está apagado o muerto, el día se pierde. No es crítico, el mes va a tener huecos pero el cron es tolerante a días faltantes (los thresholds para sleep/HR/steps trends son ≥15 días, no 30).
- **"access blocked" o crash al pedir HealthKit**: verificar Settings → Privacy & Security → Health → Shortcuts → todas las categorías necesarias en ON.

## Limitaciones

- **Sin Apple Watch**: muchas categorías van a estar en null. Sleep stages se reducen a Asleep/Awake. HRV no existe. Resting HR puede no calcularse a diario. El prompt es tolerante — emite facts con los fields disponibles.
- **iPhone apagado**: días con iPhone off → archivo de ese día no se escribe → el ingestor mensual ve menos días.
- **Multi-device**: si Val tiene iPhone + iPad y los 2 leen HealthKit, ambos pueden tirar la automation. Recomendado armar la automation **solo en el iPhone** (el iPad rara vez tiene datos de fitness reales).

## Después de armar la automation

Dejala correr 2-3 días para verificar que escribe en `~/Library/Mobile Documents/com~apple~CloudDocs/RufinoHealth/`. Después el cron mensual la consume — no hay nada más que tocar.
