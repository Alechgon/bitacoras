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

- **Respaldar en Google** — sube todo. Devuelve las filas y el avance de las dos metas.
- **Traer de Google** — lo inverso: recupera lo respaldado. Para cuando cambias de equipo.
- **Abrir el tablero** — abre el `/exec` en otra pestaña.
- **Probar conexión** — verifica que el `/exec` responde antes de mandar nada.
- **Respaldar solo al cerrar el día** — cada vez que cierres el día, sube solo.

La planilla se crea sola en tu Drive con el primer respaldo, llamada
**SOSER San Pablo · Respaldo**. El enlace sale en el tablero y en la respuesta.

## Lo que queda en la planilla

Nueve hojas, con cabecera fija, filtros, bandas y formato condicional.

| Hoja | Qué trae |
|---|---|
| Panel | Las dos metas con su plazo, ritmo exigido y % · ritmo real, cumplimiento y requerimientos por criticidad y supervisora |
| Histórico | **Una fila por respaldo**, acumulativa. De aquí sale la tendencia y las chispas del tablero |
| Programa | Cada visita: fecha, bloque, técnico, establecimiento, estado, folio, trabajo |
| Establecimientos | Los 93 con dirección, gas, raciones, puntaje con escala de color y estado de preventiva |
| Correctivos | Lo que piden las supervisoras; los que pasan 10 días salen en rojo |
| Bitácoras | Un ítem revisado por fila: categoría, cantidad, acción y observación |
| Datácora | El export, marcando cuáles cuentan para el conteo |
| Movimientos | Qué se aplazó, cuántas veces y por qué; dos o más sale en rojo |
| Reportes supervisoras | Las menciones del grupo de WhatsApp |

El **Histórico** es la única hoja que no se reescribe: cada respaldo agrega una fila
con el avance de las dos metas, el ritmo y el cumplimiento de ese momento.

## Direcciones útiles

| Para qué | URL |
|---|---|
| Tablero | `/exec` |
| Todo el estado en JSON | `/exec?modo=json` |
| Los indicadores calculados | `/exec?modo=kpi` |
| El histórico de respaldos | `/exec?modo=historico` |
| Ver si está vivo | `/exec?modo=ping` |

El `?modo=kpi` sirve para enganchar el bot de WhatsApp o lo que quieras: devuelve el
avance de las dos metas, el ritmo exigido contra el real, el cumplimiento y los
requerimientos por criticidad y por supervisora.

## Si algo falla

| Qué dice | Qué pasa |
|---|---|
| `respuesta inesperada: <!DOCTYPE html...` | La implementación quedó en "Solo yo", o falta autorizar el script |
| `la URL no parece un Apps Script publicado` | Falta el `/exec` al final |
| `Failed to fetch` | La URL está mal, o no hay internet |
| Respalda pero el tablero se ve viejo | Falta crear una **versión nueva** de la implementación |

## Un par de cosas que conviene saber

Las hojas de datos **se reescriben** en cada respaldo: siempre queda la última foto.
La excepción es **Histórico**, que acumula una fila por respaldo — ahí está la tendencia.

El tablero es **de solo lectura**. Lo que se edita sigue siendo la página; esto es
para mirar desde el teléfono, mandarle el link a alguien o revisar sin abrir nada.

El JSON completo queda en un archivo de tu Drive (`soser-estado.json`). Si lo
borras, el siguiente respaldo lo crea de nuevo.
