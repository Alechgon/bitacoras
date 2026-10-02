# Respaldo en Google Apps Script

Recibe todo el estado desde la página, lo deja en una planilla de Google con ocho
hojas y publica un tablero que se abre desde cualquier parte, sin instalar nada.

La URL ya viene puesta en la página:
`https://script.google.com/macros/s/AKfycbx8mlrYEMlU0gXkvwInPM0tgFG3Oo6PQCU_YhupEhBLvX4vwP_JYngAZG8Kwfwf7pPw/exec`

## Pegar el código

1. Abre tu proyecto en [script.google.com](https://script.google.com).
2. Reemplaza todo el contenido del archivo por el de **`Codigo.gs`**.
3. Guarda.
4. **Implementar → Administrar implementaciones →** lápiz → Versión: **Nueva versión** → Implementar.

Ese último paso es el que más se olvida: mientras no crees una versión nueva, el
`/exec` sigue entregando el código viejo.

La implementación tiene que quedar así:

| Campo | Valor |
|---|---|
| Ejecutar como | **Yo** |
| Quién tiene acceso | **Cualquier usuario** |

Lo segundo es obligatorio: si queda en "Solo yo", la página no puede escribir
porque el navegador no manda tu sesión de Google.

La primera vez Google pide autorizar el acceso a Drive y Sheets. Va a aparecer
*"Google no verificó la aplicación"* — es tu propio script, entra por
**Configuración avanzada → Ir a (nombre del proyecto)**.

## Usarlo

En la página, pestaña **Ajustes → Respaldo en Google**:

- **Probar conexión** — verifica que el `/exec` responde antes de mandar nada.
- **Respaldar en Google** — sube todo. Devuelve cuántas filas quedaron.
- **Abrir el tablero** — abre el `/exec` en otra pestaña.
- **Respaldar solo al cerrar el día** — cada vez que cierres el día, sube solo.

La planilla se crea sola en tu Drive con el primer respaldo, llamada
**SOSER San Pablo · Respaldo**. El enlace sale en el tablero y en la respuesta.

## Lo que queda en la planilla

| Hoja | Qué trae |
|---|---|
| Resumen | Avance de las dos metas, conteos y fecha del último respaldo |
| Programa | Cada visita: fecha, bloque, técnico, establecimiento, estado, folio, trabajo |
| Establecimientos | Los 93 con dirección, gas, raciones, puntaje y estado de preventiva |
| Correctivos | Lo que piden las supervisoras, con días abiertos y fecha agendada |
| Bitácoras detalle | Un ítem por fila: categoría, cantidad, acción y observación |
| Datácora | El export, marcando cuáles cuentan para el conteo |
| Aplazamientos | Qué se movió, cuántas veces y por qué |
| Reportes supervisoras | Las menciones del grupo de WhatsApp |

## Direcciones útiles

| Para qué | URL |
|---|---|
| Tablero | `/exec` |
| Todo el estado en JSON | `/exec?modo=json` |
| Solo los KPI | `/exec?modo=resumen` |
| Ver si está vivo | `/exec?modo=ping` |

El `?modo=resumen` sirve para enganchar el bot de WhatsApp o lo que quieras:
devuelve el avance de las dos metas y cuántos correctivos hay abiertos.

## Si algo falla

| Qué dice | Qué pasa |
|---|---|
| `respuesta inesperada: <!DOCTYPE html...` | La implementación quedó en "Solo yo", o falta autorizar el script |
| `la URL no parece un Apps Script publicado` | Falta el `/exec` al final |
| `Failed to fetch` | La URL está mal, o no hay internet |
| Respalda pero el tablero se ve viejo | Falta crear una **versión nueva** de la implementación |

## Un par de cosas que conviene saber

El respaldo **pisa** lo anterior: siempre queda la última foto, no un historial.
Si quieres guardar un corte de un día, duplica la planilla a mano.

El tablero es **de solo lectura**. Lo que se edita sigue siendo la página; esto es
para mirar desde el teléfono, mandarle el link a alguien o revisar sin abrir nada.

El JSON completo queda en un archivo de tu Drive (`soser-estado.json`). Si lo
borras, el siguiente respaldo lo crea de nuevo.
