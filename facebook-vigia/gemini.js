// gemini.js — el "cerebrito". Lee publicaciones de Facebook y decide si son alguien PIDIENDO un trabajo
// (electricidad, gasfitería o construcción — los rubros que elijas), de qué se trata, qué necesita,
// comuna, urgencia, y te redacta el mensaje para escribirle. Clasifica de a lotes de 8.
//
// Si Gemini falla, devuelve un diagnóstico claro (qué pasó, qué hacer y el link exacto para arreglarlo).
// Llave "AQ." → Vertex (modo express), "AIza" → Google AI Studio.

const SERVIDORES = {
  aistudio: "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
  vertex: "https://aiplatform.googleapis.com/v1/publishers/google/models/{m}:generateContent"
};
const MODELOS_DEF = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest"];
let BUENO = { key: "", srv: "", modelo: "" };   // lo que respondió la última vez con esta llave (se prueba primero)

export const LINKS = {
  aistudio_llaves: "https://aistudio.google.com/apikey",
  express: "https://console.cloud.google.com/vertex-ai/studio",
  express_alta: "https://cloud.google.com/generative-ai-studio",
  credenciales: "https://console.cloud.google.com/apis/credentials",
  api_gemini: "https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com",
  api_vertex: "https://console.cloud.google.com/apis/library/aiplatform.googleapis.com",
  facturacion: "https://console.cloud.google.com/billing",
  limites: "https://ai.google.dev/gemini-api/docs/rate-limits"
};

function ordenServidores(cfg) {
  const modo = cfg.gemini_endpoint || "auto";
  if (modo === "aistudio" || modo === "vertex") return [modo];
  const key = cfg.gemini_key || "";
  let orden = key.startsWith("AQ.") ? ["vertex", "aistudio"] : ["aistudio", "vertex"];
  if (BUENO.key === key && orden.includes(BUENO.srv)) orden = [BUENO.srv, ...orden.filter(s => s !== BUENO.srv)];
  return orden;
}
function ordenModelos(cfg) {
  const ms = cfg.modelos?.length ? cfg.modelos : MODELOS_DEF;
  return BUENO.key === cfg.gemini_key && ms.includes(BUENO.modelo) ? [BUENO.modelo, ...ms.filter(m => m !== BUENO.modelo)] : ms;
}
const llaveValida = (k) => !!k && !String(k).startsWith("PEGA") && String(k).length > 20;

async function llamar(servidor, modelo, cuerpo, key, timeoutMs = 45000) {
  let url = SERVIDORES[servidor].replace("{m}", modelo);
  const headers = { "Content-Type": "application/json" };
  if (servidor === "vertex") url += "?key=" + encodeURIComponent(key);
  else headers["x-goog-api-key"] = key;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { method: "POST", headers, body: JSON.stringify(cuerpo), signal: ctrl.signal });
    if (!r.ok) {
      let j = null;
      try { j = (await r.json())?.error; } catch {}
      const det = (j?.details || []);
      const e = new Error(`HTTP ${r.status}${j?.message ? " · " + j.message.slice(0, 160) : ""}`);
      e.status = r.status;
      e.gstatus = j?.status || "";
      e.reason = det.map(d => d.reason).filter(Boolean)[0] || "";
      e.activationUrl = det.map(d => d.metadata?.activationUrl).filter(Boolean)[0] || "";
      e.gmsg = j?.message || "";
      e.servidor = servidor; e.modelo = modelo;
      throw e;
    }
    return await r.json();
  } catch (e) {
    if (e.name === "AbortError") { const x = new Error("Google no respondió a tiempo"); x.status = 0; x.red = true; throw x; }
    if (e instanceof TypeError) { const x = new Error("sin conexión con Google"); x.status = 0; x.red = true; throw x; }
    throw e;
  } finally { clearTimeout(t); }
}

// ¿qué pasó y qué hacer? (lo que muestra la alarma del panel)
export function diagnosticar(e, cfg = {}) {
  const key = cfg.gemini_key || "";
  const esExpress = key.startsWith("AQ.");
  const llaves = esExpress ? { link: LINKS.express, txt: "Abrir mis llaves (Vertex AI Studio, modo express)" } : { link: LINKS.aistudio_llaves, txt: "Abrir mis llaves en Google AI Studio" };
  if (!e) return null;
  if (e === "sin_llave") return { tipo: "sin_llave", titulo: "Falta la llave de Gemini", grave: true,
    que: "Sin llave el vigía decide con reglas simples (se le pasan cosas o anota de más).",
    pasos: ["Abre Google AI Studio con tu cuenta de Google.", "Toca «Create API key» (Crear clave de API).", "Copia la llave, vuelve aquí, pégala y toca «Guardar y probar»."],
    link: LINKS.aistudio_llaves, link_txt: "Crear llave en Google AI Studio" };
  const m = (e.gmsg || e.message || "").toLowerCase();
  if (e.red) return { tipo: "red", titulo: "No hay conexión con Google", grave: false, que: "Puede ser internet o Google lento. Se reintenta sola.", pasos: ["Revisa tu internet. Si sigue, espera unos minutos."], link: "", link_txt: "" };
  if (e.reason === "API_KEY_INVALID" || /api key not valid|invalid api key|api_key_invalid/.test(m))
    return { tipo: "llave_invalida", titulo: "La llave no sirve", grave: true, que: "Quedó mal copiada, la borraron o la cambiaron.",
      pasos: ["Abre tus llaves.", "Copia la llave completa (o crea una nueva).", "Pégala aquí y toca «Guardar y probar»."], ...llaves, link_txt: llaves.txt };
  if (/expired|expirad/.test(m))
    return { tipo: "llave_vencida", titulo: "La llave venció", grave: true, que: "Google desactivó esa llave.", pasos: ["Crea una llave nueva y pégala aquí."], ...llaves, link_txt: llaves.txt };
  if (e.reason === "SERVICE_DISABLED" || /has not been used in project|is disabled|service_disabled|api has not been used/.test(m)) {
    const lib = e.servidor === "vertex" ? LINKS.api_vertex : LINKS.api_gemini;
    return { tipo: "api_apagada", titulo: "La API de Gemini está apagada en tu proyecto", grave: true,
      que: "Hay que volver a habilitarla (pasa si el proyecto se pausó o es nuevo).",
      pasos: ["Abre el link: te lleva directo a la API de tu proyecto.", "Toca «Habilitar» (Enable) y espera 1–2 minutos.", "Vuelve y toca «Probar de nuevo»."],
      link: e.activationUrl || lib, link_txt: "Habilitar la API (abre tu proyecto)" };
  }
  if (/billing|facturaci/.test(m))
    return { tipo: "facturacion", titulo: "Google pide revisar la facturación", grave: true, que: "El proyecto necesita una cuenta de facturación activa o se acabó el crédito.",
      pasos: ["Abre Facturación en Google Cloud y revisa el proyecto.", "O crea una llave gratis en Google AI Studio y pégala aquí."], link: LINKS.facturacion, link_txt: "Abrir facturación" };
  if (e.status === 429 || e.gstatus === "RESOURCE_EXHAUSTED" || /quota|resource exhausted|rate limit/.test(m))
    return { tipo: "cuota", titulo: "Se acabó la cuota gratis por ahora", grave: false,
      que: "Google limita cuántas consultas gratis haces por minuto y por día. El vigía espera y sigue solo; nada se pierde.",
      pasos: ["No hay que hacer nada: se reintenta sola.", "Si pasa todos los días, puedes crear otra llave o bajar las publicaciones que lee."], link: LINKS.limites, link_txt: "Ver los límites gratis" };
  if (e.status === 403 || e.gstatus === "PERMISSION_DENIED")
    return { tipo: "permiso", titulo: "Google no deja usar la llave", grave: true, que: e.gmsg || "Permiso denegado.",
      pasos: ["Revisa que la API esté habilitada y la llave no tenga restricciones.", "Lo más rápido: crea una llave nueva en Google AI Studio y pégala aquí."], link: e.activationUrl || LINKS.credenciales, link_txt: "Abrir mis credenciales de Google Cloud" };
  if (e.status === 404) return { tipo: "modelo", titulo: "Google no encontró el modelo de IA", grave: true, que: "El modelo cambió de nombre o no está en tu región.",
    pasos: ["Toca «Probar de nuevo»: prueba solo otros modelos.", "Si sigue, avísame y lo actualizo."], link: "", link_txt: "" };
  if (e.status >= 500) return { tipo: "google", titulo: "Google tiene problemas", grave: false, que: "Falla del lado de Google. Se reintenta sola.", pasos: ["Espera unos minutos."], link: "", link_txt: "" };
  return { tipo: "otro", titulo: "La IA no respondió bien", grave: false, que: e.message || "Error desconocido.", pasos: ["Toca «Probar de nuevo»."], link: llaves.link, link_txt: llaves.txt };
}

function textoRespuesta(data) {
  return (data?.candidates?.[0]?.content?.parts || []).map(p => p.text || "").join("");
}
export function extraerJson(txt) {
  let s = String(txt || "").trim().replace(/^```(?:json)?\s*/i, "").replace(/```\s*$/i, "").trim();
  try { return JSON.parse(s); } catch {}
  const a = s.indexOf("{"), b = s.lastIndexOf("}");
  const c = s.indexOf("["), d = s.lastIndexOf("]");
  for (const [i, j] of [[a, b], [c, d]]) {
    if (i >= 0 && j > i) { try { return JSON.parse(s.slice(i, j + 1)); } catch {} }
  }
  throw new Error("respuesta no es JSON");
}

// prueba la llave: {ok, detalle, diag}
export async function probar(cfg) {
  const key = cfg.gemini_key || "";
  if (!llaveValida(key)) return { ok: false, detalle: "falta la llave de Gemini", diag: diagnosticar("sin_llave", cfg) };
  const cuerpo = { contents: [{ role: "user", parts: [{ text: "Responde solo: ok" }] }] };
  let peor = null;
  for (const srv of ordenServidores(cfg)) {
    for (const modelo of ordenModelos(cfg)) {
      try {
        const t0 = Date.now();
        await llamar(srv, modelo, cuerpo, key, 20000);
        BUENO = { key, srv, modelo };
        return { ok: true, detalle: `${srv === "vertex" ? "Vertex (express)" : "Google AI Studio"} · ${modelo} · ${Date.now() - t0} ms` };
      } catch (e) {
        if (!peor || (e.status !== 404 && peor.status === 404)) peor = e;
        if (e.status === 400 || e.status === 401 || e.status === 403) break;     // la llave/proyecto: probar el otro servidor
      }
    }
  }
  return { ok: false, detalle: peor?.message || "sin respuesta", diag: diagnosticar(peor, cfg) };
}

const NOMBRES = { electricidad: "ELECTRICIDAD", gasfiteria: "GASFITERÍA (agua, gas, calefont, cañerías, desagües)", construccion: "CONSTRUCCIÓN (albañilería, cerámica, pintura, techumbre, carpintería, remodelaciones)" };
function prompt(cfg) {
  const rubros = (cfg.rubros?.length ? cfg.rubros : ["electricidad", "gasfiteria", "construccion"]).filter(r => NOMBRES[r]);
  return `Eres el asistente de un maestro que busca pegas particulares en Chile de: ${rubros.map(r => NOMBRES[r]).join("; ")}.
Te paso varias publicaciones de grupos de Facebook, cada una marcada con "### número". El texto puede venir sucio
(nombres, horas, "Me gusta", "Comentar"). Para CADA una decide si es una persona PIDIENDO o BUSCANDO que le hagan
un trabajo de esos rubros.

NO es solicitud si: la persona OFRECE sus servicios (otro maestro, empresa, publicidad), vende, regala, hace trueque
o arrienda algo, busca trabajo para sí misma, es una noticia o un meme, o no tiene que ver con esos rubros.

Responde SOLO este JSON (un elemento por publicación, con su mismo número):
{"r":[{"i":0,
  "es_solicitud":true,
  "tipo":"electricidad|gasfiteria|construccion|varios|otro",
  "resumen":"qué necesita, máx 10 palabras",
  "necesita":"descripción clara de lo que necesita, 1 o 2 frases, con detalles útiles (qué, dónde, cuándo)",
  "comuna":"comuna o sector SOLO si el texto lo dice, si no vacío",
  "urgencia":"alta|media|baja",
  "mensaje":"solo si es_solicitud: mensaje corto, cálido y natural en chileno para escribirle, tuteo, 2 o 3 líneas, sin links, sin sonar robot ni spam, que muestre que leíste lo que necesita, y que cierre con una pregunta simple",
  "frases_clave":["máx 3 frases EXACTAS del texto que muestran que pide el servicio"]}]}

Si es_solicitud es false, deja mensaje y frases_clave vacíos (igual pon tipo y resumen).`;
}
function contexto(cfg) {
  return [
    cfg.mi_nombre ? `El maestro se llama ${cfg.mi_nombre}.` : "",
    cfg.mi_rubro ? `Ofrece: ${cfg.mi_rubro}.` : "",
    cfg.mi_zona ? `Trabaja en: ${cfg.mi_zona}.` : "",
    cfg.mi_fono ? `Puede dejar su fono ${cfg.mi_fono} si corresponde.` : "",
    cfg.plantilla ? `Tono que le gusta (úsalo de guía, no lo copies igual): "${cfg.plantilla}"` : ""
  ].filter(Boolean).join(" ") || "(sin datos)";
}

// textos: [string] → { r: [resultado|null por cada texto], modelo, servidor } | { error, limite, diag }
export async function clasificarLote(cfg, textos) {
  const key = cfg.gemini_key || "";
  if (!llaveValida(key)) return { error: "sin_llave", diag: diagnosticar("sin_llave", cfg) };
  const cuerpoTxt = textos.map((t, i) => `### ${i}\n${String(t || "").slice(0, 1400)}`).join("\n\n");
  const cuerpo = {
    contents: [{ role: "user", parts: [{ text: `${prompt(cfg)}\n\nCONTEXTO DEL MAESTRO: ${contexto(cfg)}\n\nPUBLICACIONES:\n\n${cuerpoTxt}` }] }],
    generationConfig: { responseMimeType: "application/json", temperature: 0.2 }
  };
  let peor = null, limites = 0, intentos = 0;
  for (const modelo of ordenModelos(cfg)) {
    for (const srv of ordenServidores(cfg)) {
      intentos++;
      try {
        const data = await llamar(srv, modelo, cuerpo, key);
        BUENO = { key, srv, modelo };
        const obj = extraerJson(textoRespuesta(data));
        const arr = Array.isArray(obj) ? obj : (obj.r || obj.resultados || obj.publicaciones || []);
        const out = textos.map(() => null);
        arr.forEach((x, k) => {
          const i = Number.isInteger(x?.i) ? x.i : (Number.isInteger(+x?.i) ? +x.i : k);
          if (i >= 0 && i < out.length) out[i] = x;
        });
        return { r: out, modelo, servidor: srv };
      } catch (e) {
        if (!peor || (peor.status === 404 && e.status !== 404)) peor = e;
        if (e.status === 429) limites++;
      }
    }
  }
  return { error: peor?.message || "sin respuesta", limite: limites > 0 && limites >= Math.ceil(intentos / 2), diag: diagnosticar(peor, cfg) };
}
