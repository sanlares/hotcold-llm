# Plan de análisis

Escrito antes de la corrida definitiva y fijado en el commit "pre-corrida". Lo que está acá no se cambia después de ver los resultados. Cualquier análisis que se agregue después se presenta como **exploratorio**.

## Pregunta y alcance

Estudio **exploratorio y descriptivo**. La pregunta es si agentes de IA (LLMs) que juegan el experimento *Baseline* de Ghidoni, Suetens y Yang (2026, *Experimental Economics*), en el rol de segundo jugador, reproducen:

1. la conducta de las mismas personas reales;
2. la predicción teórica;
3. la brecha *hot–cold* que encuentra el paper.

No se busca predecir a cada persona.

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
- **Exclusión:** la misma regla que el original. Quien falla el quiz 6 veces queda afuera (`drop_stage = 2`).
- **Errores técnicos:** respuestas ilegibles o cortadas que siguen fallando después de 2 reintentos (`drop_stage = 9`). Se reportan aparte y no cuentan como exclusiones del diseño.

## Medidas

**Decisión de devolver la confianza.** Se define igual que en el paper (`tab2.do`):
- en **Hot**, son las rondas en que el primer jugador eligió IN;
- en **Cold**, son todas las rondas, porque la elección se hace condicionada a IN.

**Ventanas:** ronda 1, rondas 19–20 (la principal del paper) y rondas 1–20.

### Medida principal (tabla 1)

% de decisiones de devolver, por celda (Hot-Low, Cold-Low, Hot-High, Cold-High), para cada modelo × Persona, al lado de:
- **los mismos humanos**, que ven la misma secuencia;
- **la predicción teórica: 0% en todas las celdas.** Es la mejor respuesta de un segundo jugador que solo maximiza su pago (paper, Sección 2, p. 4):
  - en Hot, RIGHT da 50 contra 35;
  - en Cold, RIGHT conviene siempre que la tasa de confianza sea mayor que 0, y en el experimento es 28% o 69%.

  El paper aclara (nota 12) que con preferencias sociales la tasa puede ser positiva incluso en Cold. Por eso 0% es la referencia "egoísta", no la única teoría.
- **las predicciones del modelo de sorpresa del paper**, en dirección:
  - Hot ≥ Cold en Low y en High;
  - la diferencia es mayor en Low que en High.

  Se marca "sí" o "no" para cada modelo × Persona.

**Diferencia Hot − Cold**, en puntos porcentuales, para Low y para High.

### Medidas secundarias

| Tabla | Qué mide |
|---|---|
| 2 | Proporción de agentes que **nunca / a veces / siempre** devuelven. Humanos: 24 / 62 / 14 |
| 3 | % por bloques de rondas (1–5, …, 16–20), Hot y Cold. En los humanos, Cold baja de 44% a 35% y Hot queda estable |
| 4 | La **Tabla 2 del paper** con los agentes: modelo lineal de probabilidad con controles (edad, mujer, educación) y errores agrupados por participante. Se usan los datos de la persona real emparejada |

### Chequeos (tabla 5)

- Exclusiones, errores técnicos y reintentos.
- Consistencia del cuestionario final con la Persona: edad, género y educación. Una respuesta rara (por ejemplo, edad "−28") **se registra como conducta del modelo y no se corrige**.
- **Estereotipos:** cuánto de las diferencias entre agentes explican edad, género y educación (R²). En los humanos es 2,9% (con todas las decisiones, como en el paper). Si en un modelo es mucho mayor, el modelo está usando la demografía de forma estereotipada.
- **Contaminación:** % que dice conocer el estudio (pregunta agregada al final).
- Versión del modelo que informó el proveedor y costo.
- **Gemma 4:** escribió los textos de Nemotron y también es uno de los modelos que juegan. Se compara Gemma con los demás modelos en ese brazo.

## Incertidumbre

- **Intervalos al 95%** por bootstrap que vuelve a sortear agentes (las 20 rondas de un agente quedan juntas). Para los humanos es la incertidumbre habitual de muestreo.
- **Advertencia: los agentes de un mismo modelo no son personas independientes.** Son muestras del mismo modelo. Por eso sus intervalos subestiman cuánto podría cambiar el resultado con otra versión del modelo u otro prompt.
- La comparación principal es **descriptiva** y **entre modelos**. No se presentan "efectos significativos" de los agentes como si fueran evidencia sobre personas.

## Análisis cualitativo

Se analizan las respuestas finales: el comentario del cuestionario original y la pantalla agregada "¿cómo decidiste?". El método (codificación a mano, con ayuda de un LLM, o ambas) se define después de la corrida y se presenta como exploratorio.

## Lo que no se hace

- No se cambia el prompt, los modelos ni las Personas después de ver los resultados definitivos.
- No se descarta ningún modelo por sus resultados.
- No se elige la fuente de Persona según cuál "se parece más" a los humanos.

## Validación del código de análisis

`uv run python -m hotcold.analysis --validate` reproduce la Tabla 2 del paper con los datos humanos:
- los 6 coeficientes de Hot;
- los N: 395, 579 y 5.815;
- los errores estándar;
- las brechas de 17,73 y 6,58 puntos del texto.

Hay un test que lo controla.
