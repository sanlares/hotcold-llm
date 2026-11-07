# Pilotos (noviembre de 2026)

Antes de fijar el diseño se corrieron pilotos chicos para encontrar errores y elegir modelos y Personas. **Son exploratorios**:
- 20 agentes por combinación (5 por condición), siempre los mismos 20 participantes reales y las mismas secuencias;
- con 20 agentes, diferencias de 10 a 20 puntos entran en el ruido.

Costo total: unos US$6.

Las tablas de esta página se calcularon con la definición de los pilotos: en Cold, solo las rondas en que el primer jugador eligió IN. El análisis definitivo usa la definición del paper, con todas las decisiones (ver `plan_de_analisis.md`).

## 1. Modelos

Se probaron:
- **Anthropic:** Claude Haiku 5.5 y Sonnet 5.5;
- **OpenAI:** gpt-5-nano;
- **DeepInfra**, modelos abiertos o baratos:
  - DeepSeek V4 Flash;
  - Llama 4 Scout;
  - Gemma 4 31B;
  - gpt-oss-120b;
  - Qwen3 235B;
  - Qwen 3.8 Flash.

Todos sin razonamiento extendido, o con el mínimo de cada modelo.

Con la Persona básica (demografía real + datos inventados neutros, ver §2), el % de veces que devolvieron la confianza fue (Hot / Cold; humanos de esos 20: 42% / 43%):

| Modelo | Hot / Cold |
|---|---|
| Haiku 5.5 | 0 / 35 |
| Sonnet 5.5, gpt-5-nano | ≈ 100 / 100 |
| DeepSeek V4 Flash | 41 / 21 |
| Llama 4 Scout | 39 / 18 |
| Gemma 4 31B | 40 / 15 |
| gpt-oss-120b | 32 / 54 |
| Qwen3 235B, Qwen 3.8 Flash | 0 / 0 |

Lo que se aprendió:
- **Los modelos difieren mucho entre sí.** Algunos nunca devuelven la confianza; otros, siempre. La variación relevante está **entre modelos**, no entre agentes de un mismo modelo. Por eso el diseño final compara 8 modelos.
- Solo algunos modelos (DeepSeek, Llama, Gemma) muestran la dirección del paper (Hot > Cold).
- **Dentro de cada agente casi no hay variación entre rondas.** Cada agente elige una vez y repite. En los humanos, el 62% a veces devuelve y a veces no.
- **gpt-5-nano falló el quiz de comprensión** en 8 de 20 agentes. El error más común: responder que juega siempre con el mismo participante. Con Personas largas falló en 18 de 20. En los humanos esto es muy raro.
- Pedir un motivo en cada decisión cambia la conducta (Haiku pasó de 0% a 19% en Hot). Por eso el diseño final no lo pide durante el juego.
- Activar el razonamiento en Haiku no cambió los resultados.
- **Sonnet 5.5** quedó afuera por costo (≈ 17 veces Haiku) y porque devolvía siempre.

## 2. Fuentes de Persona

Con los mismos 20 participantes se probaron seis formas de describir al agente:

| Persona | Qué contiene |
|---|---|
| Básica | Demografía real + datos inventados neutros (nombre, ciudad, carrera, familia, hobbies) |
| Rica | Un relato de vida en primera persona, escrito a mano con un LLM |
| PRISM | Básica + la autodescripción real de valores de un participante del Reino Unido de PRISM (Kirk et al., 2024) |
| Nemotron | Demografía real + el relato de una persona sintética de Nemotron-Personas-UK (NVIDIA), emparejada por edad, sexo y educación |
| Twin, resumen | Resumen de un participante real de EE. UU. de Twin-2K-500 (Toubia et al., 2025), sin los juegos económicos |
| Twin, relato | Lo mismo, reescrito en primera persona por un LLM |

Resultados (Hot / Cold, %):

| Modelo | Básica | Rica | PRISM | Nemotron | Twin resumen | Twin relato |
|---|---|---|---|---|---|---|
| Haiku | 0 / 35 | 74 / 64 | 81 / 82 | 42 / 56 | 41 / 39 | 64 / 65 |
| DeepSeek V4 Flash | 41 / 21 | 69 / 46 | 79 / 83 | 61 / 38 | 57 / 60 | 57 / 46 |
| Qwen3 235B | 0 / 0 | 0 / 20 | 59 / 54 | 5 / 0 | 27 / 6 | 27 / 18 |
| Qwen 3.8 Flash | 0 / 0 | 0 / 20 | 75 / 21 | 5 / 31 | 38 / 32 | 72 / 74 |
| Gemma 4 | 40 / 15 | 66 / 54 | 85 / 71 | 51 / 72 | 57 / 61 | 72 / 74 |
| gpt-oss-120b | 32 / 54 | 20 / 47 | 51 / 53 | 41 / 77 | 37 / 38 | 32 / 77 |
| Llama 4 Scout | 39 / 18 | 46 / 23 | 48 / 35 | 38 / 36 | 46 / 12 | 19 / 20 |

Lo que se aprendió:
- **Cómo se describe a la persona cambia mucho la conducta del agente**: de 0% a 85% con la misma persona real. PRISM, donde la gente se describe por sus valores, empuja a todos los modelos a devolver.
- **Las Personas aumentan las diferencias entre agentes, pero no dentro de cada agente.**
- En los humanos de *Baseline*, edad, género y educación explican solo un 3% de las diferencias en reciprocidad. Una Persona solo demográfica no puede reproducir esa variedad, aunque el modelo la usara perfecto.
- En una validación aparte con Twin-2K-500, cada agente jugó el juego de confianza que había jugado su persona real. Las Personas casi no predicen lo que hizo cada persona (correlaciones de 0,0 a 0,2).

## 3. Por qué el diseño final usa la Persona demográfica y la de Nemotron

- **Demográfica (sin nada inventado):** es el control. Muestra lo que hace el modelo sabiendo solo lo que el experimento registró de cada persona.
- **Nemotron:** es la fuente de variación entre agentes que mejor respeta el marco del experimento: estudiantes del Reino Unido de la misma edad, sexo y educación que el participante real. Además, el procedimiento está documentado por un tercero:
  - la demografía sale de los censos del Reino Unido de 2021–2022;
  - la personalidad, de puntajes regionales de Rentfrow, Jokela y Lamb (2015);
  - el texto lo escribe Gemma 4 31B a partir de eso.

  No la escribieron los autores de esta tesis ni se eligió mirando resultados.
- **Twin-2K-500** tiene preferencias medidas en personas reales, pero son adultos de EE. UU., no estudiantes del Reino Unido. Queda como posible validación aparte.
- La Persona básica, la rica y PRISM se descartan: inventan rasgos o, en el caso de PRISM, empujan sistemáticamente a cooperar.

## Código de los pilotos

Las fuentes exploratorias siguen disponibles con `--persona basic | rich | prism | twin-summary | twin-narrative | twin-qa | twin-demographic`, solo para los 20 agentes del piloto (`hotcold/sources.py`, `hotcold/twin_trust.py`, `hotcold/compare.py`).
