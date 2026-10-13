// gemini.js — el "cerebrito". Lee publicaciones de Facebook y decide si son alguien PIDIENDO un
// trabajo de electricidad o gasfitería (no ofreciéndolo), de qué se trata, comuna, urgencia, y te
// redacta el mensaje para escribirle. Devuelve además las "frases clave" para ir aprendiendo.
//
// v2: clasifica de a LOTES (hasta 8 publicaciones por llamada) → 8 veces menos consultas, cuida
// la cuota gratis. Si Google responde "demasiadas consultas" (429) lo avisa con {limite:true}
// y el background espera y reintenta solo.
//
// Usa la misma llave de tu bot de SOSER: "AQ." → Vertex (express), "AIza" → AI Studio.

const SERVIDORES = {
  aistudio: "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
  vertex: "https://aiplatform.googleapis.com/v1/publishers/google/models/{m}:generateContent"
};
const MODELOS_DEF = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest"];
let BUENO = { key: "", srv: "" };   // el servidor que respondió la última vez con esta llave (se prueba primero)

function ordenServidores(cfg) {
  const modo = cfg.gemini_endpoint || "auto";
  if (modo === "aistudio" || modo === "vertex") return [modo];
  const key = cfg.gemini_key || "";
  let orden = key.startsWith("AQ.") ? ["vertex", "aistudio"] : ["aistudio", "vertex"];
  if (BUENO.key === key && orden.includes(BUENO.srv)) orden = [BUENO.srv, ...orden.filter(s => s !== BUENO.srv)];
  return orden;
}

const llaveValida = (k) => !!k && !String(k).startsWith("PEGA") && String(k).length > 20;

async function llamar(servidor, modelo, cuerpo, key, timeoutMs = 40000) {
  let url = SERVIDORES[servidor].replace("{m}", modelo);
  const headers = { "Content-Type": "application/json" };
  if (servidor === "vertex") url += "?key=" + encodeURIComponent(key);
  else headers["x-goog-api-key"] = key;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { method: "POST", headers, body: JSON.stringify(cuerpo), signal: ctrl.signal });
    if (!r.ok) {
      let det = "";
      try { det = (await r.json())?.error?.message || ""; } catch {}
      const e = new Error(`HTTP ${r.status}${det ? " · " + det.slice(0, 120) : ""}`);
      e.status = r.status;
      throw e;
    }
    return await r.json();
  } catch (e) {
    if (e.name === "AbortError") { const x = new Error("no respondió a tiempo"); x.status = 0; throw x; }
    throw e;
  } finally { clearTimeout(t); }
}

function textoRespuesta(data) {
  return (data?.candidates?.[0]?.content?.parts || []).map(p => p.text || "").join("");
}

// JSON a prueba de respuestas "creativas" (```json …```, texto antes/después)
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

// Prueba la llave (para el panel): devuelve {ok, detalle}
export async function probar(cfg) {
  const key = cfg.gemini_key || "";
  if (!llaveValida(key)) return { ok: false, detalle: "falta la llave de Gemini" };
  const cuerpo = { contents: [{ role: "user", parts: [{ text: "Responde solo: ok" }] }] };
  const fallas = [];
  for (const srv of ordenServidores(cfg)) {
    for (const modelo of (cfg.modelos?.length ? cfg.modelos : MODELOS_DEF)) {
      try {
        const t0 = Date.now();
        await llamar(srv, modelo, cuerpo, key, 15000);
        BUENO = { key, srv };
        return { ok: true, detalle: `${srv} · ${modelo} · ${Date.now() - t0} ms` };
      } catch (e) {
        fallas.push(`${srv}/${modelo}: ${e.message}`);
        if (e.status === 401 || e.status === 403) break;     // llave mala en este servidor: probar el otro
      }
    }
  }
  return { ok: false, detalle: fallas.slice(0, 3).join(" | ") };
}

const PROMPT = `Eres el asistente de un maestro que busca pegas particulares de ELECTRICIDAD y GASFITERÍA en Chile.
Te paso varias publicaciones de grupos de Facebook, cada una marcada con "### número". El texto puede venir
sucio (nombres, horas, "Me gusta", "Comentar"). Para CADA una decide si es una persona PIDIENDO o BUSCANDO que
le hagan un trabajo de electricidad o gasfitería (incluye gas, calefont, agua, cañerías, desagües, enchufes,
tablero, luz, etc.).

NO es solicitud si: la persona OFRECE sus servicios (otro maestro, empresa, publicidad), es una noticia, un
meme, una venta de productos, o no tiene que ver con electricidad/gasfitería.

Responde SOLO este JSON (un elemento por publicación, con su mismo número):
{"r":[{"i":0,
  "es_solicitud":true,
  "tipo":"electricidad|gasfiteria|ambos|otro",
  "resumen":"qué necesita, máx 10 palabras",
  "comuna":"comuna o sector SOLO si el texto lo dice, si no vacío",
  "urgencia":"alta|media|baja",
  "mensaje":"solo si es_solicitud: mensaje corto, cálido y natural en chileno para escribirle, tuteo, 2 o 3 líneas, sin links, sin sonar robot ni spam, que muestre que leíste lo que necesita, y que cierre con una pregunta simple",
  "frases_clave":["máx 3 frases EXACTAS del texto que muestran que pide el servicio"]}]}

Si es_solicitud es false, deja mensaje y frases_clave vacíos.`;

function contexto(cfg) {
  return [
    cfg.mi_nombre ? `El maestro se llama ${cfg.mi_nombre}.` : "",
    cfg.mi_rubro ? `Ofrece: ${cfg.mi_rubro}.` : "",
    cfg.mi_zona ? `Trabaja en: ${cfg.mi_zona}.` : "",
    cfg.mi_fono ? `Puede dejar su fono ${cfg.mi_fono} si corresponde.` : "",
    cfg.plantilla ? `Tono que le gusta (úsalo de guía, no lo copies igual): "${cfg.plantilla}"` : ""
  ].filter(Boolean).join(" ") || "(sin datos)";
}

// textos: [string] → { r: [resultado|null por cada texto] } | { error, limite }
export async function clasificarLote(cfg, textos) {
  const key = cfg.gemini_key || "";
  if (!llaveValida(key)) return { error: "sin_llave" };
  const cuerpoTxt = textos.map((t, i) => `### ${i}\n${String(t || "").slice(0, 1400)}`).join("\n\n");
  const prompt = `${PROMPT}\n\nCONTEXTO DEL MAESTRO: ${contexto(cfg)}\n\nPUBLICACIONES:\n\n${cuerpoTxt}`;
  const cuerpo = {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    generationConfig: { responseMimeType: "application/json", temperature: 0.2 }
  };
  let ultimo = null, limites = 0, intentos = 0;
  for (const modelo of (cfg.modelos?.length ? cfg.modelos : MODELOS_DEF)) {
    for (const srv of ordenServidores(cfg)) {
      intentos++;
      try {
        const data = await llamar(srv, modelo, cuerpo, key);
        BUENO = { key, srv };
        const obj = extraerJson(textoRespuesta(data));
        const arr = Array.isArray(obj) ? obj : (obj.r || obj.resultados || obj.publicaciones || []);
        const out = textos.map(() => null);
        arr.forEach((x, k) => {
          const i = Number.isInteger(x?.i) ? x.i : (Number.isInteger(+x?.i) ? +x.i : k);
          if (i >= 0 && i < out.length) out[i] = x;
        });
        return { r: out, modelo, servidor: srv };
      } catch (e) {
        ultimo = e;
        if (e.status === 429) limites++;
      }
    }
  }
  return { error: ultimo?.message || "sin respuesta", limite: limites > 0 && limites >= Math.ceil(intentos / 2) };
}
