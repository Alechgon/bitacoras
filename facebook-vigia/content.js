// content.js — el "lector". Corre dentro de Facebook, en tu sesión, y SOLO MIRA.
//
// Dos modos (se lo pregunta al background al cargar):
//  - VIGÍA: la pestaña fija del vigía abrió un grupo (lo reciente o una búsqueda). Espera que cargue,
//    baja un poco la página como lo haría una persona, junta las publicaciones y avisa "listo".
//    Antes revisa si Facebook mostró login, verificación, bloqueo o "sin acceso" → el background se pausa solo.
//  - INICIO: estás navegando tú (inicio o grupos). Cada pocos segundos lee lo nuevo que aparece.
// Nunca comenta, nunca da like, nunca escribe.

(() => {
  if (window.__vigia2) return;
  window.__vigia2 = true;

  const SEL = '[role="article"], div[aria-posinset], div[data-pagelet^="FeedUnit"]';
  const dormir = (ms) => new Promise(r => setTimeout(r, ms));
  const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  const enviar = (m) => new Promise(res => { try { chrome.runtime.sendMessage(m, r => { void chrome.runtime.lastError; res(r); }); } catch { res(null); } });

  // ---------------------------------------------------------------- ¿qué página es?
  function textoDialogos() {
    return [...document.querySelectorAll('[role="dialog"], [role="alertdialog"], [role="alert"]')]
      .map(d => d.innerText || "").join("\n");
  }
  function estadoPagina(nPosts) {
    const p = location.pathname.toLowerCase();
    if (p.startsWith("/login") || p.includes("login.php") ||
        (document.querySelector('input[name="pass"]') && document.querySelector('input[name="email"]'))) return "login";
    if (p.includes("/checkpoint")) return "checkpoint";
    const dlg = norm(textoDialogos());
    const BLOQUEO = /(bloquead[oa]s? temporalmente|temporarily blocked|uso indebido de esta funcion|misusing (this|a) feature|demasiado rapido|going too fast|no puedes usar esta funcion|you can.?t use this feature)/;
    if (BLOQUEO.test(dlg)) return "bloqueo";
    if (nPosts > 0) return "ok";
    const txt = norm((document.body?.innerText || "").slice(0, 6000));
    if (/(confirma tu identidad|confirm your identity|suspendimos tu cuenta|we suspended your account|tu cuenta esta bloqueada|your account (has been|is) locked)/.test(txt)) return "checkpoint";
    if (BLOQUEO.test(txt)) return "bloqueo";
    if (/(este contenido no esta disponible|this content isn.?t available|contenido no disponible|esta pagina no esta disponible|this page isn.?t available|unete al grupo para ver|join (this )?group to see|este grupo es privado|this group is private)/.test(txt)) return "sin_acceso";
    if (/(no se encontraron resultados|no results found|no hay resultados|no encontramos resultados|we didn.?t find any results)/.test(txt)) return "sin_resultados";
    return "vacio";
  }

  // ---------------------------------------------------------------- sacar publicaciones
  function principales(sel) {
    return [...document.querySelectorAll(sel)].filter(el => !el.parentElement || !el.parentElement.closest(sel));   // fuera comentarios anidados
  }
  function articulosPrincipales() {
    const a = principales(SEL);
    return a.length ? a : principales('[role="feed"] > div');      // plan B si Facebook cambia las marcas
  }

  function limpiar(t) {
    let s = String(t || "").replace(/ /g, " ");
    s = s.split(/\n(?:Me gusta|Like|Me encanta|Todas las reacciones|All reactions)\b/)[0];
    s = s.replace(/\n(Comentar|Comment|Compartir|Share|Ver más|See more|Ver traducción|See translation|Responder|Reply)\b.*/gis, "");
    return s.replace(/\n{2,}/g, "\n").trim();
  }

  function textoDe(art) {
    const msg = art.querySelector('[data-ad-comet-preview="message"], [data-ad-preview="message"]');
    if (msg && msg.innerText.trim().length > 5) return limpiar(msg.innerText);
    const bloques = [...art.querySelectorAll('div[dir="auto"], span[dir="auto"]')]
      .map(x => (x.innerText || "").trim()).filter(t => t.length > 15);
    if (bloques.length) return limpiar(bloques.sort((a, b) => b.length - a.length)[0]);
    return limpiar(art.innerText);
  }

  function autorDe(art) {
    const a = art.querySelector('a[href*="/user/"], h2 a[href], h3 a[href], h4 a[href], strong a[href]');
    if (!a) return { autor: "", autor_url: "" };
    const nombre = (a.innerText || a.getAttribute("aria-label") || "").trim().split("\n")[0];
    return { autor: nombre.slice(0, 80), autor_url: abs(a.getAttribute("href")) };
  }

  function linkDe(art) {
    for (const a of art.querySelectorAll("a[href]")) {
      const h = a.getAttribute("href") || "";
      if (/\/groups\/[^/]+\/(posts|permalink)\/\d+|story_fbid=|\/posts\/[\w]+|\/permalink\.php/i.test(h)) {
        const u = abs(h);
        return u.includes("story_fbid") ? u.split("&__")[0] : u.split("?")[0];
      }
    }
    return "";
  }

  function abs(h) { if (!h) return ""; try { return new URL(h, location.origin).href; } catch { return h; } }

  // "2 h", "35 min", "3 d", "Ayer", "Justo ahora", "12 de octubre" → horas (o null si no se sabe)
  const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  function edadHoras(art, texto) {
    let cab = norm(art.innerText || "");
    const corte = texto ? cab.indexOf(norm(texto).slice(0, 25)) : -1;
    cab = (corte > 0 ? cab.slice(0, corte) : cab.slice(0, 220));
    let m;
    if (/\b(justo ahora|ahora mismo|just now|hace un momento)\b/.test(cab)) return 0;
    if ((m = cab.match(/\b(\d{1,2})\s*(min|mins|minutos?|m)\b/))) return +m[1] / 60;
    if ((m = cab.match(/\b(\d{1,2})\s*(h|hr|hrs|horas?)\b/))) return +m[1];
    if (/\b(ayer|yesterday)\b/.test(cab)) return 30;
    if ((m = cab.match(/\b(\d{1,2})\s*(d|dias?|days?)\b/))) return +m[1] * 24;
    if ((m = cab.match(/\b(\d{1,2})\s*(sem|semanas?|w|wk)\b/))) return +m[1] * 168;
    if ((m = cab.match(/\b(\d{1,2}) de (enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b/))) {
      const hoy = new Date();
      let f = new Date(hoy.getFullYear(), MESES.indexOf(m[2]), +m[1]);
      if (f > hoy) f = new Date(hoy.getFullYear() - 1, MESES.indexOf(m[2]), +m[1]);
      return Math.max(0, (hoy - f) / 3600000);
    }
    return null;
  }

  function huella(s) {           // id corto para publicaciones sin link
    let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) | 0;
    return "h" + (h >>> 0).toString(36);
  }

  function extraer() {
    const out = [];
    for (const art of articulosPrincipales()) {
      const texto = textoDe(art).slice(0, 1800);
      if (texto.length < 12) continue;
      const { autor, autor_url } = autorDe(art);
      const url = linkDe(art);
      const id = url || huella(autor + "|" + texto.slice(0, 140));
      out.push({ id, url, autor, autor_url, texto, edad_h: edadHoras(art, texto) });
    }
    return out;
  }

  // Facebook a veces deja el link de la publicación vacío hasta que pasas el mouse por la hora.
  // Se "pasa el mouse" (solo un evento, sin clic) para que lo complete.
  async function completarLinks() {
    let n = 0;
    for (const art of articulosPrincipales()) {
      if (linkDe(art)) continue;
      const cands = [...art.querySelectorAll('a[role="link"]')].filter(a => {
        const h = a.getAttribute("href");
        return !h || h === "#" || h.startsWith("#");
      }).slice(0, 3);
      for (const a of cands) {
        for (const ev of ["mouseover", "mouseenter", "focus"]) a.dispatchEvent(new Event(ev, { bubbles: true }));
        n++;
      }
    }
    if (n) await dormir(700);
  }

  // ---------------------------------------------------------------- modo vigía
  async function modoVigia() {
    const t0 = Date.now();
    const posts = new Map();
    let ultimoCambio = Date.now(), bajadas = 0;
    while (Date.now() - t0 < 22000) {
      await dormir(1500);
      const est = estadoPagina(posts.size);
      if (est === "login" || est === "checkpoint" || est === "bloqueo") return listo([], est);
      for (const p of extraer()) if (!posts.has(p.id)) { posts.set(p.id, p); ultimoCambio = Date.now(); }
      if (posts.size && Date.now() - ultimoCambio > (posts.size >= 3 ? 4500 : 9000)) break;
      // si después de unos segundos no aparece más, baja un poco (como quien lee)
      if (Date.now() - t0 > 5000 && bajadas < 3 && Date.now() - ultimoCambio > 2500) {
        const pasos = 3 + Math.floor(Math.random() * 3);              // de a poco, como la ruedita del mouse
        for (let i = 0; i < pasos; i++) { window.scrollBy(0, 160 + Math.random() * 140); await dormir(120 + Math.random() * 200); }
        bajadas++;
      }
      if (!posts.size && Date.now() - t0 > 12000) {
        const e2 = estadoPagina(0);
        if (e2 === "sin_acceso" || e2 === "sin_resultados") return listo([], e2);
      }
    }
    if (posts.size) {
      await completarLinks();
      for (const p of extraer()) if (posts.has(p.id) === false && p.url) {
        // la misma publicación ahora con link: reemplaza la versión sin link
        for (const [k, v] of posts) if (!v.url && v.texto === p.texto) { posts.delete(k); posts.set(p.id, p); }
      }
    }
    listo([...posts.values()].slice(0, 30), posts.size ? "ok" : estadoPagina(0));
  }

  function listo(lista, estado) {
    enviar({ tipo: "vigia_listo", posts: lista, pagina: {
      estado, url: location.href, titulo: document.title.slice(0, 80),
      visible: document.visibilityState, articulos: document.querySelectorAll(SEL).length } });
  }

  // ---------------------------------------------------------------- modo inicio (tú navegando)
  function rutaUtil() {
    const p = location.pathname;
    return p === "/" || p.startsWith("/groups") || p.startsWith("/home.php") || p.startsWith("/search");
  }
  function modoInicio() {
    const enviados = new Set();
    const barrer = () => {
      if (!rutaUtil()) return;
      const est = estadoPagina(1);
      if (est === "bloqueo" || est === "checkpoint") { enviar({ tipo: "alerta_pagina", estado: est, url: location.href }); return; }
      const nuevos = extraer().filter(p => !enviados.has(p.id));
      nuevos.forEach(p => enviados.add(p.id));
      if (nuevos.length) enviar({ tipo: "feed_posts", posts: nuevos, url: location.href });
    };
    setTimeout(barrer, 2500);
    setInterval(barrer, 6000);
  }

  // ---------------------------------------------------------------- modo importar (tu lista de grupos)
  // Se abre facebook.com/groups/joins/ a la vista; baja la página de a poco y junta los links de
  // tus grupos con su nombre. Va guardando a medida que encuentra (si cierras antes, queda lo que alcanzó).
  async function modoImportar() {
    const caja = document.createElement("div");
    caja.style.cssText = "position:fixed;z-index:2147483647;top:14px;right:14px;max-width:340px;background:#1877f2;color:#fff;" +
      "padding:12px 16px;border-radius:12px;font:600 14px/1.4 system-ui,Segoe UI,Arial,sans-serif;box-shadow:0 6px 20px rgba(0,0,0,.3)";
    (document.body || document.documentElement).appendChild(caja);
    const decir = (t) => { caja.textContent = t; };
    const RES = /^(joins|feed|discover|create|search|notifications|your_groups|joined|learning_content|membership|categories|requests|invites|pending|manage|admin)$/i;
    const GENERICO = /^(ver grupo|view group|visitar grupo|visit group|unirte|join|ver mas|see more|ver todo|see all|.*actividad.*|.*activity.*|.*miembros.*|.*members.*)$/i;
    const grupos = new Map();
    const juntar = () => {
      let nuevos = 0;
      for (const a of document.querySelectorAll('a[href*="/groups/"]')) {
        const m = (a.getAttribute("href") || "").match(/\/groups\/([^/?#]+)/);
        if (!m || RES.test(m[1])) continue;
        let id; try { id = decodeURIComponent(m[1]); } catch { id = m[1]; }
        const txt = (a.innerText || a.getAttribute("aria-label") || "").trim().split("\n")[0].trim();
        const nombre = txt && !GENERICO.test(norm(txt)) ? txt.slice(0, 80) : "";
        if (!grupos.has(id)) { grupos.set(id, nombre); nuevos++; }
        else if (nombre && nombre.length > (grupos.get(id) || "").length) grupos.set(id, nombre);
      }
      return nuevos;
    };
    const mandar = (fin) => enviar({ tipo: "grupos_import", fin, grupos: [...grupos].map(([id, nombre]) => ({ id, nombre })) });

    if (estadoPagina(1) === "login") { decir("⚡ Vigía: primero inicia sesión en Facebook y vuelve a tocar «Importar mis grupos»."); return mandar(true); }
    decir("⚡ Vigía: juntando tus grupos… deja esta pestaña a la vista");
    await dormir(2500);
    const t0 = Date.now();
    let quietos = 0, vueltas = 0;
    while (Date.now() - t0 < 300000) {
      if (document.visibilityState === "hidden") { decir("⚡ Vigía: vuelve a esta pestaña para que siga juntando tus grupos…"); await dormir(1500); continue; }
      const n = juntar();
      quietos = n ? 0 : quietos + 1;
      decir(`⚡ Vigía: ${grupos.size} grupos encontrados… bajando la página (no cierres esta pestaña)`);
      if (n || ++vueltas % 4 === 0) await mandar(false);
      const abajo = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 120;
      if (quietos >= (abajo ? 6 : 14)) break;
      window.scrollBy(0, Math.round(window.innerHeight * (0.7 + Math.random() * 0.25)));
      await dormir(1100 + Math.random() * 900);
    }
    juntar();
    await mandar(true);
    caja.style.background = "#16a34a";
    decir(`✅ Listo: ${grupos.size} grupos guardados en el vigía. Ya puedes cerrar esta pestaña.`);
  }

  // ---------------------------------------------------------------- arranque
  (async () => {
    let r = await enviar({ tipo: "quien_soy", url: location.href });
    if (!r?.vigia && /\/groups\/[^/]+\/(search|\?|$)|sorting_setting/.test(location.pathname + location.search)) {
      await dormir(2000);                                  // por si el vigía recién marcó esta pestaña
      r = await enviar({ tipo: "quien_soy", url: location.href });
    }
    if (r?.vigia) return modoVigia();
    if (r?.importar) return modoImportar();
    if (r?.inicio) return modoInicio();
    // por ahora nada: vuelve a preguntar cada minuto (por si activas el vigía después)
    const iv = setInterval(async () => {
      const r2 = await enviar({ tipo: "quien_soy", url: location.href });
      if (r2?.inicio) { clearInterval(iv); modoInicio(); }
    }, 60000);
  })();
})();
