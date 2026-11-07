# Revisión independiente (2026-11-07)

Después del piloto de control (8 modelos × 2 Personas × 20 agentes), **tres revisores independientes** revisaron el proyecto: agentes de IA (Claude) sin acceso a la conversación de trabajo ni a las notas del autor. Cada uno leyó solo:
- el repositorio;
- el paper;
- el paquete de replicación;
- las conversaciones del piloto.

Ninguno podía modificar archivos ni hacer llamadas pagas.

| Revisor | Foco |
|---|---|
| A. Economista experimental | Fidelidad al paper y al `.qsf`, exclusiones, comparación con humanos y teoría |
| B. Metodología de simulación con LLMs | Personas, contaminación, no independencia, qué se puede concluir |
| C. Código y replicabilidad | Errores de código, fuga de datos, robustez a escala, replicabilidad |

**Veredicto común:** el flujo es fiel al `.qsf` y no hay fuga de datos humanos hacia los prompts. Antes de la corrida había que corregir puntos del análisis y algunos detalles técnicos. Debajo de cada hallazgo está la respuesta.

## Lo que los tres confirmaron

**Fidelidad al `.qsf`.**
- El orden de pantallas, el texto del quiz y su bucle de reintento coinciden con el original.
- Las 80 bifurcaciones LEFT/RIGHT → resultado coinciden.
- Los porcentajes que se insertan (28/72, 69/31) son correctos.
- La regla del quiz (35/25/50/12; q2 False; q3 True solo en Hot; q4 = tasa anunciada) es la del original.

**Mismas personas y secuencias.** En 5.920 filas del piloto, 0 diferencias en IN/OUT, condición, edad y género respecto de `hotcold_dataset`.

**Sin fuga de datos.** Ninguna Persona usa lo que la persona real hizo o respondió.

**Análisis.** La definición de "devolver" es la de `tab2.do`, y `--validate` reproduce la Tabla 2 del paper.

**Robustez.** La construcción de Personas es determinista, la reanudación no repite agentes y una clave inválida detiene la corrida.

## Hallazgos y respuestas

### 1. La referencia humana no era "los mismos humanos" cuando un modelo pierde agentes (A, B, C)

`analysis.py` comparaba a cada modelo con todos los participantes emparejados con *cualquier* modelo. En el piloto, gpt-5-nano completó 5 de 20 agentes y la celda Hot-Low de Nemotron quedó vacía.

**Respuesta: corregido.**
- Para cada modelo × Persona hay ahora una fila **"paired humans"**: los participantes emparejados con los agentes que completaron, en las mismas rondas (`human_reci`).
- Se agregó una tabla de exclusiones por celda.
- Regla fijada: una celda con menos de 30 agentes se muestra, pero su brecha no se interpreta.
- gpt-5-nano se presenta aparte.

### 2. Agentes con error técnico entraban al análisis con rondas a medias (A, C)

**Respuesta: corregido.**
- Solo se analizan los agentes que completaron las pantallas originales, como `finished == 1` en el paper.
- Un error en la pantalla agregada al final ya no anula una sesión completa: queda en `debrief_error`.
- Regla fijada: `--retry-errors` se usa una vez después de la corrida y se reporta cuántos agentes se volvieron a correr.

### 3. El formulario Verdadero/Falso podía inducir el error de gpt-5-nano (B)

La casilla llevaba el enunciado sin "¿verdadero o falso?", y se leía como una afirmación. gpt-5-nano respondía "True" a "estás emparejado con el mismo participante en todas las rondas".

**Respuesta: aceptado y probado** con 20 agentes de gpt-5-nano (US$0,03).
- Con "True or false: …" en la casilla, las exclusiones bajaron de 15 a 10 de 20.
- El error de q2 casi desapareció, pero apareció otro en q3 ("sabés lo que eligió el otro antes de decidir" → "False" en Hot).
- Se mantiene el cambio, aplicado a todos los modelos, porque es la lectura natural de la pantalla original. Que nano siga excluyendo a muchos se reporta como resultado sobre comprensión.
- El texto de la pantalla no cambia.

### 4. El ejemplo del mensaje de sistema nombraba la opción de devolver (B)

Decía "like [ LEFT ]".

**Respuesta: corregido.** Ahora dice "like [ Next ]".

### 5. El veredicto "sí/no" del modelo de sorpresa era demasiado estricto y sin intervalos (A, B)

**Respuesta: corregido.**
- La brecha Hot − Cold se juzga en las rondas 19–20, la ventana principal del paper, con intervalos al 95%.
- Hay cinco veredictos posibles: en la dirección del paper / en contra / no se puede decir / sin variación / celda chica.

### 6. "¿Conocés este estudio?" no mide memorización (A, B)

Responde la Persona: Qwen3 235B dijo haberlo visto "en clases de economía del comportamiento".

**Respuesta: aceptado.**
- Se lee como "reconoce el tipo de juego".
- Se agregó una pregunta aparte, fuera del personaje, a cada modelo (`hotcold.probe_knowledge`).
- La pregunta del debrief ahora es neutral entre Hot y Cold: "How did you decide between LEFT and RIGHT?".

### 7. El costo de Claude se subestimaba (C)

LangChain informa las escrituras de caché de Anthropic en `ephemeral_5m_input_tokens` y deja `cache_creation` en 0.

**Respuesta: corregido**, con un test. Impacto: menos de US$1 en la corrida completa.

### 8. Las "opciones cerradas" solo se imponían en Claude (C)

OpenAI y DeepInfra recibían `strict: False`.

**Respuesta: corregido en parte.**
- OpenAI usa ahora `strict=True`.
- En DeepInfra no hay garantía de que todos los modelos lo acepten. Ahí cada respuesta se controla al recibirla y se vuelve a pedir si no encaja: en el piloto fueron 3 de unos 5.000 pedidos.
- Está documentado en el README como diferencia entre proveedores.

### 9. Robustez y replicabilidad (C)

- Un `--resume` volvía a habilitar todo el tope de gasto. **Corregido:** cuenta lo ya gastado.
- Una línea cortada al final de `results.jsonl` hacía fallar la reanudación. **Corregido:** se descarta y ese agente corre de nuevo.
- `calls.jsonl` no distinguía las sesiones reanudadas. **Corregido:** campo `session`.
- El manifiesto no guardaba `max_tokens`, la URL, los tiempos límite ni el modo estricto. **Corregido.**
- La descarga de Nemotron no fijaba la versión. **Corregido:** revisión `0bb75b1` de Hugging Face.
- `--validate` no controlaba los errores estándar. **Corregido:** reproduce los 6.
- Faltaban tests de la caché, del análisis con agentes incompletos, de la reanudación con una línea cortada y del límite compartido entre corridas. **Agregados.**
- El límite de 64 agentes simultáneos en DeepInfra no se había probado. **Pendiente:** si aparecen errores por límite de uso, la corrida se pausa sola tras 10 errores seguidos; se baja a 32 y se retoma.
- **Dónde archivar la corrida** (OSF o Zenodo): **decisión pendiente del autor.**

### 10. Desvíos mal descritos en el README (A)

- Los humanos tenían un botón "Anterior" (`BackButton: true` en el `.qsf`).
- "Expectation" y "Comment" eran optativas; el agente debe contestarlas.

**Respuesta: corregido** en la tabla de desvíos.

### 11. Solo para reportar en la tesis (A, B)

- **Repetición.** Mantener la sesión como una conversación hace que los agentes repitan su conducta: 75% o más nunca cambian de decisión, contra 38% de los humanos. La brecha de las rondas 19–20 de los agentes no se lee como aprendizaje. *Agregado al plan.*
- **Qué miden los intervalos.** Solo el azar con este prompt y esta versión del modelo; la unidad para generalizar es el modelo. *Agregado al plan.*
- **Nemotron y género.** Los 8 participantes de género "Other" o que prefirieron no decirlo reciben un relato con she/he. *Se agregó una tabla de sensibilidad sin ellos.*
- **Gemma.** Gemma escribió los textos de Nemotron y es el modelo que más cambia con ellos. Se menciona como caso atípico sin atribuirle la causa.
- **El debrief.** Es una justificación escrita después de decidir, no la causa de la decisión. Si se codifica con un LLM, se usa uno de otra familia y se valida a mano una parte. *Agregado al plan.*

## Después de la revisión

Como cambió lo que ven los agentes (puntos 3, 4, 6 y 8), se repitió el piloto de control con el código final (ver abajo).
