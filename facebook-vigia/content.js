// content.js — el "lector". Corre dentro de Facebook, en tu sesión, y SOLO MIRA.
//
// Modos (se lo pregunta al background al cargar la página):
//  - VIGÍA: la ventana/pestaña del vigía está en un paso del plan (inicio del grupo, una búsqueda o el
//    inicio de Facebook). Se queda el tiempo que le digas, bajando de a poco como quien lee, junta las
//    publicaciones (autor, texto, link, fecha) y las va mandando. Si Facebook muestra login,
//    verificación o bloqueo, avisa al tiro y el vigía se pausa.
//  - INICIO: estás navegando tú. Cada pocos segundos lee lo nuevo que aparece.
//  - IMPORTAR: recorre tu lista de grupos y los manda al vigía.
// Nunca comenta, nunca da like, nunca escribe, nunca hace clic.

(() => {
  if (window.__vigia3) return;
  window.__vigia3 = true;

  const SEL = '[role="article"], div[aria-posinset], div[data-pagelet^="FeedUnit"]';
  const RES_G = /^(joins|feed|discover|create|search|notifications|your_groups|joined|learning_content|membership|categories|requests|invites|pending|manage|admin)$/i;
  const dormir = (ms) => new Promise(r => setTimeout(r, ms));
  const azar = (a, b) => a + Math.random() * (b - a);
  const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  const enviar = (m) => new Promise(res => { try { chrome.runtime.sendMessage(m, r => { void chrome.runtime.lastError; res(r); }); } catch { res(null); } });

  // ---------------------------------------------------------------- ¿qué página es?
  function textoDialogos() {
    return [...document.querySelectorAll('[role="dialog"], [role="alertdialog"], [role="alert"]')].map(d => d.innerText || "").join("\n");
  }
  const BLOQUEO = /(bloquead[oa]s? temporalmente|temporarily blocked|uso indebido de esta funcion|misusing (this|a) feature|demasiado rapido|going too fast|no puedes usar esta funcion|you can.?t use this feature)/;
  function estadoPagina(nPosts) {
    const p = location.pathname.toLowerCase();
    if (p.startsWith("/login") || p.includes("login.php") ||
        (document.querySelector('input[name="pass"]') && document.querySelector('input[name="email"]'))) return "login";
    if (p.includes("/checkpoint")) return "checkpoint";
    if (BLOQUEO.test(norm(textoDialogos()))) return "bloqueo";
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
  const propio = (el, art) => { const c = el.closest(SEL); return !c || c === art; };   // que no sea de un comentario

  function limpiar(t) {
    let s = String(t || "").replace(/ /g, " ");
    s = s.split(/\n(?:Me gusta|Like|Me encanta|Todas las reacciones|All reactions)\b/)[0];
    s = s.replace(/\n(Comentar|Comment|Compartir|Share|Ver más|See more|Ver traducción|See translation|Responder|Reply)\b.*/gis, "");
    return s.replace(/\n{2,}/g, "\n").trim();
  }
  function textoDe(art) {
    const msg = art.querySelector('[data-ad-comet-preview="message"], [data-ad-preview="message"]');
    if (msg && msg.innerText.trim().length > 5) return limpiar(msg.innerText);
    const bloques = [...art.querySelectorAll('div[dir="auto"], span[dir="auto"]')].filter(x => propio(x, art))
      .map(x => (x.innerText || "").trim()).filter(t => t.length > 15);
    if (bloques.length) return limpiar(bloques.sort((a, b) => b.length - a.length)[0]);
    return limpiar(art.innerText);
  }
  function abs(h) { if (!h) return ""; try { return new URL(h, location.origin).href; } catch { return h; } }
  const esLinkPost = (h) => /\/groups\/[^/]+\/(posts|permalink)\/\d+|story_fbid=|\/posts\/[\w]+|\/permalink\.php/i.test(h || "");
  const esLinkGrupo = (h) => { const m = String(h || "").match(/\/groups\/([^/?#]+)\/?(?:[?#]|$)/); return m && !RES_G.test(m[1]) ? m[1] : null; };

  function autorDe(art) {
    let a = [...art.querySelectorAll('a[href*="/user/"]')].find(x => propio(x, art) && (x.innerText || "").trim());
    if (!a) a = [...art.querySelectorAll('h2 a[href], h3 a[href], h4 a[href], strong a[href]')].find(x => {
      const h = x.getAttribute("href") || "";
      return propio(x, art) && !esLinkPost(h) && !esLinkGrupo(h) && !/\/hashtag\//.test(h) && (x.innerText || "").trim().length > 1;
    });
    if (!a) return { autor: "", autor_url: "" };
    const nombre = (a.innerText || a.getAttribute("aria-label") || "").trim().split("\n")[0];
    let url = abs(a.getAttribute("href"));
    try { const u = new URL(url); url = u.pathname.includes("profile.php") && u.searchParams.get("id") ? `${u.origin}/profile.php?id=${u.searchParams.get("id")}` : url.split("?")[0]; } catch {}
    return { autor: nombre.slice(0, 80), autor_url: url };
  }
  function grupoDe(art) {                                   // en el inicio de Facebook: ¿de qué grupo viene?
    for (const a of art.querySelectorAll('a[href*="/groups/"]')) {
      const id = esLinkGrupo(a.getAttribute("href"));
      const t = (a.innerText || "").trim().split("\n")[0];
      if (id && t.length > 1 && propio(a, art)) return { grupo_id: id, grupo_nombre: t.slice(0, 80) };
    }
    return {};
  }
  function linkDe(art) {
    for (const a of art.querySelectorAll("a[href]")) {
      const h = a.getAttribute("href") || "";
      if (esLinkPost(h) && propio(a, art)) {
        const u = abs(h);
        return u.includes("story_fbid") ? u.split("&__")[0] : u.split("?")[0];
      }
    }
    return "";
  }

  // ---- fechas: "Justo ahora", "35 min", "2 h", "Ayer a las 14:30", "3 d", "2 sem", "12 de octubre a las 10:00",
  //      "martes a las 9:15", "12 de octubre de 2025" (y en inglés) → horas desde que se publicó
  const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  const MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
  const DIAS = ["domingo", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado"];
  const DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
  function parseEdad(raw) {
    const t = norm(raw).replace(/\s+/g, " ").trim();
    if (!t || t.length > 90) return null;
    const ahora = new Date();
    const hm = t.match(/(?:a las|at)\s+(\d{1,2})[:.](\d{2})\s*(am|pm|a\. ?m\.|p\. ?m\.)?/);
    const conHora = (d) => {
      if (hm) { let H = +hm[1]; const M = +hm[2]; const pm = /^p/.test(hm[3] || ""), am = /^a/.test(hm[3] || "");
        if (pm && H < 12) H += 12; if (am && H === 12) H = 0; d.setHours(H, M, 0, 0); }
      else d.setHours(12, 0, 0, 0);
      return d;
    };
    const horas = (d) => Math.max(0, (ahora - d) / 3.6e6);
    let m;
    if (/\b(justo ahora|ahora mismo|just now|hace un momento|recien)\b/.test(t)) return 0;
    if ((m = t.match(/\b(\d{1,2})\s*(min|mins|minutos?|m)\b/))) return +m[1] / 60;
    if ((m = t.match(/\b(\d{1,2})\s*(h|hr|hrs|horas?|hours?)\b/))) return +m[1];
    if (/\b(ayer|yesterday)\b/.test(t)) { const d = new Date(ahora); d.setDate(d.getDate() - 1); return horas(conHora(d)); }
    if ((m = t.match(/\b(\d{1,2})\s*(d|dias?|days?)\b/))) return +m[1] * 24;
    if ((m = t.match(/\b(\d{1,2})\s*(sem|semanas?|w|wk|wks|weeks?)\b/))) return +m[1] * 168;
    if ((m = t.match(/\b(\d{1,2})\s*(anos?|years?|yr|yrs)\b/))) return +m[1] * 8760;
    if ((m = t.match(new RegExp(`\\b(\\d{1,2}) de (${MESES.join("|")})(?: de (\\d{4}))?`))) || (m = t.match(new RegExp(`\\b(${MONTHS.join("|")}) (\\d{1,2})(?:,? (\\d{4}))?`)))) {
      const esIng = MONTHS.includes(m[1]);
      const dia = +(esIng ? m[2] : m[1]), mes = esIng ? MONTHS.indexOf(m[1]) : MESES.indexOf(m[2]);
      const y = m[3] ? +m[3] : ahora.getFullYear();
      const d = conHora(new Date(y, mes, dia));
      if (!m[3] && d > ahora) d.setFullYear(y - 1);
      return horas(d);
    }
    if ((m = t.match(new RegExp(`\\b(${DIAS.join("|")}|${DAYS.join("|")})\\b`)))) {
      const i = DIAS.includes(m[1]) ? DIAS.indexOf(m[1]) : DAYS.indexOf(m[1]);
      const d = new Date(ahora); d.setDate(d.getDate() - (((ahora.getDay() - i) + 7) % 7 || 7));
      return horas(conHora(d));
    }
    return null;
  }
  function edadDe(art, texto) {
    const cands = [];
    for (const el of art.querySelectorAll("a[href], abbr, [aria-label], [title]")) {
      if (!propio(el, art)) continue;
      const h = el.getAttribute("href") || "";
      const txt = (el.innerText || "").trim();
      if (esLinkPost(h)) cands.push(el.getAttribute("aria-label") || "", txt);
      else if (el.tagName === "ABBR" || el.hasAttribute("title")) cands.push(el.getAttribute("title") || "", txt);
      else if (el.getAttribute("aria-label") && el.getAttribute("aria-label").length < 60) cands.push(el.getAttribute("aria-label"));
    }
    for (const c of cands) { if (!c || c.length > 60) continue; const e = parseEdad(c); if (e != null) return { edad_h: e, fecha_txt: c.slice(0, 40) }; }
    // cabecera del post (lo que va antes del texto)
    let cab = art.innerText || "";
    const corte = texto ? norm(cab).indexOf(norm(texto).slice(0, 25)) : -1;
    cab = corte > 0 ? cab.slice(0, corte) : cab.slice(0, 220);
    for (const linea of cab.split(/\n|·/).map(x => x.trim()).filter(Boolean)) {
      const e = parseEdad(linea);
      if (e != null) return { edad_h: e, fecha_txt: linea.slice(0, 40) };
    }
    return { edad_h: null, fecha_txt: "" };
  }

  function huella(s) {           // id corto para publicaciones sin link
    let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) | 0;
    return "h" + (h >>> 0).toString(36);
  }
  const claves = new WeakMap(); let nClave = 0;               // id por elemento (sin tocar la página)
  function extraer() {
    const out = [];
    for (const art of articulosPrincipales()) {
      const texto = textoDe(art).slice(0, 1800);
      if (texto.length < 12) continue;
      if (!claves.has(art)) claves.set(art, ++nClave);
      const { autor, autor_url } = autorDe(art);
      const url = linkDe(art);
      out.push({ k: claves.get(art), id: url || huella(autor + "|" + texto.slice(0, 140)), url, autor, autor_url, texto,
                 ...edadDe(art, texto), ...grupoDe(art) });
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
        return propio(a, art) && (!h || h === "#" || h.startsWith("#"));
      }).slice(0, 3);
      for (const a of cands) { for (const ev of ["mouseover", "mouseenter", "focus"]) a.dispatchEvent(new Event(ev, { bubbles: true })); n++; }
    }
    if (n) await dormir(600);
  }

  // ---------------------------------------------------------------- modo vigía (un paso del plan)
  // Se queda "dur" ms leyendo: baja de a poco, a veces sube un poco, hace pausas como quien lee.
  // Termina al cumplir el tiempo, o si ya juntó las publicaciones pedidas y pasó la mitad del tiempo,
  // o si no aparece nada más. Va mandando lo que encuentra cada pocos segundos.
  async function modoVigia(paso) {
    const dur = Math.max(8000, paso?.dur || 60000);
    const objetivo = Math.max(1, paso?.objetivo || 10);
    const t0 = Date.now();
    const posts = new Map();                 // k → post (se actualiza: el link puede aparecer después)
    const enviados = new Set();
    let ultimoNuevo = Date.now(), ultimoEnvio = Date.now(), ocultoMs = 0, bajadas = 0;

    const mandar = async (todo) => {
      const listos = [...posts.values()].filter(p => !enviados.has(p.k) && (todo || p._vueltas >= 1));
      if (!listos.length) return;
      listos.forEach(p => enviados.add(p.k));
      ultimoEnvio = Date.now();
      await enviar({ tipo: "vigia_parcial", pid: paso?.id, posts: listos.map(({ _vueltas, ...p }) => p), total: posts.size, visible: document.visibilityState });
    };
    const fin = async (estado) => {
      await mandar(true);
      await enviar({ tipo: "vigia_listo", pid: paso?.id, posts: [], pagina: {
        estado, url: location.href, titulo: document.title.slice(0, 80), visible: document.visibilityState,
        oculto: ocultoMs > (Date.now() - t0) * 0.6, total: posts.size, seg: Math.round((Date.now() - t0) / 1000),
        articulos: document.querySelectorAll(SEL).length } });
    };

    while (true) {
      const espera = azar(1800, 4200);                     // "leyendo"
      await dormir(espera);
      if (document.visibilityState === "hidden") ocultoMs += espera;
      const el = Date.now() - t0;
      const est = estadoPagina(posts.size);
      if (est === "login" || est === "checkpoint" || est === "bloqueo") return fin(est);
      for (const p of posts.values()) p._vueltas = (p._vueltas || 0) + 1;
      for (const p of extraer()) {
        const ya = posts.get(p.k);
        if (!ya) { posts.set(p.k, { ...p, _vueltas: 0 }); ultimoNuevo = Date.now(); }
        else if (!enviados.has(p.k)) posts.set(p.k, { ...ya, ...p, url: p.url || ya.url, _vueltas: ya._vueltas });
      }
      await completarLinks();
      if (Date.now() - ultimoEnvio > 7000 || [...posts.values()].filter(p => !enviados.has(p.k)).length >= 6) await mandar(false);
      if (!posts.size && el > 12000) {
        const e2 = estadoPagina(0);
        if (e2 === "sin_acceso" || e2 === "sin_resultados") return fin(e2);
      }
      const quieto = Date.now() - ultimoNuevo;
      if (el >= dur) break;
      if (posts.size >= objetivo && el >= dur * 0.5) break;
      if (quieto > 30000 && el > 25000) break;             // no carga nada más
      // bajar como persona: unos tirones de ruedita; de vez en cuando sube un poquito
      if (Math.random() < 0.1 && bajadas > 2) window.scrollBy(0, -Math.round(azar(120, 320)));
      else {
        const n = 2 + Math.floor(Math.random() * 3);
        for (let i = 0; i < n; i++) { window.scrollBy(0, Math.round(azar(110, 260))); await dormir(azar(90, 260)); }
      }
      bajadas++;
    }
    await completarLinks();
    for (const p of extraer()) { const ya = posts.get(p.k); if (ya && !enviados.has(p.k)) posts.set(p.k, { ...ya, ...p, url: p.url || ya.url }); }
    return fin(posts.size ? "ok" : estadoPagina(0));
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
      if (nuevos.length) enviar({ tipo: "feed_posts", posts: nuevos.map(({ k, ...p }) => p), url: location.href });
    };
    setTimeout(barrer, 2500);
    setInterval(barrer, 6000);
  }

  // ---------------------------------------------------------------- modo importar (tu lista de grupos)
  async function modoImportar() {
    const caja = document.createElement("div");
    caja.style.cssText = "position:fixed;z-index:2147483647;top:14px;right:14px;max-width:340px;background:#1877f2;color:#fff;" +
      "padding:12px 16px;border-radius:12px;font:600 14px/1.4 system-ui,Segoe UI,Arial,sans-serif;box-shadow:0 6px 20px rgba(0,0,0,.3)";
    (document.body || document.documentElement).appendChild(caja);
    const decir = (t) => { caja.textContent = t; };
    const GENERICO = /^(ver grupo|view group|visitar grupo|visit group|unirte|join|ver mas|see more|ver todo|see all|.*actividad.*|.*activity.*|.*miembros.*|.*members.*)$/i;
    const grupos = new Map();
    const juntar = () => {
      let nuevos = 0;
      for (const a of document.querySelectorAll('a[href*="/groups/"]')) {
        const m = (a.getAttribute("href") || "").match(/\/groups\/([^/?#]+)/);
        if (!m || RES_G.test(m[1])) continue;
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
    if (!r?.vigia && !r?.importar && /\/groups\/|facebook\.com\/?(\?|#|$)|sorting_setting/.test(location.href)) {
      await dormir(2000);                                  // por si el vigía recién marcó esta pestaña
      r = await enviar({ tipo: "quien_soy", url: location.href });
    }
    if (r?.vigia) return modoVigia(r.paso);
    if (r?.importar) return modoImportar();
    if (r?.inicio) return modoInicio();
    const iv = setInterval(async () => {                    // por si activas el vigía después
      const r2 = await enviar({ tipo: "quien_soy", url: location.href });
      if (r2?.inicio) { clearInterval(iv); modoInicio(); }
    }, 60000);
  })();

})();
