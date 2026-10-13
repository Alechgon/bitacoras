# Vigía de pegas — Facebook

Extensión de Chrome que revisa tus grupos de Facebook buscando a quien **pide** trabajos de
electricidad o gasfitería, lo clasifica con IA (Gemini), y te arma una **lista de solicitudes** con
el mensaje listo para que **tú** le escribas. También lee el inicio/los grupos mientras navegas.

> **Importante (léelo).** Facebook no permite robots que comenten o manden mensajes solos: eso te
> banea la cuenta (la misma donde tienes los 400 grupos). Por eso esta herramienta **no comenta ni
> escribe nada**: solo mira lo que ya está en pantalla y te avisa. Tú respondes a mano, personalizado.
> Igual, para que Facebook te vea como persona, va **lento** (configurable). No lo pongas a mil.

---

## 1) Instalar (una vez)

1. En el PC (donde tienes Chrome con tu Facebook iniciado), descarga/clona esta carpeta
   `facebook-vigia/` (está en tu repo `github.com/alechgon/bitacoras`).
2. Abre Chrome y entra a `chrome://extensions`.
3. Arriba a la derecha, activa **Modo de desarrollador**.
4. Botón **Cargar descomprimida** → elige la carpeta `facebook-vigia`.
5. Aparece "⚡ Vigía de pegas". Fija el ícono en la barra (el puzzle → chincheta).
6. Haz clic en el ícono → se abre el **panel**.

## 2) Configurar (pestaña Configuración)

- **Llave de Gemini**: la misma de tu bot de SOSER (la `AQ.…`). Pégala y toca **Probar** (debe decir ✓).
- **Tu nombre, fono, qué ofreces, zona**: con esto la IA te redacta el mensaje más personal.
- **Minutos entre cada búsqueda**: por defecto 4. Más alto = más seguro. Déjalo en 4–6.
- **Horario**: a qué horas puede andar buscando (ej. 08:00 a 23:00).
- Deja marcado **Leer el inicio mientras navego** (eso es gratis y sin riesgo) y
  **Hacer búsquedas automáticas** (eso es lo que recorre los grupos).
- Guarda.

## 3) Cargar tus grupos (pestaña Grupos)

Pega los links de tus grupos, uno por línea. Opcional ponerle nombre con una barra:

```
https://www.facebook.com/groups/123456789 | Pegas y servicios Santiago
https://www.facebook.com/groups/mielectricidadcl
```

### Sacar los 400 de una
1. En Chrome, entra a **https://www.facebook.com/groups/joins/** (tus grupos).
2. Baja hasta que carguen todos (sigue bajando, Facebook los muestra de a poco).
3. Abre la consola: tecla **F12** → pestaña **Console**.
4. Pega esto y Enter; te copia la lista al portapapeles:

```js
copy([...document.querySelectorAll('a[href*="/groups/"]')]
  .map(a => a.href.match(/facebook\.com\/groups\/[^/?#]+/))
  .filter(Boolean).map(m => 'https://www.' + m[0])
  .filter((v,i,x) => x.indexOf(v) === i).join('\n'));
```

5. Vuelve al panel → pestaña **Grupos** → pega (Ctrl+V) → **Guardar grupos**.

## 4) Usar (pestaña Actividad y Solicitudes)

- Toca **Activar** (arriba). De ahí en adelante, con Chrome abierto, el vigía va recorriendo.
- **Pestaña Actividad**: te muestra EN VIVO qué está haciendo (buscando una palabra en tal grupo, o
  mirando el inicio), la **cuenta regresiva** para la próxima búsqueda, cuántas publicaciones lleva
  vistas, cuántas pegas encontró, la **bitácora** de todo con la hora, y las últimas publicaciones que
  miró (aunque no fueran pega). Así ves que está vivo aunque entre búsqueda y búsqueda espere un rato.
- **Pestaña Solicitudes**: cuando encuentra a alguien pidiendo, te llega una **notificación** y aparece
  la tarjeta con el post, de qué se trata, comuna y urgencia, y el **mensaje sugerido** (editable), con
  botones **Abrir post**, **Copiar mensaje**, **Contactado**, **Descartar**.
- El contador rojo en el ícono = cuántas nuevas tienes sin ver.

> Entre cada búsqueda espera unos **2 minutos** (configurable). Es a propósito, para que Facebook te vea
> como persona y no te bloquee. En la pestaña Actividad ves la cuenta regresiva, así sabes que sigue andando.

## 5) Palabras (pestaña Palabras)

- Las palabras que busca, una a una, en cada grupo. Agrega/quita las que quieras.
- **Aprendidas**: cuando la IA ve que una frase se repite en solicitudes reales (ej. "me quedó sin luz"),
  te la propone acá; tú la **Activas** y desde ahí también la busca. Así va mejorando sola.

---

## Cómo funciona por dentro (resumen técnico)

- `content.js` lee los `[role="article"]` (los posts) de la página de búsqueda del grupo y del feed,
  saca autor + texto + link, y se los manda al `background.js`. No hace clics.
- `background.js` lleva el ritmo: cada X minutos entra a
  `facebook.com/groups/<id>/search/?q=<palabra>` de un grupo, lee, cierra, y avanza a la siguiente
  palabra/grupo. Deduplica por link, clasifica con `gemini.js`, guarda la solicitud y te avisa.
- `gemini.js` decide si es una solicitud real, de qué tipo, y redacta el mensaje.
- Todo se guarda en el navegador (storage de la extensión). Nada sale a ningún servidor tuyo, salvo
  que pongas un *webhook* opcional (para avisar a tu WhatsApp más adelante).

## Avisos

- Solo corre con **Chrome abierto** y tu Facebook con sesión. Si cierras Chrome, se pausa.
- Los selectores de Facebook cambian de vez en cuando; si algún día deja de pescar posts, avísame y
  ajusto `content.js`.
- Mientras más grupos y más palabras, más lento el barrido completo (es a propósito). Con 4 min entre
  búsquedas, una vuelta a 400 grupos toma varios días; va rotando y avisando a medida que encuentra.
