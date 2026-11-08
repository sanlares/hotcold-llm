# Auditoría del input

Generado por `uv run python -m hotcold.audit_inputs`. Revisa todo lo que se le manda a los agentes (mensaje de sistema, pantallas y formularios de respuesta) para los dos brazos del diseño final, sin llamar a ningún modelo.

- Brazos revisados: demographic (396 agentes), nemotron (396 agentes)
- **Problemas que hay que corregir: 0**

## Problemas

Ninguno.

## Casos para leer a mano

No son errores: son agentes cuya Persona conviene mirar antes de correr.

### Persona demográfica (45)

- `baseline_40`: age 44 → "You are a woman aged 44. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_48`: age 47 → "You are a woman aged 47. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_53`: age 42 → "You are a man aged 42. You live in the UK and you are a student at PhD level or above. Now and then you take part in paid online studies on …"
- `baseline_74`: education 'Other' → "You are a woman aged 18. You live in the UK and you are a student; your educational background does not fit the usual categories (high schoo…"
- `baseline_79`: age 57 → "You are a woman aged 57. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_99`: gender 'Other' → "You are aged 25; you do not identify as a man or a woman. You live in the UK and you are a bachelor's student. Now and then you take part in…"
- `baseline_119`: age 47 → "You are a woman aged 47. You live in the UK and you are a master's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_124`: gender 'Other' → "You are aged 31; you do not identify as a man or a woman. You live in the UK and you are a student at PhD level or above. Now and then you t…"
- `baseline_140`: gender 'Other' → "You are aged 20; you do not identify as a man or a woman. You live in the UK and you are a bachelor's student. Now and then you take part in…"
- `baseline_149`: gender 'I would rather not say' → "You are aged 19; you prefer not to disclose your gender. You live in the UK and you are a student; your educational background is high schoo…"
- `baseline_151`: gender 'Other' → "You are aged 28; you do not identify as a man or a woman. You live in the UK and you are a master's student. Now and then you take part in p…"
- `baseline_180`: age 43 → "You are a woman aged 43. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_185`: age 47 → "You are a woman aged 47. You live in the UK and you are a master's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_195`: age 47 → "You are a woman aged 47. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_212`: age 41 → "You are a man aged 41. You live in the UK and you are a master's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_220`: gender 'Other' → "You are aged 19; you do not identify as a man or a woman. You live in the UK and you are a bachelor's student. Now and then you take part in…"
- `baseline_231`: gender 'Other' → "You are aged 20; you do not identify as a man or a woman. You live in the UK and you are a student; your educational background is high scho…"
- `baseline_236`: age 44 → "You are a woman aged 44. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_237`: age 52 → "You are a woman aged 52. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_243`: age 41 → "You are a woman aged 41. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_246`: age 58 → "You are a woman aged 58. You live in the UK and you are a student at PhD level or above. Now and then you take part in paid online studies o…"
- `baseline_274`: age 42 → "You are a woman aged 42. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_275`: gender 'Other' → "You are aged 28; you do not identify as a man or a woman. You live in the UK and you are a master's student. Now and then you take part in p…"
- `baseline_280`: age 42 → "You are a man aged 42. You live in the UK and you are a master's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_282`: age 49 → "You are a man aged 49. You live in the UK and you are a student at PhD level or above. Now and then you take part in paid online studies on …"
- `baseline_285`: age 42 → "You are a man aged 42. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_288`: age 44 → "You are a man aged 44. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_294`: age 41 → "You are a woman aged 41. You live in the UK and you are a master's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_298`: education 'Other' → "You are a woman aged 19. You live in the UK and you are a student; your educational background does not fit the usual categories (high schoo…"
- `baseline_401`: education 'Other' → "You are a woman aged 30. You live in the UK and you are a student; your educational background does not fit the usual categories (high schoo…"
- `baseline_402`: age 59 → "You are a man aged 59. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_419`: age 42 → "You are a woman aged 42. You live in the UK and you are a master's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_422`: age 59 → "You are a woman aged 59. You live in the UK and you are a master's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_434`: age 40 → "You are a woman aged 40. You live in the UK and you are a student at PhD level or above. Now and then you take part in paid online studies o…"
- `baseline_442`: age 51 → "You are a man aged 51. You live in the UK and you are a master's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_450`: education 'Other' → "You are a man aged 19. You live in the UK and you are a student; your educational background does not fit the usual categories (high school …"
- `baseline_452`: age 45 → "You are a man aged 45. You live in the UK and you are a master's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_454`: age 40 → "You are a man aged 40. You live in the UK and you are a master's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_455`: age 52 → "You are a woman aged 52. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_456`: age 41 → "You are a man aged 41. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_477`: age 51 → "You are a man aged 51. You live in the UK and you are a student at PhD level or above. Now and then you take part in paid online studies on …"
- `baseline_480`: age 41 → "You are a woman aged 41. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_482`: age 41 → "You are a man aged 41. You live in the UK and you are a bachelor's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_483`: age 45 → "You are a man aged 45. You live in the UK and you are a master's student. Now and then you take part in paid online studies on Prolific.…"
- `baseline_488`: age 50 → "You are a woman aged 50. You live in the UK and you are a master's student. Now and then you take part in paid online studies on Prolific.…"

### Nemotron (11)

Calidad del emparejamiento: diferencia de edad 0 años: 373, 1 años: 20, 2 años: 2, 4 años: 1; misma educación: 396 de 396; todos son estudiantes.

- `baseline_99` (Other, 25, Bachelor student; Nemotron `92485c0f`): real gender 'Other', text uses she/her 17, he/him 0
- `baseline_124` (Other, 31, PhD student or above; Nemotron `901a51f5`): real gender 'Other', text uses she/her 0, he/him 23
- `baseline_140` (Other, 20, Bachelor student; Nemotron `179affb8`): real gender 'Other', text uses she/her 0, he/him 14
- `baseline_149` (I would rather not say, 19, High school or below; Nemotron `68506bf2`): real gender 'I would rather not say', text uses she/her 14, he/him 0
- `baseline_151` (Other, 28, Master student; Nemotron `3913b030`): real gender 'Other', text uses she/her 15, he/him 0
- `baseline_220` (Other, 19, Bachelor student; Nemotron `a03e7cd7`): real gender 'Other', text uses she/her 17, he/him 0
- `baseline_231` (Other, 20, High school or below; Nemotron `90059b25`): real gender 'Other', text uses she/her 0, he/him 16
- `baseline_275` (Other, 28, Master student; Nemotron `20b28e74`): real gender 'Other', text uses she/her 13, he/him 0
- `baseline_453` (Male, 39, Bachelor student; Nemotron `ef992a43`): match: age difference 2, same education True
- `baseline_456` (Male, 41, Bachelor student; Nemotron `5a829b9c`): match: age difference 2, same education True
- `baseline_482` (Male, 41, Bachelor student; Nemotron `d11f5618`): match: age difference 4, same education True
