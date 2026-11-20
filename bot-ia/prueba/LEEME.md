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
