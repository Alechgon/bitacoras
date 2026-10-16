// content.js — el "lector". Corre dentro de Facebook, en tu sesión, y SOLO MIRA.
//
// Modos (se lo pregunta al background al cargar la página):
//  - VIGÍA: la ventana del vigía está en un paso del plan (inicio del grupo, una búsqueda o el inicio de
//    Facebook). Baja de a poco, como quien lee, hasta juntar las publicaciones pedidas (o hasta que no
//    haya más, o se acabe el tiempo máximo). De cada una saca autor, perfil, texto, link exacto y fecha.
//  - INICIO: estás navegando tú. Cada pocos segundos lee lo nuevo que aparece.
//  - IMPORTAR: recorre tu lista de grupos y los manda al vigía.
// Nunca comenta, nunca da like, nunca escribe, nunca hace clic.
//
// La fecha: Facebook la esconde a propósito (la dibuja con letras revueltas). Se busca de 4 formas:
//   1) la hora exacta que Facebook trae escondida en los datos de la página,
//   2) leyendo solo las letras que de verdad se ven en pantalla (descifra lo revuelto),
//   3) pasando el puntero por la hora y leyendo el globito con la fecha completa,
//   4) el texto tal cual, como último recurso.

(() => {
  if (window.__vigia4) return;
  window.__vigia4 = true;

  const SEL = '[role="article"], div[aria-posinset], div[data-pagelet^="FeedUnit"]';
  const RES_G = /^(joins|feed|discover|create|search|notifications|your_groups|joined|learning_content|membership|categories|requests|invites|pending|manage|admin)$/i;
  const dormir = (ms) => new Promise(r => setTimeout(r, ms));
  const azar = (a, b) => a + Math.random() * (b - a);
  const rango = (r, def) => { const [a, b] = Array.isArray(r) ? r : def; return azar(+a || 0, Math.max(+a || 0, +b || 0)); };
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
  function nombreDelGrupo() {          // "(3) Pegas Ñuñoa | Facebook" → "Pegas Ñuñoa"
    if (!/^\/groups\/[^/]+/.test(location.pathname)) return "";
    const h1 = [...document.querySelectorAll('[role="main"] h1, h1')].map(x => (x.innerText || "").trim()).find(t => t.length > 1 && t.length < 100);
    const tit = document.title.replace(/^\(\d+\)\s*/, "").replace(/\s*[|·-]\s*Facebook\s*$/i, "").trim();
    const n = h1 || tit;
    return /^(facebook|buscar|search|resultados)/i.test(n) ? "" : n.slice(0, 80);
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
    s = s.replace(/\n(Comentar|Comment|Compartir|Share|Ver traducción|See translation|Responder|Reply)\b.*/gis, "");
    s = s.replace(/(…|\.\.\.)\s*(Ver más|See more)\s*$/i, "…");
    return s.replace(/\n{2,}/g, "\n").trim();
  }
  function textoDe(art) {
    const msg = [...art.querySelectorAll('[data-ad-rendering-role="story_message"], [data-ad-comet-preview="message"], [data-ad-preview="message"]')].find(x => propio(x, art));
    if (msg && msg.innerText.trim().length > 5) return limpiar(msg.innerText);
    const bloques = [...art.querySelectorAll('div[dir="auto"], span[dir="auto"]')].filter(x => propio(x, art))
      .map(x => (x.innerText || "").trim()).filter(t => t.length > 15);
    if (bloques.length) return limpiar(bloques.sort((a, b) => b.length - a.length)[0]);
    return limpiar(art.innerText);
  }
  function abs(h) { if (!h) return ""; try { return new URL(h, location.origin).href; } catch { return h; } }
  const esLinkPost = (h) => /\/groups\/[^/]+\/(posts|permalink)\/\d+|story_fbid=|multi_permalinks=|\/posts\/[\w]+|\/permalink\.php|[?&]post_id=\d+/i.test(h || "");
  const esLinkGrupo = (h) => { const m = String(h || "").match(/\/groups\/([^/?#]+)\/?(?:[?#]|$)/); return m && !RES_G.test(m[1]) ? m[1] : null; };
  const NO_NOMBRE = /^(ver mas|see more|seguir|follow|unirte|join|mas|more|\d+\s*(min|h|d)|publico|public)$/i;

  // link limpio a la publicación (nunca a la actividad de la persona en el grupo)
  function limpiarLinkPost(h, grupoId) {
    const u = abs(h);
    let m;
    if ((m = u.match(/\/groups\/([^/]+)\/(?:posts|permalink)\/(\d+)/))) return `https://www.facebook.com/groups/${m[1]}/posts/${m[2]}/`;
    if ((m = u.match(/multi_permalinks=(\d+)/)) && grupoId) return `https://www.facebook.com/groups/${grupoId}/posts/${m[1]}/`;
    if ((m = u.match(/[?&]post_id=(\d+)/)) && grupoId) return `https://www.facebook.com/groups/${grupoId}/posts/${m[1]}/`;
    if (u.includes("story_fbid")) return u.split("&__")[0];
    return u.split("?")[0];
  }
  function grupoDePagina() { const m = location.pathname.match(/^\/groups\/([^/?#]+)/); return m && !RES_G.test(m[1]) ? m[1] : ""; }

  function autorDe(art) {
    const cands = [
      ...art.querySelectorAll('[data-ad-rendering-role="profile_name"] a[href], [data-ad-rendering-role="profile_name"]'),
      ...art.querySelectorAll('a[href*="/user/"]'),
      ...art.querySelectorAll('h2 a[href], h3 a[href], h4 a[href], strong a[href], h2 span, h3 span, h4 span, strong span')
    ];
    for (const el of cands) {
      if (!propio(el, art)) continue;
      const a = el.tagName === "A" ? el : el.querySelector("a[href]") || el.closest("a[href]");
      const h = a?.getAttribute("href") || "";
      if (a && (esLinkPost(h) || esLinkGrupo(h) || /\/hashtag\//.test(h))) continue;
      const nombre = (el.innerText || a?.getAttribute("aria-label") || "").trim().split("\n")[0].trim();
      if (nombre.length < 2 || nombre.length > 80 || NO_NOMBRE.test(norm(nombre))) continue;
      return { autor: nombre, ...perfilDe(h) };
    }
    return { autor: "", autor_url: "", autor_id: "" };
  }
  // perfil de la persona: /groups/X/user/123 → facebook.com/profile.php?id=123 (su perfil, no su actividad en el grupo)
  function perfilDe(h) {
    if (!h) return { autor_url: "", autor_id: "" };
    let url = abs(h), m;
    if ((m = url.match(/\/user\/(\d+)/))) return { autor_url: `https://www.facebook.com/profile.php?id=${m[1]}`, autor_id: m[1] };
    try {
      const u = new URL(url);
      if (u.pathname.includes("profile.php") && u.searchParams.get("id")) return { autor_url: `https://www.facebook.com/profile.php?id=${u.searchParams.get("id")}`, autor_id: u.searchParams.get("id") };
      const v = u.pathname.match(/^\/([A-Za-z0-9.]{3,})\/?$/);
      if (v && !/^(groups|watch|marketplace|events|pages|people|reel|stories)$/i.test(v[1])) return { autor_url: `https://www.facebook.com/${v[1]}`, autor_id: v[1] };
    } catch {}
    return { autor_url: url.split("?")[0], autor_id: "" };
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
    const gid = grupoDePagina() || grupoDe(art).grupo_id || "";
    for (const a of art.querySelectorAll("a[href]")) {
      const h = a.getAttribute("href") || "";
      if (esLinkPost(h) && propio(a, art) && !/comment_id=/.test(h)) return limpiarLinkPost(h, gid);
    }
    for (const a of art.querySelectorAll("a[href]")) {           // el link de "comentarios" también lleva a la publicación
      const h = a.getAttribute("href") || "";
      if (esLinkPost(h) && propio(a, art)) return limpiarLinkPost(h, gid);
    }
    return "";
  }

  // ---------------------------------------------------------------- fechas
  const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  const MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
  const DIAS = ["domingo", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado"];
  const DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
  // texto → { ms: cuándo se publicó (hora de este PC), precision }
  function parseFecha(raw) {
    const t = norm(raw).replace(/\s+/g, " ").trim();
    if (!t || t.length > 90) return null;
    const ahora = new Date();
    const hm = t.match(/(?:a las|at|,)\s*(\d{1,2})[:.](\d{2})\s*(am|pm|a\. ?m\.|p\. ?m\.)?/);
    const conHora = (d) => {
      if (hm) { let H = +hm[1]; const M = +hm[2]; const pm = /^p/.test(hm[3] || ""), am = /^a/.test(hm[3] || "");
        if (pm && H < 12) H += 12; if (am && H === 12) H = 0; d.setHours(H, M, 0, 0); }
      else d.setHours(12, 0, 0, 0);
      return d;
    };
    const atras = (ms, precision) => ({ ms: ahora - ms, precision });
    let m;
    if (/\b(justo ahora|ahora mismo|just now|hace un momento|recien)\b/.test(t)) return atras(0, "min");
    if ((m = t.match(/\b(\d{1,2})\s*(min|mins|minutos?|m)\b/))) return atras(+m[1] * 60000, "min");
    if ((m = t.match(/\b(\d{1,2})\s*(h|hr|hrs|horas?|hours?)\b/))) return atras(+m[1] * 3600000, "h");
    if (/\b(ayer|yesterday)\b/.test(t)) { const d = new Date(ahora); d.setDate(d.getDate() - 1); return { ms: +conHora(d), precision: hm ? "exacta" : "d" }; }
    if ((m = t.match(/\b(\d{1,2})\s*(d|dias?|days?)\b/))) return atras(+m[1] * 86400000, "d");
    if ((m = t.match(/\b(\d{1,2})\s*(sem|semanas?|w|wk|wks|weeks?)\b/))) return atras(+m[1] * 7 * 86400000, "sem");
    if ((m = t.match(/\b(\d{1,2})\s*(anos?|years?|yr|yrs)\b/))) return atras(+m[1] * 365 * 86400000, "ano");
    if ((m = t.match(new RegExp(`\\b(\\d{1,2}) de (${MESES.join("|")})(?: de (\\d{4}))?`))) || (m = t.match(new RegExp(`\\b(${MONTHS.join("|")}) (\\d{1,2})(?:,? (\\d{4}))?`)))) {
      const esIng = MONTHS.includes(m[1]);
      const dia = +(esIng ? m[2] : m[1]), mes = esIng ? MONTHS.indexOf(m[1]) : MESES.indexOf(m[2]);
      const y = m[3] ? +m[3] : ahora.getFullYear();
      const d = conHora(new Date(y, mes, dia));
      if (!m[3] && d > ahora) d.setFullYear(y - 1);
      return { ms: +d, precision: hm ? "exacta" : "d" };
    }
    if ((m = t.match(new RegExp(`\\b(${DIAS.join("|")}|${DAYS.join("|")})\\b`)))) {
      const i = DIAS.includes(m[1]) ? DIAS.indexOf(m[1]) : DAYS.indexOf(m[1]);
      const d = new Date(ahora); d.setDate(d.getDate() - (((ahora.getDay() - i) + 7) % 7 || 7));
      return { ms: +conHora(d), precision: hm ? "exacta" : "d" };
    }
    return null;
  }

  // 1) la hora exacta escondida en los datos de la página: "post_id":"123" … "creation_time":1760000000
  let mapaJson = null, mapaJsonN = -1;
  function horasDeJson() {
    const scripts = document.querySelectorAll('script[type="application/json"]');
    if (mapaJson && scripts.length === mapaJsonN) return mapaJson;
    mapaJson = new Map(); mapaJsonN = scripts.length;
    for (const s of scripts) {
      const t = s.textContent || "";
      if (!t.includes("creation_time")) continue;
      const rx = /"(?:post_id|story_fbid|top_level_post_id)":"?(\d{3,})"?/g;
      let m;
      while ((m = rx.exec(t))) {
        const trozo = t.slice(m.index, m.index + 8000);
        const c = trozo.match(/"creation_time":(\d{10})/);
        if (c && !mapaJson.has(m[1])) mapaJson.set(m[1], +c[1] * 1000);
      }
    }
    return mapaJson;
  }
  // 2) solo las letras que se ven (Facebook mete letras falsas corridas de lugar y reordena las verdaderas)
  function textoVisible(el) {
    const base = el.getBoundingClientRect();
    if (!base.width || !base.height) return "";
    const chars = [];
    const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const rg = document.createRange();
    let n;
    while ((n = tw.nextNode())) {
      const p = n.parentElement;
      if (!p) continue;
      const cs = getComputedStyle(p);
      if (cs.display === "none" || cs.visibility === "hidden" || +cs.opacity === 0 || parseFloat(cs.fontSize) < 3) continue;
      for (let i = 0; i < n.length; i++) {
        rg.setStart(n, i); rg.setEnd(n, i + 1);
        const b = rg.getBoundingClientRect();
        if (!b.width || !b.height) continue;
        const cy = b.top + b.height / 2;
        if (cy < base.top - 1 || cy > base.bottom + 1 || b.right < base.left - 1 || b.left > base.right + 1) continue;
        chars.push({ x: b.left, r: b.right, ch: n.data[i] });
      }
    }
    chars.sort((a, b) => a.x - b.x);
    let out = "", der = null;
    for (const c of chars) { if (der != null && c.x - der > 2.5 && !out.endsWith(" ") && c.ch !== " ") out += " "; out += c.ch; der = c.r; }   // hueco visible = espacio
    return out.replace(/\s+/g, " ").trim();
  }
  // candidatos a "hora" en la cabecera de la publicación
  function candidatosHora(art) {
    const top = art.getBoundingClientRect().top;
    const out = [];
    for (const el of art.querySelectorAll('a[href], a[role="link"], abbr, span[id], [aria-labelledby]')) {
      if (!propio(el, art) || out.length > 8) continue;
      const r = el.getBoundingClientRect();
      if (r.top - top > 170 || !r.width) continue;               // solo la cabecera
      const h = el.getAttribute("href") || "";
      if (/\/user\/|\/groups\/[^/]+\/?$|profile\.php|\/hashtag\//.test(h)) continue;
      const txt = (el.innerText || "").trim();
      if (txt.length > 60) continue;
      out.push(el);
    }
    // primero lo que tiene pinta de hora: link vacío ("#"), link a la publicación o texto corto
    const pinta = (el) => { const h = el.getAttribute("href"); return esLinkPost(h) || h === "#" || h === "" || (h == null && el.tagName === "A") ? 0 : (el.innerText || "").trim().length <= 12 ? 1 : 2; };
    return out.sort((a, b) => pinta(a) - pinta(b));
  }
  // 3) pasar el puntero (como haces tú) y leer el globito; de paso Facebook completa el link
  async function hover(el, ms) {
    const r = el.getBoundingClientRect();
    const o = { bubbles: true, cancelable: true, view: window, clientX: r.left + Math.min(6, r.width / 2), clientY: r.top + r.height / 2 };
    try {
      el.dispatchEvent(new PointerEvent("pointerover", o)); el.dispatchEvent(new PointerEvent("pointerenter", { ...o, bubbles: false }));
      el.dispatchEvent(new MouseEvent("mouseover", o)); el.dispatchEvent(new MouseEvent("mouseenter", { ...o, bubbles: false }));
      el.dispatchEvent(new MouseEvent("mousemove", o));
      el.focus?.({ preventScroll: true });
    } catch {}
    await dormir(ms);
    const tip = [...document.querySelectorAll('[role="tooltip"]')].map(x => (x.innerText || "").trim()).filter(Boolean).pop() || "";
    try {
      el.dispatchEvent(new MouseEvent("mouseout", o)); el.dispatchEvent(new MouseEvent("mouseleave", { ...o, bubbles: false }));
      el.dispatchEvent(new PointerEvent("pointerout", o)); el.blur?.();
    } catch {}
    return tip;
  }
  function fechaRapida(art, texto, url) {
    // 1) datos escondidos
    const id = (url.match(/\/posts\/(\d+)/) || url.match(/story_fbid=(\d+)/) || [])[1];
    if (id) { const ms = horasDeJson().get(id); if (ms) return { publicado_ms: ms, precision: "exacta", fecha_txt: new Date(ms).toLocaleString("es-CL"), fecha_fuente: "datos" }; }
    for (const el of art.querySelectorAll("[data-utime]")) { const u = +el.getAttribute("data-utime"); if (u > 1e9) return { publicado_ms: u * 1000, precision: "exacta", fecha_txt: el.getAttribute("title") || "", fecha_fuente: "datos" }; }
    // 2) letras visibles / atributos de la hora
    for (const el of candidatosHora(art)) {
      for (const [txt, fuente] of [[el.getAttribute("aria-label"), "etiqueta"], [el.getAttribute("title"), "etiqueta"], [textoVisible(el), "visible"]]) {
        if (!txt || txt.length > 70) continue;
        const f = parseFecha(txt);
        if (f) return { publicado_ms: f.ms, precision: f.precision, fecha_txt: txt.slice(0, 50), fecha_fuente: fuente };
      }
    }
    // 4) el texto tal cual (cabecera)
    let cab = art.innerText || "";
    const corte = texto ? norm(cab).indexOf(norm(texto).slice(0, 25)) : -1;
    cab = corte > 0 ? cab.slice(0, corte) : cab.slice(0, 220);
    for (const linea of cab.split(/\n|·/).map(x => x.trim()).filter(Boolean)) {
      const f = parseFecha(linea);
      if (f) return { publicado_ms: f.ms, precision: f.precision, fecha_txt: linea.slice(0, 50), fecha_fuente: "texto" };
    }
    return null;
  }

  function huella(s) {           // id corto para publicaciones sin link
    let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) | 0;
    return "h" + (h >>> 0).toString(36);
  }
  const claves = new WeakMap(); let nClave = 0;               // id por elemento (sin tocar la página)
  function leer(art) {
    const texto = textoDe(art).slice(0, 1800);
    if (texto.length < 12) return null;
    if (!claves.has(art)) claves.set(art, ++nClave);
    const a = autorDe(art);
    const url = linkDe(art);
    const f = fechaRapida(art, texto, url) || {};
    return { k: claves.get(art), id: url || huella(a.autor + "|" + texto.slice(0, 140)), url, ...a, texto, ...grupoDe(art),
             publicado_ms: f.publicado_ms ?? null, precision: f.precision || "", fecha_txt: f.fecha_txt || "", fecha_fuente: f.fecha_fuente || "",
             edad_h: f.publicado_ms ? Math.max(0, (Date.now() - f.publicado_ms) / 3.6e6) : null, visto_ms: Date.now() };
  }
  function extraer() { return articulosPrincipales().map(art => ({ art, p: leer(art) })).filter(x => x.p); }

  // a las que les falta fecha o link: pasar el puntero por la hora (3), una por una, sin apuro
  const PRIORIDAD = { datos: 4, globito: 3, etiqueta: 2, visible: 2, texto: 1, "": 0 };
  const exacta = (p) => p.fecha_fuente === "datos" || p.fecha_fuente === "globito";
  // ¿vale la pena pasar el puntero? (sin link, sin fecha, o fecha muy aproximada como "3 d")
  const falta = (p) => !p.url || !p.publicado_ms || (!exacta(p) && ["d", "sem", "ano"].includes(p.precision));
  function usarFecha(p, f) {           // se queda con la mejor fecha que tenga (la exacta gana)
    if (!f?.publicado_ms) return;
    if ((PRIORIDAD[f.fecha_fuente] || 0) <= (PRIORIDAD[p.fecha_fuente || ""] || 0) && p.publicado_ms) return;
    Object.assign(p, f, { edad_h: Math.max(0, (Date.now() - f.publicado_ms) / 3.6e6) });
  }
  async function completar(lista, ms) {
    for (const { art, p } of lista) {
      if (!falta(p)) continue;
      for (const el of candidatosHora(art).slice(0, 3)) {
        const tip = await hover(el, ms);
        if (!p.url) { const u = linkDe(art); if (u) { p.url = u; p.id = u; } }
        usarFecha(p, fechaRapida(art, p.texto, p.url));          // con el link ya se puede buscar la hora exacta escondida
        const f = tip ? parseFecha(tip) : null;
        if (f) usarFecha(p, { publicado_ms: f.ms, precision: f.precision, fecha_txt: tip.slice(0, 60), fecha_fuente: f.precision === "exacta" ? "globito" : "etiqueta" });
        if (!falta(p) && (exacta(p) || p.precision !== "")) break;
      }
    }
  }

  // ---------------------------------------------------------------- diagnóstico (para ajustar a tu Facebook)
  function diagnostico() {
    const arts = articulosPrincipales().slice(0, 5);
    return arts.map(art => {
      const c = art.cloneNode(true);
      c.querySelectorAll("img, svg, video, image").forEach(x => { x.removeAttribute("src"); x.removeAttribute("srcset"); x.removeAttribute("xlink:href"); x.innerHTML = ""; });
      c.querySelectorAll('[role="article"]').forEach((x, i) => { if (i > 0 || x !== c) x.innerHTML = "[comentario]"; });
      const p = leer(art) || {};
      return {
        html: c.outerHTML.slice(0, 15000),
        horas: candidatosHora(art).map(el => ({ tag: el.tagName, href: (el.getAttribute("href") || "").slice(0, 120), aria: el.getAttribute("aria-label") || "", texto: (el.innerText || "").slice(0, 60), visible: textoVisible(el) })),
        leido: { autor: p.autor, autor_url: p.autor_url, url: p.url, fecha_txt: p.fecha_txt, fuente: p.fecha_fuente, texto: (p.texto || "").slice(0, 120) }
      };
    });
  }

  // ---------------------------------------------------------------- modo vigía (un paso del plan)
  async function modoVigia(paso) {
    const R = paso?.ritmo || {};
    const objetivo = Math.max(1, paso?.objetivo || 10);
    const maxMs = Math.max(15000, paso?.max_ms || 6 * 60000);
    const pacienciaMs = Math.max(8000, (R.paciencia_seg || 25) * 1000);
    const hoverMs = () => rango(R.hover_seg, [0.4, 0.9]) * 1000;
    const t0 = Date.now();
    const posts = new Map();                 // k → post
    const enviados = new Set();
    let ultimoNuevo = Date.now(), ultimoEnvio = Date.now(), ocultoMs = 0, bajadas = 0, finPagina = 0;

    const mandar = async (todo) => {
      const listos = [...posts.values()].filter(p => !enviados.has(p.k) && (todo || p._vueltas >= 1));
      if (!listos.length) return;
      listos.forEach(p => enviados.add(p.k));
      ultimoEnvio = Date.now();
      await enviar({ tipo: "vigia_parcial", pid: paso?.id, posts: listos.map(({ _vueltas, ...p }) => p), total: posts.size, visible: document.visibilityState, grupo_nombre: nombreDelGrupo() });
    };
    const fin = async (estado, motivo = "") => {
      await mandar(true);
      const lista = [...posts.values()];
      await enviar({ tipo: "vigia_listo", pid: paso?.id, posts: [], pagina: {
        estado, motivo, url: location.href, titulo: document.title.slice(0, 80), visible: document.visibilityState, grupo_nombre: nombreDelGrupo(),
        oculto: ocultoMs > (Date.now() - t0) * 0.6, total: posts.size, objetivo, seg: Math.round((Date.now() - t0) / 1000),
        calidad: { fecha: lista.filter(p => p.publicado_ms).length, link: lista.filter(p => p.url).length, autor: lista.filter(p => p.autor).length },
        articulos: document.querySelectorAll(SEL).length, ...(paso?.diag ? { diag: diagnostico() } : {}) } });
    };

    await dormir(rango(R.carga_seg, [3, 6]) * 1000);           // esperar que cargue, como quien recién entra
    while (true) {
      const el = Date.now() - t0;
      const est = estadoPagina(posts.size);
      if (est === "login" || est === "checkpoint" || est === "bloqueo") return fin(est);
      for (const p of posts.values()) p._vueltas = (p._vueltas || 0) + 1;
      const nuevos = [];
      for (const x of extraer()) {
        const ya = posts.get(x.p.k);
        if (!ya) { if (posts.size < objetivo + 5) { posts.set(x.p.k, { ...x.p, _vueltas: 0 }); nuevos.push(x); ultimoNuevo = Date.now(); } }
        else if (!enviados.has(x.p.k)) {
          const m = { ...ya, ...x.p, _vueltas: ya._vueltas };
          for (const k of ["url", "id", "autor", "autor_url", "autor_id"]) if (!x.p[k] && ya[k]) m[k] = ya[k];
          // la fecha: se queda con la mejor que haya conseguido (la del globito o la escondida no se pierden)
          if (ya.publicado_ms && (!x.p.publicado_ms || (PRIORIDAD[ya.fecha_fuente || ""] || 0) > (PRIORIDAD[x.p.fecha_fuente || ""] || 0)))
            for (const k of ["publicado_ms", "precision", "fecha_txt", "fecha_fuente", "edad_h"]) m[k] = ya[k];
          posts.set(x.p.k, m);
        }
      }
      if (R.puntero !== false && nuevos.length) {
        const faltan = nuevos.filter(x => falta(x.p));
        if (faltan.length) { await completar(faltan, hoverMs()); for (const x of faltan) posts.set(x.p.k, { ...posts.get(x.p.k), ...x.p }); }
      }
      if (Date.now() - ultimoEnvio > 7000 || [...posts.values()].filter(p => !enviados.has(p.k)).length >= 6) await mandar(false);
      if (!posts.size && el > 12000) {
        const e2 = estadoPagina(0);
        if (e2 === "sin_acceso" || e2 === "sin_resultados") return fin(e2);
      }
      if (posts.size >= objetivo) return fin("ok", "cantidad");
      if (Date.now() - t0 > maxMs) return fin(posts.size ? "ok" : estadoPagina(0), "tiempo");
      const abajo = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 50;
      finPagina = abajo ? finPagina + 1 : 0;
      if (Date.now() - ultimoNuevo > pacienciaMs && (abajo || el > pacienciaMs * 2)) return fin(posts.size ? "ok" : estadoPagina(0), "no_hay_mas");
      if (document.visibilityState === "hidden") ocultoMs += 1;
      // bajar como persona: unos tirones de ruedita; de vez en cuando sube un poquito
      if (Math.random() < (R.subir_prob ?? 0.1) && bajadas > 2) window.scrollBy(0, -Math.round(rango(R.subir_px, [120, 320])));
      else {
        const n = Math.round(rango(R.tirones, [2, 4]));
        for (let i = 0; i < n; i++) { window.scrollBy(0, Math.round(rango(R.tiron_px, [120, 260]))); await dormir(rango(R.tiron_ms, [90, 260])); }
      }
      bajadas++;
      const lectura = rango(R.lectura_seg, [2, 5]) * 1000;        // "leyendo" lo que apareció
      await dormir(lectura);
      if (document.visibilityState === "hidden") ocultoMs += lectura;
    }
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
      const nuevos = extraer().map(x => x.p).filter(p => !enviados.has(p.id));
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
