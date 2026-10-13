// content.js — el "lector". Corre dentro de Facebook (en tu sesión) y saca los posts que se ven:
//  - En una página de BÚSQUEDA de grupo (la que abre el vigía), lee los resultados y los manda.
//  - En el INICIO o dentro de un grupo mientras TÚ navegas, lee lo que va apareciendo (riesgo cero).
// No hace clic en nada ni escribe: solo mira el texto que ya está en pantalla.

(() => {
  if (window.__vigiaCargado) return;
  window.__vigiaCargado = true;

  const vistosEnPagina = new Set();
  const esBusqueda = () => /\/groups\/[^/]+\/search/i.test(location.pathname + location.search) || /\/search\//.test(location.pathname);

  // ------- sacar un post de un contenedor <article>
  function limpiarTexto(t) {
    let s = (t || "").replace(/ /g, " ");
    // corta la "cola" de Facebook (reacciones/comentarios) para quedarnos con el mensaje
    s = s.split(/\n(?:Me gusta|Like|Me encanta)\b/)[0];
    s = s.replace(/\n(Comentar|Comment|Compartir|Share|Ver más|See more|Ver traducci[oó]n|Responder|Reply)\b.*/gis, "");
    s = s.replace(/\n{2,}/g, "\n").trim();
    return s.slice(0, 1800);
  }

  function sacarPost(art) {
    const texto = limpiarTexto(art.innerText || "");
    if (texto.length < 12) return null;

    let autor = "", autor_url = "";
    // el autor suele ser el primer enlace a un perfil, arriba del post
    const perfil = art.querySelector('h2 a[href], h3 a[href], h4 a[href], a[href*="/user/"], strong a[href]');
    if (perfil) {
      autor = (perfil.innerText || "").trim().split("\n")[0];
      autor_url = abs(perfil.getAttribute("href"));
    }

    // permalink del post: el enlace que apunta a /posts/ /permalink/ o trae story_fbid
    let url = "";
    const anclas = art.querySelectorAll('a[href]');
    for (const a of anclas) {
      const h = a.getAttribute("href") || "";
      if (/\/posts\/|\/permalink\/|story_fbid=|\/groups\/[^/]+\/posts\//i.test(h)) { url = abs(h); break; }
    }
    if (!url) {                 // a veces el link del post es el de la hora (aria sobre un time)
      const t = art.querySelector('a[role="link"][href*="/groups/"]');
      if (t) url = abs(t.getAttribute("href"));
    }
    url = (url || "").split("?")[0];

    return { autor, autor_url, texto, url };
  }

  function abs(h) {
    if (!h) return "";
    try { return new URL(h, location.origin).href; } catch { return h; }
  }

  function barrer() {
    const arts = document.querySelectorAll('[role="article"]');
    const nuevos = [];
    for (const art of arts) {
      if (art.__vigia) continue;
      art.__vigia = true;
      const p = sacarPost(art);
      if (!p) continue;
      const clave = (p.url || (p.autor + "|" + p.texto.slice(0, 60)));
      if (vistosEnPagina.has(clave)) continue;
      vistosEnPagina.add(clave);
      nuevos.push(p);
    }
    if (nuevos.length) {
      try { chrome.runtime.sendMessage({ tipo: "posts", posts: nuevos }); } catch {}
    }
    return nuevos.length;
  }

  // ------- búsqueda: barrer un par de veces (deja renderizar) y listo; el background cierra el tab
  if (esBusqueda()) {
    setTimeout(barrer, 2500);
    setTimeout(barrer, 6000);
    setTimeout(() => { try { chrome.runtime.sendMessage({ tipo: "posts", posts: [] }); } catch {} }, 9000);
    return;
  }

  // ------- feed/grupo mientras navegas: barrer cada pocos segundos lo nuevo que aparezca
  let timer = null;
  function activarFeed() {
    chrome.storage.local.get("config", ({ config }) => {
      if (config && config.feed_activo === false) return;
      if (timer) return;
      barrer();
      timer = setInterval(barrer, 5000);
      // si cambia la URL (Facebook es SPA), limpiar lo visto para el nuevo contexto
      let ultima = location.href;
      setInterval(() => { if (location.href !== ultima) { ultima = location.href; vistosEnPagina.clear(); } }, 3000);
    });
  }
  activarFeed();
})();
