# Vigía de pegas — Facebook (v4)

Extensión de Chrome que recorre tus grupos de Facebook **como una persona** buscando a quien **pide**
trabajos de electricidad, gasfitería o construcción, y te arma la lista con la fecha de cada publicación,
el link exacto, el perfil de la persona, un link a Messenger y el mensaje listo para que **tú** le escribas.

**Lo que NO hace, a propósito:** no comenta, no da like, no manda mensajes, no hace clic. Solo mira.
Los likes y los mensajes los haces tú.

---

## 1) Instalar o actualizar

1. Descomprime el ZIP en una carpeta que no vayas a borrar (por ejemplo `Documentos\facebook-vigia`).
   Si ya lo tenías, reemplaza los archivos de la carpeta vieja.
2. Chrome → `chrome://extensions` → **Modo de desarrollador** (arriba a la derecha).
3. Primera vez: **Cargar descomprimida** → la carpeta. Actualizando: la flechita **⟳** en la tarjeta del vigía
   (**obligatorio**; si no, el panel avisa con un recuadro rojo). Se conserva todo.
4. El panel se abre solo.

## 2) El ciclo en cada grupo (todo se cambia en Configuración)

1. **Inicio del grupo** (orden “Actividad reciente”): baja de a poco hasta leer **30** publicaciones.
2. **Buscador del grupo**: escribe tus palabras una por una y lee **10** resultados de cada una.
3. **Inicio de Facebook**: lee **30**, aprieta **F5** (actualizar) y lee **30** más.
4. Pausa y sigue con el siguiente grupo. Cada ~40 min descansa ~10.

Lee hasta juntar la cantidad; si el grupo no tiene más o se cumple el tiempo máximo, sigue y lo anota en la
bitácora (“leí 18 de 30, no había más”). Cada paso dice además cuántas fechas, links y nombres pudo leer
(“fecha 30/30, link 30/30, nombre 30/30”).

## 3) La fecha de cada publicación

Facebook esconde la hora a propósito (la dibuja con letras revueltas). El vigía la saca de 4 formas, en este
orden: la hora exacta que Facebook guarda escondida en la página, el globito que sale al pasar el puntero por la
hora, las letras que de verdad se ven en pantalla, y el texto tal cual. Cada solicitud muestra:

- **Publicado** con día y hora, y un **“hace 2 h 14 min” que va corriendo** en vivo.
- Qué decía Facebook cuando la vio (“3 h”, “Ayer a las 14:30”…) y a qué hora la vio.

Hasta **2 días** → Solicitudes (las de menos de 1 hora salen 🔥 y te avisa al celular). De **2 a 7 días** →
**Para revisar**. Más viejas → se descartan.

## 4) Solicitudes y la pestaña “Lista”

- Tarjetas con 👤 perfil, 💬 Messenger, 📄 link a **esa** publicación y 👥 grupo; **Copiar y abrir** el post o
  Messenger con el mensaje ya copiado.
- **📋 Lista**: una tabla para bajar con scroll — **Tipo** (lo juzga la IA: electricidad, gasfitería,
  construcción) · **Persona** · **Grupo** · **Publicado** · **Qué necesita** · **link a la publicación**.
  Se ordena de más nuevas a más antiguas o al revés, se filtra por tipo y estado, y tiene buscador.
- **Revisar de nuevo**: vuelve a pasar por la IA las que entraron sin IA; las que no son pega pasan a
  Descartadas.
- **Exportar a Excel** con todos los links.

## 5) La IA (Gemini) y su alarma

- Pega tu llave en Configuración → **Probar**. Arriba se ve si la IA está funcionando y cuántas revisó hoy.
- Si la IA falla (llave mala, API apagada, cuota gratis agotada, sin internet), aparece una **alarma roja en
  la esquina** del panel (y un aviso en Chrome y en el celular). Al tocarla se abre una ventana que dice qué
  pasó, qué hacer, con **el botón que te lleva justo a la página para arreglarlo** (por ejemplo, “Habilitar la
  API” de tu proyecto), un cuadro para **pegar la llave** y **Guardar y probar**. Mientras tanto el vigía sigue
  trabajando con reglas.
- Las llaves: Google AI Studio → https://aistudio.google.com/apikey · Vertex modo express →
  https://console.cloud.google.com/vertex-ai/studio · Google Cloud → https://console.cloud.google.com/apis/credentials

## 6) Configuración

- **El ciclo:** cuántas publicaciones leer y tiempo máximo en cada paso, cuántos F5, palabras por grupo
  (0 = todas), orden de los pasos. Abajo calcula cuánto toma cada grupo y una vuelta completa.
- **Pausas y descansos** y el **Ajuste fino**: los segundos de cada movimiento (esperar que cargue, leer cada
  pantalla, tirones de ruedita, subir a releer, pasar el puntero por la hora, “escribir” la palabra, antes del
  F5, paciencia cuando no aparece nada).
- **Topes de seguridad** por hora y por día (0 = sin tope, bajo tu riesgo).
- **Rubros** que te interesan, **fechas**, **ventana del vigía**, “cuando no uso el PC, poner la ventana del
  vigía adelante”, avisos al celular (ntfy), respaldo.
- **Diagnóstico**: si la bitácora dice “fecha 0/30” o “nombre 0/30”, toca **Hacer diagnóstico**, descarga el
  archivo y mándamelo para ajustarlo exacto a tu Facebook.

## 7) Para que funcione bien

- Chrome abierto, Facebook con sesión, y la **ventana del vigía a la vista** (puede ser chica, a un costado):
  Facebook solo carga más publicaciones cuando la página se ve.
- PC sin suspensión: Configuración de Windows → Sistema → Inicio/apagado → suspender: Nunca (enchufado).

## 8) Cómo cuida tu cuenta

Una sola ventana, ritmo de persona con azar, descansos, horario y topes. Si Facebook muestra login (20 min),
verificación o “vas muy rápido” (24 h), se pausa solo, te avisa y baja los topes a la mitad.

---

Por dentro: `background.js` (el ciclo, tiempos, pausas, IA, solicitudes, alarma), `content.js` (lee la página:
autor, perfil, texto, link, fecha), `gemini.js` (IA por lotes y diagnóstico de errores), `filtro.js` (reglas sin
IA), `panel.*` (la pantalla), `reposo.*` (la ventana del vigía entre grupos). Todo queda en tu Chrome.
