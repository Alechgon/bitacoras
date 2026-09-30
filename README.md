# SOSER · Sucursal San Pablo — Mantención PAE

Panel de mantención para la sucursal San Pablo (licitación 85-34-LR25).
Página estática: no necesita servidor, build ni dependencias. Se abre sola en GitHub Pages.

## Subirlo a GitHub

1. Crea un repo (por ejemplo `soser-mantencion`).
2. Sube **`index.html`**, **`datos.js`** y este README a la raíz.
3. Settings → Pages → Source: `Deploy from a branch`, rama `main`, carpeta `/ (root)`.
4. A los dos minutos queda en `https://alechgon.github.io/soser-mantencion/`.

Para probarlo en el computador antes de subirlo, no basta con abrir el archivo:
`datos.js` no carga con `file://`. Levanta un servidor local:

```bash
python3 -m http.server 8000
# y abre http://localhost:8000
```

## Qué hay adentro

| Pestaña | Para qué |
|---|---|
| **Hoy** | Tablero del día por técnico y bloque. Arrastra tarjetas, marca lo hecho, suma emergencias sin límite y cierra el día postergando lo que no se ejecutó. |
| **Semana** | Los cinco días en paralelo. Sirve para acoplar varios trabajos del mismo sector en un día. |
| **Cronograma** | Carta Gantt de los 93 sitios × 12 semanas, con el avance de las dos metas. |
| **Establecimientos** | Los 93 con buscador, filtros y ficha completa: puntaje desglosado, historial, bitácoras y lo que dijeron las supervisoras. |
| **Bitácoras** | Carga el PDF, lo lee, te deja corregir y lo suma al cronograma en su fecha. |
| **Buscador** | Buscador central de trabajos realizados, con filtro por categoría de la bitácora. |
| **Pendientes** | Los correctivos abiertos ordenados por criticidad. |
| **Ajustes** | Respaldo, avisos y registro de aplazamientos. |

## Las dos reglas del plan

1. **La totalidad de JUNAEB cargada en Datácora al 30 de octubre.** Es la regla número uno: los 60 establecimientos quedan agendados entre el 30 de septiembre y el 23 de octubre.
2. **Todos los jardines JUNJI e INTEGRA con preventivo al 15 de diciembre.** Los 33 corren del 2 al 24 de noviembre.

Los correctivos reportados por las supervisoras no compiten con esas metas: cuando el
establecimiento ya está agendado, se cierran en la misma visita (tarjetas marcadas
*PREV + CORRECTIVO*). Los 11 de jardines van aparte, en el bloque 3 de octubre.

## Puntaje de criticidad (1 a 20)

Calculado, no puesto a dedo:

| Factor | Puntos |
|---|---|
| Sin ninguna visita desde el 01-07-2026 | +6 |
| Además, sin visita en todo 2026 | +2 |
| Con visita pero sin preventiva certificada | +2 |
| Falla abierta de gas (fuga u olor) | +6 |
| Falla de frío o de agua/calefont | +4 |
| Falla eléctrica | +3 |
| Falla de equipo | +2 |
| Otra falla | +1 |
| Antigüedad de la falla | +1 cada 15 días, tope +3 |
| Prioridad declarada por jefatura | +2 |
| 800 raciones o más / entre 400 y 799 | +2 / +1 |
| Jardín infantil o sala cuna | +2 |
| Gas granel o cilindro 45K | +1 |
| Cada vez que el trabajo se aplaza | +1 |

## Regla de aplazamiento

Un trabajo se puede aplazar **una vez** sin autorización. El segundo aplazamiento lo
autoriza el encargado y queda en el registro de Ajustes con su motivo. Cada aplazamiento
suma un punto, así el trabajo se empuja solo hacia arriba en la cola.
**Una falla con olor o fuga de gas no se aplaza nunca.**

## Dónde se guardan los cambios

En el `localStorage` del navegador: quedan en ese equipo. Para que queden en el repo,
usa **Ajustes → Exportar respaldo** y sube el `.json`. El botón *Volver al plan original*
borra los cambios locales y recarga `datos.js`.

Si más adelante se quiere sincronización entre equipos, el paso siguiente es Supabase
(el mismo backend de Datácora), sin rehacer la página.

## Avisos

Los horarios son 08:00, 11:00, 14:00 y 16:50. Las notificaciones del navegador solo
funcionan con la pestaña abierta; en el celular Android el sistema las corta. Para que
lleguen con la página cerrada hay que conectarlo al bot de Telegram.

## Regenerar los datos

`datos.js` sale de los scripts de Python a partir de `BBDD_RBD_San_Pablo.xlsx`,
`Registro_Unificado_SOSER.xlsx`, las capturas de Datácora y el export del grupo de
WhatsApp. Si cambian los pesos del puntaje o entra un lote nuevo de bitácoras, se
regenera el archivo completo y se reemplaza.

## Estructura de la bitácora

Seis categorías, 44 ítems, cada uno con ubicación (cocina, bodega, baño, patio, otro),
cantidad, acción y observación:

- **Calor** (8) · cocina 4 platos, calefont, flexibles y conexiones de gas, horno, cocinilla, baño maría, fogón o anafe, caseta de gas
- **Electricidad** (7) · balanza y equipos de frío, extractor, interruptor, enchufes, toma corriente, cajas de distribución, luminarias
- **Frío** (5) · refrigerador, salad bar, frigobar, congelador, visicooler
- **Vectores** (3) · mallas mosquiteras, puertas-ventanas, vidrios
- **Agua** (5) · grifería, filtraciones, evacuación, cámara desgrasadora, sifón
- **Infraestructura** (16) · mesones, muebles, estantería, lavafondos, ducto de ventilación, extintor, campana, dispensador, botiquín, anclajes, señalética, carro, basureros, pintura
