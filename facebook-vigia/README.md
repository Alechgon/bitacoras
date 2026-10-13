# Vigía de pegas — Facebook (v3)

Extensión de Chrome que recorre tus grupos de Facebook **como una persona** buscando a quien **pide**
trabajos de electricidad o gasfitería, y te arma una **lista de solicitudes** con el link de la
publicación, el perfil de la persona, un link directo a Messenger y el mensaje listo para que **tú**
le escribas.

**Lo que NO hace, a propósito:** no comenta, no da like, no manda mensajes, no hace clic. Solo mira
lo que ya está en pantalla. Los likes y los mensajes los haces tú.

---

## 1) Instalar o actualizar

1. Descomprime el ZIP en una carpeta que no vayas a borrar, por ejemplo `Documentos\facebook-vigia`.
   - **Si ya lo tenías:** reemplaza los archivos de la carpeta vieja por estos (misma carpeta).
2. En Chrome entra a `chrome://extensions` y activa **Modo de desarrollador** (arriba a la derecha).
3. - **Primera vez:** botón **Cargar descomprimida** → elige la carpeta `facebook-vigia`.
   - **Actualizando:** en la tarjeta “Vigía de pegas” toca la flechita circular **⟳**.
     **Obligatorio:** si no, Chrome sigue con el motor viejo (el panel avisa con un recuadro rojo).
     Tus grupos, palabras, llave y solicitudes se conservan.
4. Fija el ícono ⚡ en la barra (pieza de puzzle → chincheta). El panel se abre solo después de actualizar.

## 2) Cómo recorre cada grupo

Por cada grupo (todos los tiempos se cambian en **Configuración**):

1. **Inicio del grupo** en orden “Actividad reciente”: se queda ~3 min bajando de a poco y leyendo
   hasta ~30 publicaciones (lo de hoy y ayer).
2. **Buscador del grupo:** escribe tus palabras del buscador una por una, ~1 min cada una, y lee hasta
   ~10 resultados.
3. **Inicio de Facebook:** ~2 min leyendo lo que aparece, buscando tus palabras del inicio.
4. Pausa de 20–60 s y pasa al siguiente grupo. Cada ~40 min de trabajo descansa ~10 min.

**Fechas:** lo de hasta **2 días** que sea un pedido → **Solicitudes** (lo de menos de 1 hora sale 🔥 y te
avisa al celular). Lo de **2 a 7 días** → **Para revisar** (lo analizas tú). Lo más viejo se descarta.

**Ventana del vigía:** el vigía usa una ventana aparte. **Déjala abierta y a la vista** (puede ser chica, a
un costado de la pantalla): Facebook solo carga más publicaciones cuando la página se ve. Si la minimizas o
queda tapada, solo alcanza a leer las primeras (la bitácora te lo avisa).

## 3) Palabras (pestaña Palabras)

- **🔎 Del buscador:** las que escribe en el buscador de cada grupo.
- **🏠 Del inicio:** las que busca dentro de las publicaciones (inicio del grupo e inicio de Facebook).
  Si una publicación trae alguna, la IA revisa si es alguien pidiendo el servicio. Además puede usar sus
  propias reglas (oficio + alguien pidiendo) por si se te escapa una palabra.
- Toca una palabra para **apagarla/prenderla**, ✏️ para **cambiarla**, ✕ para **borrarla**.
- **Palabras propias por grupo:** en la pestaña Grupos, ✏️ en la columna “Palabras del buscador”.
- **Aprendidas:** frases que el vigía vio en pedidos reales; si se repiten pasan solas a las del inicio.

Las búsquedas son lo que más vigila Facebook: mientras menos palabras del buscador, más seguro. Si tienes
muchas, en Configuración pon “Palabras por grupo” en 2 o 3 y las va rotando entre grupos.

## 4) Configurar (pestaña Configuración)

- **Llave de Gemini** (la del bot de SOSER) → **Probar**. Sin llave decide con reglas simples.
- **Tus datos** (nombre, fono, rubro, zona): la IA los usa para redactar el mensaje.
- **Cómo recorre cada grupo:** minutos y publicaciones del inicio del grupo, minutos y resultados por
  palabra, palabras por grupo, minutos del inicio de Facebook y cada cuántos grupos, orden de los pasos.
  Abajo te calcula cuánto toma cada grupo y cuánto demora una vuelta completa.
- **Pausas y descansos:** entre búsquedas, entre grupos, trabajar/descansar, horario.
- **Topes de seguridad:** grupos y búsquedas por hora y por día.
- **Fechas:** hasta cuántas horas es pega y hasta cuántos días “para revisar”.
- **Avisos al celular (gratis):** app **ntfy** → **Generar** → en la app **+** con ese nombre → **Probar**.

## 5) Cargar tus grupos (pestaña Grupos)

Toca **Importar mis grupos**: abre tu lista de grupos, la recorre y los agrega con nombre y link. Deja esa
pestaña a la vista hasta el aviso verde **Listo**. La tabla muestra cada grupo con su **nombre y link**, sus
palabras, visitas, publicaciones leídas, pegas y estado. Tiene buscador.

## 6) Usar

Toca **Activar**.

- **Actividad:** qué hace en este momento (qué grupo, qué paso, cuánto lleva y cuántas publicaciones),
  el plan del grupo actual, cuánto lleva esta hora y hoy contra los topes, y la **bitácora**: en cada paso
  toca “ver publicaciones” para ver **quién publicó, de qué se trata, hace cuánto y qué decidió**.
- **Solicitudes:** cada pega con 👤 perfil, 💬 Messenger, 📄 link de la publicación y 👥 grupo, el texto, hace
  cuánto se publicó y el mensaje sugerido (editable). **Copiar y abrir post** / **Copiar y abrir Messenger**
  copian el mensaje y abren la página para que lo pegues. Después marca **Contactado**.
  **Para revisar** tiene las de 2–7 días. **Exportar a Excel** baja la lista con todos los links.

## 7) Cómo cuida tu cuenta

- Una sola ventana/pestaña del vigía, silenciada; nunca abre varias a la vez.
- Se queda minutos en cada página, baja de a poco y a veces sube un poco, como quien lee.
- Tiempos con azar (nunca exactos), descansos largos, horario y topes por hora y por día.
- Un grupo mirado hace menos de 1 hora no se repite si hay otros disponibles; prioriza los que dan pegas.
- **Pausa automática** si Facebook pide iniciar sesión (20 min) o muestra verificación o “bloqueado / vas muy
  rápido” (24 h, configurable): te avisa y **baja los topes a la mitad**. Si el aviso te sale a ti navegando,
  también se pausa.

Si Facebook te muestra un aviso: resuélvelo tú a mano, no toques “Reanudar” y deja que termine la pausa.

## 8) Dejarlo andando

- Chrome **abierto**, Facebook **con sesión iniciada** y la **ventana del vigía a la vista**.
- Que el PC no se suspenda: Configuración de Windows → Sistema → “Inicio/apagado y batería” → Pantalla y
  suspensión → suspender: **Nunca** (enchufado).
- Para que Chrome parta solo: **Windows + R** → `shell:startup` → crea ahí un acceso directo a Chrome.

## 9) Problemas comunes

- **Recuadro rojo “Falta recargar el vigía”:** toca “Recargar ahora” (o ⟳ en `chrome://extensions`).
- **Lee muy pocas publicaciones / “ventana tapada”:** deja la ventana del vigía visible, no minimizada.
- **“Facebook pide iniciar sesión”:** entra a Facebook con tu cuenta; vuelve solo en 20 min.
- **La IA dice “demasiadas consultas”:** espera sola y sigue; nada se pierde.
- **Facebook cambió y ya no pesca publicaciones:** avísame y ajusto `content.js`.
- **Cambias de PC:** Configuración → Descargar respaldo; en el otro, Cargar respaldo.

---

## Por dentro (técnico)

- `background.js` — arma un plan por grupo (inicio → buscador → inicio de Facebook), lleva tiempos,
  descansos, horario y topes; pausas de seguridad; filtro de fechas y palabras; fila → IA → solicitudes;
  avisos (Chrome, ntfy, webhook); aprendizaje de frases. Todo cambio al almacenamiento pasa por un candado.
- `content.js` — el lector: en cada paso se queda el tiempo pedido bajando de a poco, junta publicaciones
  (autor, perfil, texto, link, fecha, grupo) y las manda de a poco; detecta login / verificación / bloqueo /
  sin acceso / sin resultados. Solo mira.
- `filtro.js` — reglas locales; `gemini.js` — IA por lotes de 8 (llave `AQ.` → Vertex, `AIza` → AI Studio).
- `panel.*` — la pantalla; `reposo.*` — lo que muestra la ventana del vigía entre grupos.

Todo queda en tu Chrome. Solo sale a internet: Facebook (tu sesión), Gemini (el texto de las
publicaciones que parecen pedido) y ntfy/webhook si los configuras.
