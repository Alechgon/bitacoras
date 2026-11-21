# IA de prueba — modo sombra (rama `prueba-ia`)

Esta carpeta NO es el bot real. Usa la misma instalación del celular (Qwen, whisper, Datácora) pero corre aparte,
desde `~/soser-prueba` (una "segunda vista" del mismo repo, sin descargar nada de nuevo:
`git -C ~/bitacoras worktree add ~/soser-prueba prueba-ia`), y:
- lee lo que el bot real copia del grupo **Mantención - operaciones** en `~/soser-espejo` (el "espejo");
- junta los mensajes seguidos de cada supervisora (foto + "Foco suelto" + "Republica de brasil" = una solicitud);
- pasa audios a texto (whisper) y lee fotos de documentos (tesseract);
- con el **conocimiento** (contexto, rubros y plazos, glosario) entiende qué piden: tipo, rubro, qué piden,
  colegio, urgencia y plazo, y mira en Datácora (solo lectura) si ya hay visita;
- anota todo en `Descargas/SOSER-prueba/solicitudes.xlsx`, con la **respuesta que habría dado** y el **plazo que exige la licitación**;
- y lo manda **solo al grupo "Prueba"** (a través del bot real, buzón `~/soser-espejo/salida`). Al grupo de supervisoras no va nada.

Desde WhatsApp (tú): `!ia ver` · `!ia corrige 12 rubro ELEC; quiere …` · `!ia probar Foco suelto | Republica de brasil`

Se educa así:
1. Editando `Descargas/SOSER-prueba/conocimiento/*.md` (procedimientos, bases de licitación, glosario…).
2. Corrigiendo (en WhatsApp con `!ia corrige …` o en Termux): `python sombra.py corrige 12 rubro ELEC; colegio brasil; quiere fijar el tubo` (queda como ejemplo).
3. Con historial: WhatsApp → grupo → ⋮ → Más → Exportar chat → Incluir archivos → guardar el .zip en Descargas →
   `python sombra.py importar ~/storage/downloads/<archivo>.zip`.
4. `python sombra.py reprocesar` vuelve a leer todo con lo aprendido.

Cuando esté afinada y Manuel lo diga, se pasa a la rama principal.

## Asesor de la licitación (conversa)
En el grupo **Prueba** le hablas normal, con texto o audio y sin `!`. Por ejemplo: *"tengo un vidrio roto en el República de Haití"*.
1. Te pregunta lo que necesita para decidir, como lo haría un colega. Ejemplos: *¿sabes cómo se rompió?*, *¿es el extractor de abajo o el del techo?*, *¿colegio o jardín?*.
2. Te dice a quién le toca (👉 *Le toca a: …*) y te pregunta *¿quieres que te comparta el porqué?*.
3. Si respondes que sí, te manda por escrito las frases tal cual de las Bases, el SGC o el DT de mantención, con su página. Sirve para reenviárselo al director.

Durante la conversación:
- *"en realidad fue un alumno"*: cambia la conclusión.
- *nueva*: empieza otro caso.
- *está mal, …*: anota la corrección en `asesor_correcciones.jsonl`.

Si preguntas otra cosa (multas, plazos, auditorías…), busca en los documentos, te responde corto y te ofrece mostrar de dónde sale.

- `asesor.py` es la conversación. La IA entiende tus respuestas y redacta. Si cambia la conclusión o inventa números, se usa el texto de la ficha.
- `fichas.py` tiene los casos: vidrio, extractor, gotera, electricidad, agua, desagüe, gas, plagas y uno general para todo lo demás. Cada ficha dice qué preguntar, a qué se llega y qué frase de qué página lo respalda.
- `Descargas/SOSER-prueba/conversaciones/` guarda todo lo conversado, para revisarlo.
- Para probar en Termux: `python asesor.py "se cortó la luz"` y después `python asesor.py "en todo el colegio"`.
