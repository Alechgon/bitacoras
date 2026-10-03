# Bot IA — SOSER San Pablo

Lee el grupo de supervisoras, entiende de qué establecimiento hablan y qué falla
reportan, le pone puntaje con **los mismos pesos de tu panel**, lo agenda en un
bloque de Rodrigo o Camilo y responde en el grupo, con un delay, para qué día quedó.
Además genera el reporte en Excel y empuja los hallazgos al panel.

Trabaja sobre tu `datos.js`. No hay que cargar ningún Excel aparte: si regeneras
`datos.js` y lo subes al repo, el bot lo toma solo en máximo 30 minutos.

## Cómo funciona (versión niño de 4 años)

| Pieza | Qué es | Qué hace técnicamente |
|---|---|---|
| **Termux** | la casita Linux dentro del celu | corre Node y Python en Android |
| **bot.mjs** | el cartero | Baileys: se conecta como WhatsApp Web, lee el grupo y responde con 35-95 s de espera y "escribiendo..." |
| **ia.py** | el cerebrito | manda el mensaje + la lista de los 93 establecimientos a Gemini, que devuelve RBD, problema y tipo (GAS/FRIO/AGUA/ELEC/EQUIPO/OTRO). Si Gemini falla, usa los alias y palabras clave del panel |
| **nucleo.py** | el capataz | tus reglas: puntaje, plazos, bloques, aplazamientos y metas. Sin IA, siempre da el mismo resultado |
| **agenda.db** | el cuaderno | SQLite con la agenda viva, los hallazgos y el registro de cambios |
| **servidor.py** | el jefe de obra | une todo en `127.0.0.1:8765`, solo dentro del celular |
| **reportes.py** | el que hace los informes | Excel con metas, Gantt día × bloque × técnico, detalle, hallazgos y cambios |

## Las reglas que aplica

**Puntaje 1 a 20.** Se toma la base del establecimiento desde el `why` de `datos.js`
(cobertura, raciones, jardín, tipo de gas). A eso se suma la falla nueva según los
`pesos` del panel: GAS +6, FRIO/AGUA +4, ELEC +3, EQUIPO +2, OTRO +1. Si el mensaje
dice *urgente*, *prioridad* o *no pueden cocinar*, suma además la prioridad (+2).

**Plazos máximos (días hábiles).** GAS 1, FRIO y AGUA 2, ELEC 3, EQUIPO 5, OTRO 10.
Con prioridad declarada, el plazo baja a 2. Ninguno pasa de 10, por la regla de supervisoras.

**Cómo agenda, en este orden:**

1. Si el establecimiento ya tiene una visita dentro del plazo, el correctivo se cierra
   en esa visita (la tarjeta pasa a *VISITA + CORRECTIVO* o *PREV + CORRECTIVO*).
2. Si tiene una visita más adelante, la **adelanta** en vez de duplicarla.
3. Busca un bloque libre. GAS va primero a **Camilo** (instalador de gas SEC) y ELEC
   a Rodrigo. En el resto elige al técnico que ese día ya anda más cerca, usando las
   coordenadas de `datos.js`.
4. Si no hay bloque libre, **aplaza una sola vez** una VISITA o PREVENTIVA, la de menor
   puntaje, sin pasarla de su meta: JUNAEB al 30-oct, jardines al 15-dic. Cada
   aplazamiento suma +1 punto. **El gas no se aplaza nunca.**
5. Si igual no cabe, lo agrega como **bloque extra** (las emergencias no tienen límite)
   y lo avisa en el grupo para que lo confirmes.

Los plazos, la preferencia de técnico y las palabras de prioridad se cambian en `config.json`.

## Instalación (una vez, unos 10 minutos)

**Antes:** ten a mano tu API key de Gemini (gratis en https://aistudio.google.com/apikey →
*Create API key*), el chip del bot con WhatsApp funcionando y metido al grupo de
supervisoras, y Termux + Termux:Boot instalados desde **F-Droid** (no Play Store).

**En Termux pega esto y nada más:**

```bash
pkg install -y git && { [ -d ~/bitacoras ] || git clone https://github.com/Alechgon/bitacoras ~/bitacoras; } && bash ~/bitacoras/bot-ia/instalar.sh
```

Instala todo, te pide la API key, tu número y el del bot, y te muestra un código de 8
letras. En el WhatsApp del bot ve a *Dispositivos vinculados → Vincular dispositivo →
Vincular con número de teléfono* y escribe ese código. Con eso queda corriendo: revive
solo si se cae y arranca solo al prender el teléfono.

Último paso en Android: *Ajustes → Batería → Termux → Sin restricciones* (en Xiaomi y
Samsung, además, *inicio automático*).

Ver qué hace: `tail -f ~/bitacoras/bot-ia/logs/bot.log` · Detenerlo: `bash ~/bitacoras/bot-ia/detener.sh`

## Comandos en el grupo

| Comando | Qué hace |
|---|---|
| `!hoy` · `!mañana` · `!semana` | Agenda por técnico y bloque |
| `!agenda camilo` | Próximos 5 días de un técnico |
| `!ficha 8489` | Puntaje desglosado, cobertura y próxima visita |
| `!metas` | Avance JUNAEB en Datácora y jardines con preventiva |
| `!pendientes` | Mensajes por confirmar y establecimientos sin visita |
| `!es 8489` | Confirma el establecimiento cuando el bot preguntó «¿cuál es?» |
| `!hecho 8489` | Marca realizada la próxima visita de ese RBD |
| `!reporte` | Manda el Excel completo |
| `!mover 8489 09-10 2` | *(solo admin)* Mueve una visita, por ejemplo el segundo aplazamiento autorizado |
| `!anular 8489` | *(solo admin)* Saca la visita del plan |
| `!id` | Muestra el ID del chat |

**Automático:** a las 07:30 (lun-vie) manda la agenda del día al grupo, y a las 17:40
te manda el Excel por privado. Las horas se cambian en `config.json`.

## Tu chat privado (lenguaje natural)

| Escribes | Qué hace |
|---|---|
| `ok` · `no` · `agendar` | sobre el último caso pendiente (o el que cites) |
| `caso 6 no` · `6 ok` · `ok 4 y 5` · `ok todos` | sobre esos casos |
| `caso 6: pregúntale si tiene fotos` | le pregunta a la supervisora **en el grupo**, citando su mensaje y mencionándola. Lo que responda (texto o foto) se pega al caso y te llega |
| `caso 6 responde: mañana va Camilo` | tu texto reemplaza el borrador y se envía |
| `el 3 pásalo a Camilo el jueves b2` | lo reprograma; lo que había en ese bloque se posterga al siguiente hueco |
| `caso 2 + llevar flexible` | suma una nota |
| `regla 5 si` / `regla 5 no` | acepta o rechaza una regla que el bot te propuso |

## Conversación en el grupo

Cuando una supervisora avisa un caso, el bot habla como persona (directo en el grupo, a ti te llega copia):
0. Primero confirma el colegio: "¿Es el República de Francia de Estación Central? ¿Y de qué se trata?"
1. Si no dice qué pasa: "Carla, ¿de qué se trata la emergencia en el X? Así vemos quién va y qué llevar."
2. Si no se entiende el colegio: "¿En qué colegio es? ¿Es el Carolina Vergara Ayares?"
3. Si es urgente (gas, frío, agua, o dice emergencia/urgente): lista tus visitas de hoy y del día hábil
   siguiente por técnico con su horario, propone un bloque libre si hay, y pregunta cuál se puede cambiar.
   Responden "sí", "la del Confederación Suiza", "el segundo bloque del segundo día", "cualquiera" o "ninguna".
   La visita que se aplaza pasa UN día hábil (mismo bloque si está libre; si no, como extra para que tú ordenes).
4. A ti te llega el resultado con `deshacer N`. `!hilos` lista las conversaciones, `!cerrar N` corta una.
5. Sin respuesta en 45 min: gas/prioridad se agenda solo; lo demás queda sin hora en tu `!plan`.

## Verificadores (bitácoras PDF a pedido)

Guarda los PDF en **Documents/Datacora** del teléfono (o cualquier carpeta llamada datacora) (el bot la encuentra sola; en Termux corre
una vez `termux-setup-storage`). Nombre: `Nemesio Antunez 30-09-2026.pdf` o el que trae Datácora (con RBD;
la fecha se lee del PDF). En el grupo: "necesito el verificador del Nemesio Antúnez" → el bot lista las fechas
numeradas → "la 2" → manda ese PDF. Si hay una sola, la manda de una. `!verificadores` muestra qué encontró.

## Reglas de acción (sacadas del chat real del grupo)

| Lo que escriben | Lo que hace el bot |
|---|---|
| "cierra a las 4 hoy", "se puede entrar a las 14:00", "con extensión hasta las 5:30" | Anota el horario y te avisa si choca con una visita agendada |
| "no llegaron a limpiar la cámara", "vino el gasfiter y se fue sin avisar" | Disculpa corta, te alerta y deja el caso con prioridad para `!plan` |
| "recordar lo del Haití", "¿qué pasó con el gasfiter?", "para cuándo la visita" | Responde el estado real (quién va y cuándo, o que está sin hora) y sube la prioridad |
| "mañana recibe supervisión", "será objeto de auditoría", "hoy va Junaeb" | Prioriza lo pendiente de ese colegio y te avisa |
| Preguntas frecuentes (técnicos, horario, cómo pedir visita, fin de semana, qué nos corresponde…) | Responde con `respuestas.json`; las delicadas pasan por ti |

Cada día hábil a las 16:30 publica en el grupo a qué colegios se va el día siguiente, por supervisora.
`!situaciones` y `!faq` muestran las reglas; las preguntas se editan en `bot-ia/respuestas.json`.

## Planilla de Google (todo respaldado)

El bot sube a tu planilla el mismo paquete que el panel, con su agenda viva: Panel (metas/KPIs), Programa,
Movimientos (cada cambio de agenda y por qué), Correctivos, Establecimientos, Bitácoras, Datácora, Semanas,
Histórico, más **Cronograma** (4 semanas día × técnico × bloque), **Metas por establecimiento**,
Hallazgos WhatsApp, Conversaciones, Consultas a supervisoras y Mensajes del grupo. Sube sola cuando algo
cambia (revisa cada 10 min) y al menos cada hora. A mano: `!planilla`.

## Plan del día (07:15 y `!plan`)

Te llega hoy y mañana por técnico, bloque por bloque, y los **casos sin hora** numerados.
Respondes `1 hoy camilo b3, 2 mañana, 3 lunes, 4 no, 5 espera` → vista previa (se simula en una copia, nada cambia).
`ok plan` → se aplica, se avisa al grupo (citando el mensaje original, con la supervisora de cada colegio
movido) y a cada técnico (si `tecnicos_whatsapp` tiene su número; si no, te llega a ti para reenviar).
Lo que no nombres se agenda solo después de lo tuyo (salvo que escribas `solo esos`).

## Memoria: el bot aprende de ti

- Cada decisión tuya queda en la base y en tu planilla, hoja **Decisiones del encargado**.
- Cada día a las 18:15 busca patrones y te **propone reglas** ("en gas siempre pides fotos").
- Las reglas viven en la hoja **Reglas del bot**: puedes editarlas (columna Activa si/no) o crearlas con
  `!regla nueva preguntar falla:GAS ¿tienen fotos?` · tipos: `preguntar`, `tecnico`, `instruccion`.
- Antes de redactar, Gemini ve tus decisiones parecidas y tus reglas de estilo.
- Las bitácoras archivadas se copian a la hoja **Bitácoras del bot**.
- Seguridad: la primera vez que el bot escribe, la planilla guarda su clave (Propiedades del script → BOT_CLAVE).
  Si reinstalas el bot con otra clave, borra BOT_CLAVE en Apps Script y listo.

## Supervisoras

`!supervisora carla` → sus colegios, casos abiertos, próximas visitas, consultas sin responder.
`!supervisoras` → resumen de las tres. Cada borrador muestra la supervisora del colegio.

## Preguntas sobre trabajos hechos

"¿Qué se hizo el otro día en el Teresa Prat?" → responde como persona, agrupando por equipo
("se revisaron los equipos de frío y de calor, quedaron operativos") y **adjunta los PDF** de las bitácoras
archivadas que menciona. Si preguntan "¿por qué…?" explica con las observaciones de la bitácora.

## Conexión con el panel

Si pones un `github_token` en `config.json` (fine-grained, solo *Contents: Read and
write* sobre `Alechgon/bitacoras`), cada hallazgo se sube a `bot-datos.json` con el
mismo formato que ya lee tu panel. En la pestaña **WhatsApp**, toca *Probar si hay
datos del bot*. Además lleva la fecha, el técnico y el bloque que asignó el bot.

## Ojo con esto

- **Gemini gratis:** Google puede usar lo que le mandes para mejorar sus modelos. Al
  bot solo le llegan nombres de establecimientos y fallas, nunca RUT ni datos personales.
  Si SOSER lo pide, cambia la key por una de pago: el bot no cambia.
- **Límites del plan gratis:** si Gemini se satura, el bot sigue funcionando con
  palabras clave y alias (igual que tu panel). En el Excel queda registrado qué motor
  se usó en cada mensaje.
- **Baileys no es oficial:** usa un chip aparte. Con los delays y un solo grupo
  interno, el riesgo es bajo, pero existe.
- **La agenda del bot vive en `agenda.db` del celular.** El panel la ve a través de
  `bot-datos.json`. Si regeneras `datos.js`, el bot actualiza las visitas que no ha
  tocado y respeta las que movió.
