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

## Grupo Prueba: escribe como una supervisora
Escribes en el grupo Prueba como si fueras una supervisora (texto, foto o audio, sin `!`). Los mensajes sueltos se juntan hasta 60 s: "Foco suelto" + foto + "República de Brasil" cuentan como un solo reporte.
- **Si le toca a SOSER:** responde *Acuso recibo, se coordina.* y queda anotado como pendiente.
- **Si falta un dato:** pregunta corto, por ejemplo *¿En qué establecimiento?*, *¿Sabes cómo se rompió?* o *¿Cuál extractor, el de la cocina o uno del techo?*.
- **Si no le toca a SOSER:** responde en una frase a quién le corresponde y pregunta *¿Te comparto el porqué?*. Si dices que sí, manda las frases tal cual de la licitación con su página. *por qué* también funciona después de un acuso.

Comandos (sin `!`):
- `pendientes`: todo lo anotado. Va primero gas y equipos de calor, después por fecha. Incluye lo que reportan las supervisoras en el grupo real.
- `ruta de hoy` / `ruta de mañana`: muestra por técnico, máx. 4. Va primero lo cerrado, después gas y equipos de calor, después por orden de emisión. Junta Datácora (solo lectura) con lo anotado; lo que no tiene tarea en Datácora aparece *(sin tarea en Datácora)*.
- `emular bitácora república de brasil hoy` (o `ayer`, `18-11`): hace como si el técnico acabara de cerrar esa visita. Baja la bitácora a Verificadores SOSER, lee el PDF, lista los trabajos y coteja cada pendiente del colegio: *resuelto*, *lo revisó sin reparación* o *no aparece*. Los resueltos salen de la lista. Solo colegios JUNAEB, porque en jardines la bitácora es física.
- `resuelto 3` · `borrar 3`: cierra o borra un pendiente a mano.
- `nueva`: empieza otro caso.
- `está mal, …`: anota la corrección.

Sin emular, cada 30 min (8 a 21 h) revisa en Datácora si se cerró una visita en un colegio con pendientes de antes, y manda el cotejo solo.

- `operacion.py`: pendientes, ruta y cotejo de bitácoras (lee el PDF con `bitacoras.leer_pdf`).
- `asesor.py` + `fichas.py`: deciden a quién le toca (vidrio, extractor, gotera, electricidad, agua, desagüe, gas, plagas y general), con las citas de la licitación.
- Archivos en `Descargas/SOSER-prueba/`: `pendientes.json`, `pendientes_fotos/`, `conversaciones/`.
