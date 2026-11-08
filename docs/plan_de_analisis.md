# Plan de análisis

Escrito antes de la corrida definitiva y fijado en el tag de git `pre-corrida`. Lo que está acá no se cambia después de ver los resultados. Cualquier análisis que se agregue después se presenta como **exploratorio**.

Revisado el 2026-11-07 con tres revisiones independientes del piloto de control (ver `revision_metodologica.md`).

## Pregunta y alcance

Estudio **exploratorio y descriptivo**. La pregunta es si agentes de IA (LLMs) que juegan el experimento *Baseline* de Ghidoni, Suetens y Yang (2026, *Experimental Economics*), en el rol de segundo jugador, reproducen:

1. la conducta de las mismas personas reales;
2. la predicción teórica;
3. la brecha *hot–cold* que encuentra el paper.

No se busca predecir a cada persona.

**Qué se podrá afirmar:**
- porcentajes descriptivos por modelo, válidos para *este* protocolo y *estas* versiones de los modelos;
- cuánto difieren los modelos entre sí;
- cuánto cambia la conducta según la Persona;
- qué modelos se comportan como un jugador egoísta (0%).

**Qué no se afirmará:**
- nada sobre "los LLMs" en general (son 8 modelos elegidos por costo, no al azar);
- que los agentes sienten sorpresa o aprenden como los humanos;
- que un modelo memorizó o no el paper a partir de lo que responde su Persona.

## Diseño

- **Agentes:** 396, uno por cada participante real que terminó *Baseline*. Cada agente recibe la misma condición (Hot/Cold × Low/High) y la misma secuencia de 20 rondas IN/OUT que vio esa persona.
- **Modelos:** 8; se reportan todos.

  | Proveedor | Modelos |
  |---|---|
  | DeepInfra | DeepSeek V4 Flash, Llama 4 Scout, Gemma 4 31B, gpt-oss-120b, Qwen3 235B, Qwen 3.8 Flash |
  | Anthropic | Claude Haiku 5.5 |
  | OpenAI | gpt-5-nano |

- **Personas:** dos por modelo.
  - **Demográfica:** solo edad, género, educación y ser estudiante en el Reino Unido. Son los datos reales registrados en el experimento; no se inventa nada.
  - **Nemotron:** la demografía real, más el relato de una persona de Nemotron-Personas-UK (NVIDIA) emparejada por edad, sexo y educación. Siempre es un estudiante y cada relato se usa una sola vez.
- **Pantallas:** las del `.qsf` original, textuales. Los desvíos están en el README.
- **Razonamiento:** apagado o en el mínimo de cada modelo. No se pide justificar durante el juego.
- **Qué agentes se analizan:** solo los que **completaron** todas las pantallas originales, incluido el cuestionario. Es la regla del paper (`finished == 1`).
- **Exclusión del diseño:** quien falla el quiz 6 veces queda afuera (`drop_stage = 2`), igual que en el original.
- **Errores técnicos** (`drop_stage = 9`): respuestas ilegibles o cortadas después de 2 reintentos, o fallas del proveedor.
  - Después de la corrida se usa `--resume --retry-errors` **una vez** para volver a correr a esos agentes.
  - Se reporta cuántos se volvieron a correr y cuántos quedaron con error. No cuentan como exclusiones del diseño.

## Medidas

**Decisión de devolver la confianza.** Se define igual que en el paper (`tab2.do`):
- en **Hot**, son las rondas en que el primer jugador eligió IN;
- en **Cold**, son todas las rondas, porque la elección se hace condicionada a IN.

**Ventanas:**
- **rondas 19–20: la principal**, como en el paper;
- ronda 1 y rondas 1–20: complementarias.

### Comparación con humanos

Hay dos referencias humanas:
- **"humans (all)":** los 396 participantes.
- **"paired humans":** para cada modelo × Persona, **solo los participantes emparejados con los agentes que completaron**, en las mismas rondas (columna `human_reci`). **Es la comparación principal.** Cuando un modelo pierde agentes en el quiz, compararlo con los 396 sería comparar grupos distintos.

### Medida principal (tablas 1 y 2)

**Tabla 1.** % de decisiones de devolver por celda (Hot-Low, Cold-Low, Hot-High, Cold-High), para cada modelo × Persona y sus humanos emparejados, con intervalo del 95%.

**Predicción teórica: 0% en todas las celdas.** Es la mejor respuesta de un segundo jugador que solo maximiza su pago (paper, Sección 2, p. 4):
- en Hot, RIGHT da 50 contra 35;
- en Cold, RIGHT conviene siempre que la tasa de confianza sea mayor que 0, y en el experimento es 28% o 69%.

El paper aclara (nota 12) que con preferencias sociales la tasa puede ser positiva incluso en Cold. Por eso 0% es la referencia "egoísta", no la única teoría.

**Tabla 2.** La brecha **Hot − Cold en las rondas 19–20**, para Low y para High, con intervalos del 95%, y la diferencia entre ambas brechas. El veredicto sobre el resultado principal del paper (Hot > Cold en Low) es uno de:

| Veredicto | Cuándo |
|---|---|
| **en la dirección del paper** | el intervalo de la brecha en Low está todo por encima de 0 |
| **en contra** | está todo por debajo de 0 |
| **no se puede decir** | incluye el 0 |
| **sin variación** | el modelo elige siempre lo mismo |
| **celda chica: no se interpreta** | alguna celda tiene menos de 30 agentes que completaron. La celda se muestra igual |

La segunda predicción del paper (brecha mayor en Low que en High) se muestra con su intervalo, sin veredicto aparte: el paper mismo la encuentra imprecisa.

### Medidas secundarias

| Tabla | Qué mide |
|---|---|
| 3 | Proporción de agentes que **nunca / a veces / siempre** devuelven. Humanos: 24 / 62 / 14 |
| 4 | % por bloques de rondas (1–5, …, 16–20), Hot y Cold. En los humanos, Cold baja de 44% a 35% y Hot queda estable |
| 5 | La **Tabla 2 del paper** con los agentes: modelo lineal de probabilidad con controles (edad, mujer, educación) y errores agrupados por participante, con los datos de la persona real emparejada. Si hay menos de 30 agentes o no hay variación, se muestra "—" |
| 6 | **Demográfica contra Nemotron** para cada modelo, solo con los participantes que completaron en las dos |

**Cómo leer las tablas 3 y 4.** Los agentes conservan toda la sesión como una conversación y tienden a repetir su primera decisión. Si un promedio se parece al humano, la tabla 3 dice si es porque los agentes varían como los humanos o porque se mezclan agentes que siempre devuelven con agentes que nunca devuelven. Una brecha en las rondas 19–20 de los agentes **no se interpreta como aprendizaje**.

### Exclusiones y chequeos (tablas 7 y 8)

**Exclusiones por celda**, para cada modelo × Persona. Referencia humana: en el original, 3 de 534 participantes fallaron el quiz.

Un modelo con muchas exclusiones (en el piloto, gpt-5-nano) se presenta **aparte**: la exclusión es un resultado en sí mismo y los agentes que quedan son una muestra seleccionada. En el segundo piloto de control, gpt-5-nano no aprobó el quiz en ningún agente de Hot (`revision_metodologica.md`): se espera que no tenga brecha Hot − Cold interpretable, y se reportan su Cold y su exclusión.

**Chequeos:**
- **Consistencia del cuestionario final con la Persona:** edad, género y educación. Una respuesta rara (por ejemplo, edad "−28") **se registra como conducta del modelo y no se corrige**.
- **Estereotipos:** cuánto de las diferencias entre agentes explican edad, género y educación (R²). En los humanos es 2,9%, con todas las decisiones, como en el paper. Si en un modelo es mucho mayor, el modelo está usando la demografía de forma estereotipada.
- **"Dice conocer un estudio parecido":** lo responde la Persona, así que se lee como "reconoce el tipo de juego". Un "No" no descarta nada.
- **Si el modelo conoce el paper:** se pregunta aparte, fuera del personaje y en una conversación nueva (`hotcold.probe_knowledge`), una vez por modelo. Un resumen correcto de los resultados mostraría que lo conoce; un "no" no prueba lo contrario.
- **Versión del modelo y costo:** la versión que informó el proveedor, y el costo de la corrida.
- **Gemma 4:** escribió los textos de Nemotron y también es uno de los modelos que juegan. Se lo menciona si queda como caso atípico, sin atribuirle la causa.

### Sensibilidad (tabla 9)

La tabla 2 se repite para Nemotron **sin los 8 participantes de género "Other" o que prefirieron no decirlo**. Nemotron solo tiene hombres y mujeres, así que su relato usa she/he, y eso contradice lo que dice la Persona.

## Incertidumbre

- **Intervalos al 95%** por bootstrap que vuelve a sortear agentes (las rondas de un agente quedan juntas).
- **Para los humanos**, es la incertidumbre habitual de muestreo.
- **Para los agentes de un modelo**, mide solo el azar con *este* prompt y *esta* versión del modelo. Los agentes de un mismo modelo no son personas independientes. La incertidumbre por cómo se arma el prompt es mucho mayor: en los pilotos, el mismo modelo pasó de 0% a 81% cambiando solo la Persona (`pilotos.md`).
- **La unidad para generalizar es el modelo**, no el agente. La comparación principal es **descriptiva** y **entre modelos**. No se presentan "efectos significativos" de los agentes como si fueran evidencia sobre personas.

## Análisis cualitativo

Se analizan las respuestas finales:
- el comentario del cuestionario original;
- la pantalla agregada: "¿cómo decidiste entre LEFT y RIGHT?".

La pantalla agregada es una **justificación escrita después de decidir**, no la causa de la decisión. El método (codificación a mano, con ayuda de un LLM, o ambas) se define después de la corrida y se presenta como exploratorio. Si se usa un LLM para codificar, se elige uno de otra familia que los 8 que juegan y se valida a mano una parte.

## Lo que no se hace

- No se cambia el prompt, los modelos ni las Personas después de ver los resultados definitivos.
- No se descarta ningún modelo por sus resultados.
- No se elige la fuente de Persona según cuál "se parece más" a los humanos.

## Validación del código de análisis

`uv run python -m hotcold.analysis --validate` reproduce la Tabla 2 del paper con los datos humanos:
- los 6 coeficientes de Hot y sus errores estándar;
- los N: 395, 579 y 5.815;
- las brechas de 17,73 y 6,58 puntos del texto.

Hay un test que lo controla.
