# Vigía de pegas — Facebook (v2)

Extensión de Chrome que mira tus grupos de Facebook buscando a quien **pide** trabajos de
electricidad o gasfitería, y te arma una **lista de solicitudes** con el mensaje listo para que
**tú** le escribas. También lee lo que aparece mientras navegas tú por Facebook.

**Lo que NO hace, a propósito:** no comenta, no da like, no manda mensajes, no hace clic. Solo mira
lo que ya está en pantalla. Eso es lo que hace que Facebook bloquee cuentas, y en esa cuenta tienes
tus 400 grupos.

---

## 1) Instalar (o actualizar desde la v1)

1. Descomprime el ZIP en una carpeta que no vayas a borrar, por ejemplo `Documentos\facebook-vigia`.
   - **Si ya tenías la v1:** reemplaza los archivos de la carpeta vieja por estos (misma carpeta).
2. En Chrome entra a `chrome://extensions` y activa **Modo de desarrollador** (arriba a la derecha).
3. - **Primera vez:** botón **Cargar descomprimida** → elige la carpeta `facebook-vigia`.
   - **Actualizando:** en la tarjeta “Vigía de pegas” toca la flechita circular ⟳ (Recargar).
     **Este paso es obligatorio:** si no, Chrome sigue usando el motor viejo (el panel te avisa con un
     recuadro rojo “Falta recargar el vigía”). Tus grupos, llave y solicitudes se conservan.
4. Fija el ícono ⚡ en la barra (pieza de puzzle → chincheta) y tócalo: se abre el **panel**.

## 2) Configurar (pestaña Configuración)

- **Llave de Gemini:** la misma del bot de SOSER. Toca **Probar** (debe salir ✓). Sin llave igual
  funciona, pero decide con reglas simples y el mensaje es una plantilla.
- **Tus datos:** nombre, fono (opcional), qué ofreces y zona. La IA los usa para redactar.
- **Ritmo:** deja **Seguro** las primeras semanas (ver tabla abajo).
- **Horario:** por defecto 07:30 a 23:30. Fuera de eso no entra a Facebook.
- **Avisos al celular (gratis):** instala la app **ntfy** en tu celular → en el panel toca **Generar**
  → en la app toca **+** y escribe ese mismo nombre → toca **Probar**. Cada pega te llega al celular y
  al tocarla se abre la publicación.
- **Guardar configuración.**

## 3) Cargar tus grupos (pestaña Grupos)

Toca **Importar mis grupos**. Se abre tu lista de grupos de Facebook, el vigía la recorre bajando la
página y los agrega con su nombre (los que ya tenías se mantienen). Deja esa pestaña a la vista hasta que
salga el aviso verde **Listo** (1 a 4 minutos) y después ciérrala.

También puedes pegarlos a mano, uno por línea (`link | Nombre`), o con la consola F12 (plan B, explicado
en el mismo panel).

## 4) Usar

Toca **Activar** (arriba). Desde ahí, con Chrome abierto, trabaja solo.

- **Actividad:** qué está haciendo en este momento (mirando tal grupo, buscando tal palabra,
  esperando con cuenta regresiva, descansando, en pausa), cuánto lleva esta hora y hoy contra el máximo,
  la **bitácora** de todo con la hora, y cada publicación que leyó con lo que decidió (PEGA / no / vieja).
- **Solicitudes:** cada pega con el texto, tipo, urgencia, comuna, hace cuánto se publicó y el mensaje
  sugerido (lo puedes editar). Botón **Copiar y abrir post**: copia el mensaje y abre la publicación para
  que lo pegues. Después marca **Contactado**. **Exportar a Excel** baja la lista.
- **Grupos:** cuántas veces miró cada grupo, cuántas pegas dio y si tiene problemas (sin acceso, etc.).
- **Palabras:** las que busca dentro de los grupos y las que va **aprendiendo** de las pegas reales.

Verás una **pestaña fija** (a la izquierda, chiquitita) que dice “Vigía en reposo”: es la que usa para
mirar. Déjala abierta.

## 5) Cómo cuida tu cuenta

| Ritmo  | Una mirada cada | Máx/hora | Máx/día | Búsquedas máx (hora/día) | Descanso |
|--------|-----------------|----------|---------|--------------------------|----------|
| Seguro | ~3 min          | 12       | 100     | 4 / 30                   | ~15 min cada ~25 min |
| Normal | ~2 min          | 20       | 170     | 6 / 50                   | ~12 min cada ~40 min |
| Rápido | ~1,2 min        | 32       | 280     | 10 / 80                  | ~10 min cada ~60 min |

Además, siempre:
- **Una sola pestaña**, fija y silenciada; nunca abre varias a la vez.
- Tiempos **con azar** (nunca exacto), a veces se “distrae” más rato, y baja la página de a poco.
- Las **búsquedas** (lo que más vigila Facebook) son solo 1 de cada 3 visitas; el resto mira lo más
  nuevo del grupo.
- Prioriza los grupos donde más pegas salen y salta 7 días los que no tienen acceso.
- **Pausa automática** si Facebook muestra: pedir iniciar sesión (20 min), verificación de seguridad o
  “bloqueado / vas muy rápido” (24 h, configurable). Ahí además vuelve el ritmo a **Seguro** y te avisa
  (Chrome + celular). Si ves un aviso así mientras navegas tú, también se pausa.

**Si Facebook te muestra un aviso:** resuélvelo tú a mano, no toques “Reanudar” y deja que termine la
pausa. Si se repite, baja el horario o deja menos grupos.

**¿Cuánto demora en recorrer 400 grupos?** En Seguro, ~100 visitas al día → una vuelta completa en
~4 días, pero los grupos que dan pegas los mira mucho más seguido, y lo que tú ves navegando también
se revisa al tiro. Después de 1–2 semanas sin avisos puedes pasar a **Normal**.

## 6) Dejarlo andando

- Chrome tiene que estar **abierto** y con tu Facebook **con sesión iniciada**.
- Que el PC **no se suspenda**: Configuración de Windows → Sistema → “Inicio/apagado y batería” (o
  “Energía”) → Pantalla y suspensión → suspender: **Nunca** (cuando está enchufado). La pantalla sí se
  puede apagar.
- Para que Chrome parta solo al prender el PC: tecla **Windows + R** → escribe `shell:startup` → Enter →
  en esa carpeta crea un acceso directo a Google Chrome.

## 7) Problemas comunes

- **“Falta cargar grupos” / no hace nada:** revisa que diga Grupos ✓ arriba de la Actividad y que esté
  **Activo**.
- **“La página cargó pero no mostró publicaciones” muchas veces:** en Configuración marca “Usar una
  ventanita aparte” (si pasa 3 veces seguidas lo activa solo). La ventanita puede quedar detrás.
- **“Facebook pide iniciar sesión”:** entra a Facebook en Chrome con tu cuenta; vuelve solo en 20 min.
- **La IA dice “demasiadas consultas”:** se espera sola y sigue; nada se pierde (queda en la fila).
- **Facebook cambió y ya no pesca publicaciones:** avísame y ajusto `content.js`.
- **Cambias de PC:** Configuración → **Descargar respaldo**; en el otro PC, **Cargar respaldo** (la llave
  se pone de nuevo, no va en el archivo).

---

## Por dentro (técnico)

- `background.js` — el capataz: horario, sesiones/descansos, topes por hora/día (ventana móvil),
  elección de grupo por prioridad, una pestaña fija reutilizada, pausas de seguridad, fila → filtro →
  IA → solicitudes, avisos (Chrome, ntfy, webhook) y aprendizaje de frases. Todo cambio al
  almacenamiento pasa por un candado para que nada se pise.
- `content.js` — el lector: detecta login / verificación / bloqueo / sin acceso / sin resultados,
  junta las publicaciones (autor, texto, link, antigüedad), baja la página de a poco. Solo mira.
- `filtro.js` — reglas locales: decide qué vale la pena mandar a la IA y clasifica si no hay llave.
- `gemini.js` — clasifica de a lotes de 8 (llave `AQ.` → Vertex, `AIza` → AI Studio), maneja el 429.
- `panel.*` — la pantalla. Lee el almacenamiento directo y se actualiza sola.
- `reposo.*` — lo que muestra la pestaña del vigía entre una mirada y otra.

Todo queda en tu Chrome. Solo sale a internet: Facebook (tu sesión), Gemini (el texto de las
publicaciones que parecen pega) y ntfy/webhook si los configuras.
