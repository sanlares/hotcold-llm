# hotcold_llm — *Hot–cold reciprocation gaps* con agentes de IA

Este repositorio replica el experimento ***Baseline*** de Ghidoni, Suetens y Yang (2026), *Hot–cold reciprocation gaps* (*Experimental Economics*), con agentes de IA (modelos de lenguaje, LLMs) en el lugar de los participantes humanos. Es parte de una tesis de licenciatura en economía: un estudio **exploratorio y descriptivo** que compara a los agentes con las mismas personas reales y con la predicción teórica.

## El experimento original, en breve

Es un juego de confianza que se repite 20 rondas, cada vez con otro participante.

| Si el primer jugador elige… | …y el segundo elige | Pago del primero | Pago del segundo |
|---|---|---|---|
| OUT | (no elige) | 25 | 25 |
| IN | LEFT (devolver la confianza) | 35 | 35 |
| IN | RIGHT (no devolverla) | 12 | 50 |

**Los agentes ocupan el lugar del segundo jugador.** Las condiciones se cruzan en un 2 × 2:
- **Hot:** el agente decide *después* de ver que el primero eligió IN.
- **Cold:** decide antes, para el caso en que el primero elija IN (método de estrategia).
- **Low / High:** se informa que el 28% o el 69% de los primeros jugadores eligen IN.

**Predicción teórica.** Un segundo jugador que solo maximiza su pago nunca devuelve la confianza: 0% (paper, Sección 2). El modelo de "sorpresa" del paper predice que se devuelve más en Hot que en Cold, sobre todo en Low.

## Diseño de la réplica

| | |
|---|---|
| Agentes | 396 por modelo, **uno por cada participante real** de *Baseline*: misma condición y misma secuencia de 20 rondas IN/OUT que vio esa persona |
| Modelos (8) | DeepSeek V4 Flash, Llama 4 Scout, Gemma 4 31B, gpt-oss-120b, Qwen3 235B, Qwen 3.8 Flash (vía DeepInfra); Claude Haiku 5.5 (Anthropic); gpt-5-nano (OpenAI). Se reportan todos |
| Personas (2) | **Demográfica:** solo los datos reales del experimento (edad, género, educación, estudiante en el Reino Unido). **Nemotron:** esos datos, más el relato de una persona de [Nemotron-Personas-UK](https://huggingface.co/datasets/nvidia/Nemotron-Personas-UK) emparejada por edad, sexo y educación |
| Pantallas | Las del archivo de Qualtrics original (`.qsf`), textuales |
| Exclusiones | Las del original: quien falla el quiz de comprensión 6 veces queda afuera |
| Análisis | [`docs/plan_de_analisis.md`](docs/plan_de_analisis.md), escrito antes de correr |

En [`docs/pilotos.md`](docs/pilotos.md) están los pilotos que llevaron a este diseño.

## Cómo reproducir

### 1. Instalar

```bash
uv sync
```

Hace falta [uv](https://docs.astral.sh/uv/) y Python 3.13.

### 2. Datos

**Paquete de replicación del paper.** El código lo espera en `../Bibliography/hot_and_cold_data/replication package/`. Usa:
- `qualtrics/Baseline-SM/Baseline-second.qsf`;
- `data/HotCold-baseline-SM.xlsx`;
- `data/hotcold_dataset.csv`.

La ruta se define en `hotcold/materials.py` (`PACKAGE`).

**Nemotron-Personas-UK** (público, sin cuenta), para la Persona de Nemotron:

```bash
mkdir -p data/external/nemotron_uk
curl -sL -o data/external/nemotron_uk/train-00000-of-00007.parquet https://huggingface.co/datasets/nvidia/Nemotron-Personas-UK/resolve/main/data/train-00000-of-00007.parquet
```

### 3. Claves

Las claves de API van en `hotcold_llm/.env`, que no se sube a git:

```
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
DEEPINFRA_API_TOKEN=...
```

### 4. Antes de gastar: tests y auditoría

```bash
uv run pytest -q
```

Son tests sin llamadas a modelos: pantallas textuales, flujo, Personas, errores, reanudación, límites y la validación del análisis.

```bash
uv run python -m hotcold.audit_inputs
```

Revisa todo lo que se les va a mandar a los 396 agentes y escribe [`docs/auditoria_inputs.md`](docs/auditoria_inputs.md).

```bash
uv run python -m hotcold.analysis --validate
```

Reproduce la Tabla 2 del paper con los datos humanos.

```bash
uv run python -m hotcold.batch --dry-run --n-per-treatment 0
```

Hace el lote completo con modelos simulados, sin costo.

### 5. Correr

Piloto: 20 agentes por modelo y Persona.

```bash
uv run python -m hotcold.batch --n-per-treatment 5 --tag piloto
```

Corrida completa: 8 modelos × 2 Personas × 396 agentes, con un tope de gasto en dólares.

```bash
uv run python -m hotcold.batch --n-per-treatment 0 --yes --max-cost 40 --tag definitiva
```

Si se corta, se retoma sin repetir agentes:

```bash
uv run python -m hotcold.batch --resume runs/<lote>
```

Para volver a correr además los errores técnicos:

```bash
uv run python -m hotcold.batch --resume runs/<lote> --retry-errors
```

`hotcold.run` corre una sola combinación de modelo y Persona (`--model`, `--persona`).

**Límites.** Por defecto, cada proveedor tiene un máximo de agentes al mismo tiempo: DeepInfra 64, Anthropic 16, OpenAI 16. Se cambian con `--limits deepinfra=64,anthropic=16`. Con esos límites, la corrida completa lleva unas 1,5–2 horas (medido en el piloto de control: entre 36 y 98 segundos por agente, según el modelo).

**Seguimiento.** Mientras corre, `runs/<lote>/status.json` muestra el avance de cada combinación.

### 6. Analizar

```bash
uv run python -m hotcold.analysis runs/<lote>
```

Escribe `runs/<lote>/analysis/` con `results.md`, las tablas en CSV y el gráfico.

## Qué produce cada corrida

Cada combinación de modelo × Persona es una carpeta en `runs/<lote>/<modelo>_<persona>/`:

| Archivo | Contenido |
|---|---|
| `config.json` | Parámetros de la corrida |
| `manifest.json` | Commit de git, hash del código y de los datos, versiones de las librerías, configuración y precios del modelo, texto del prompt |
| `personas.csv` | Cada agente: `agent_id` ↔ `real_id` (participante real), su condición y secuencia, y el texto exacto de su Persona. Para Nemotron, además, el identificador de la persona de Nemotron y la calidad del emparejamiento |
| `results.jsonl` | Una línea por agente terminado: el resultado y **la conversación completa** |
| `panel.csv` | Una fila por agente × ronda, con las mismas variables que `hotcold_dataset` (`p1trust`, `reci`, `hot`, `phigh`) y `human_reci`, lo que hizo la persona real en esa ronda |
| `subjects.csv` | Una fila por agente: intentos de quiz, cuestionario final, respuestas a la pantalla extra (`d_*`), chequeos (`chk_*`), exclusiones, reintentos, tokens y costo |
| `calls.jsonl` | Una línea por pedido al modelo: latencia, tokens, versión del modelo que respondió, reintentos y el texto de las respuestas fallidas |
| `run.log`, `summary.txt` | Avance, avisos, errores y un primer resumen |

`drop_stage` marca las salidas:
- **2:** falló el quiz 6 veces, igual que en el dataset original;
- **9:** error técnico (respuesta ilegible o cortada después de 2 reintentos, o falla del proveedor). Se reporta aparte.

## Cómo se arma cada agente

### Flujo (`hotcold/subject.py`)

Replica el *Survey Flow* del `.qsf`:
1. Bienvenida → instrucciones → instrucciones Hot o Cold.
2. Quiz, con hasta 6 intentos. Si falla, se muestra la pantalla original de "respuestas incorrectas" y las instrucciones otra vez.
3. 20 rondas. En Hot decide solo cuando el primero eligió IN. En Cold decide en todas.
4. Pantalla de pago y cuestionario final original.
5. **Pantalla agregada**, cuando ya no puede influir en ninguna decisión:
   - cómo decidió entre LEFT y RIGHT;
   - si conoce este estudio (para detectar si el modelo lo vio durante su entrenamiento).

Toda la sesión es **una sola conversación**: el agente recuerda cada pantalla, cada resultado y cada decisión propia. Las pantallas que solo piden "Next" se muestran juntas con la siguiente que pide una respuesta.

Las respuestas se piden en un formulario con opciones cerradas (*structured output*), así que no hay que interpretar texto libre. Cada casilla del formulario lleva el texto de su pregunta, como en la pantalla original.

- **Falla técnica** (respuesta vacía, cortada o fuera de las opciones): se repite el mismo pedido hasta 2 veces.
- **Respuesta rara pero válida** (por ejemplo, una edad negativa): se guarda tal cual y se marca. Es conducta del modelo, no se corrige.

### Personas (`hotcold/personas.py`, `hotcold/sources.py`)

**Demográfica.** Ejemplo: *"You are a woman aged 21. You are a student and you live in the UK. You are a bachelor's (undergraduate) student and do not have a university degree yet. Now and then you take part in paid online studies on Prolific."*

**Nemotron.** Esa misma información, más un nombre, una ciudad y cinco textos de la persona emparejada: personalidad, origen cultural, perfil profesional, hobbies y metas.
- La persona de Nemotron es siempre un estudiante: ocupación censal "no aplica" y un texto que la describe estudiando.
- Tiene el mismo sexo y una edad lo más cercana posible (373 de 396 con la misma edad).
- Tiene educación compatible.
- Cada persona de Nemotron se usa una sola vez.
- El emparejamiento se calcula una vez para los 396 con semilla fija, así que un piloto y la corrida completa le dan a cada agente la misma persona.

**Ninguna Persona usa lo que la persona real hizo o respondió en el experimento.**

### Modelos (`hotcold/llm.py`)

Todos se llaman con LangChain (`init_chat_model`), así que cualquier proveedor se agrega con una línea en `MODELS`. DeepInfra se usa con su API compatible con OpenAI.

- **Razonamiento:** apagado, o en el mínimo de cada modelo.
- **Temperatura:** la de cada proveedor por defecto.
- **Tiempo límite:** 120 s por pedido, con reintentos automáticos ante límites de uso o fallas del servidor.
- **Clave inválida o sin crédito:** la corrida se detiene en vez de marcar a todos los agentes como error.

## Desvíos respecto del experimento original

| Original | Acá |
|---|---|
| Figura de pagos (imagen) | Descripción en texto con los mismos números, que también están en las instrucciones |
| Consentimiento, Prolific ID, "¿Sos estudiante?" | Se omiten; la Persona ya es estudiante |
| Pantallas de solo "Next" | Agrupadas con la siguiente pantalla que pide respuesta |
| Cada pantalla, una por vez | El agente conserva toda la sesión en memoria y puede "releer" las instrucciones; un humano no |
| Pago real | El texto se mantiene, pero no hay incentivo real |
| Cuestionario final | Igual, más una pantalla agregada al final (cómo decidió y si conoce el estudio) |

## Replicabilidad

Los LLMs no garantizan la misma respuesta palabra por palabra: los proveedores muestrean al azar y pueden actualizar un modelo sin cambiarle el nombre. Lo que sí se puede repetir es el procedimiento:
- el código, con su commit de git;
- los datos de entrada, con sus hashes;
- el prompt y la configuración de cada modelo.

Todo eso queda en `manifest.json`. Además se archiva **cada conversación** (`results.jsonl`), y `calls.jsonl` guarda la versión del modelo que informó el proveedor en cada respuesta.

## Estructura

```
hotcold/
  materials.py       pantallas y secuencias, leídas del .qsf
  personas.py        participantes reales y Persona demográfica
  sources.py         Persona de Nemotron (y las fuentes exploratorias de los pilotos)
  subject.py         un agente recorriendo el experimento
  llm.py             modelos (LangChain), precios, errores
  run.py             una corrida: guardado incremental, reanudación, registro
  batch.py           varias corridas en paralelo, con límites por proveedor
  manifest.py        versiones de código, datos y librerías
  audit_inputs.py    auditoría de todo lo que se manda a los agentes
  analysis.py        tablas, gráfico y validación con la Tabla 2 del paper
  compare.py, twin_trust.py, make_twin_narratives.py, personas_rich.yaml   solo pilotos
tests/               tests sin llamadas a modelos
docs/                plan de análisis, pilotos, auditoría del input, ejemplos de prompts
data/derived/        textos derivados usados en los pilotos (Twin-2K-500)
```
