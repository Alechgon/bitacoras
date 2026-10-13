// gemini.js — el "cerebrito" de la extensión. Lee el texto de un post de Facebook y decide
// si es alguien PIDIENDO un servicio de electricidad o gasfitería (no ofreciéndolo), de qué
// se trata, de qué comuna, qué tan urgente, y te redacta un mensaje para escribirle. Además
// devuelve las "frases clave" que lo delataron, para ir aprendiendo palabras nuevas solo.
//
// Usa la misma llave que tu bot de SOSER: si parte con "AQ." va a Vertex (modo express),
// si parte con "AIza" va a AI Studio. En "auto" prueba las dos y se queda con la que responde.

const SERVIDORES = {
  aistudio: "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
  vertex: "https://aiplatform.googleapis.com/v1/publishers/google/models/{m}:generateContent"
};
let BUENO = null;

function ordenServidores(cfg) {
  const modo = cfg.gemini_endpoint || "auto";
  if (modo === "aistudio" || modo === "vertex") return [modo];
  const key = cfg.gemini_key || "";
  let orden = key.startsWith("AQ.") ? ["vertex", "aistudio"] : ["aistudio", "vertex"];
  if (BUENO && orden.includes(BUENO)) orden = [BUENO, ...orden.filter(s => s !== BUENO)];
  return orden;
}

async function llamar(servidor, modelo, cuerpo, key, timeoutMs = 30000) {
  let url = SERVIDORES[servidor].replace("{m}", modelo);
  const headers = { "Content-Type": "application/json" };
  if (servidor === "vertex") url += "?key=" + encodeURIComponent(key);
  else headers["x-goog-api-key"] = key;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { method: "POST", headers, body: JSON.stringify(cuerpo), signal: ctrl.signal });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  } finally { clearTimeout(t); }
}

function extraerJson(txt) {
  const limpio = (txt || "").replace(/^```(?:json)?/i, "").replace(/```$/i, "").trim();
  return JSON.parse(limpio);
}

// Prueba la llave (para el panel): devuelve {ok, detalle}
export async function probar(cfg) {
  const key = cfg.gemini_key || "";
  if (!key || key.startsWith("PEGA")) return { ok: false, detalle: "falta la llave de Gemini" };
  const cuerpo = { contents: [{ role: "user", parts: [{ text: "Responde solo: ok" }] }] };
  const fallas = [];
  for (const srv of ordenServidores(cfg)) {
    for (const modelo of (cfg.modelos || ["gemini-2.5-flash"])) {
      try {
        const t0 = Date.now();
        await llamar(srv, modelo, cuerpo, key, 15000);
        BUENO = srv;
        return { ok: true, detalle: `${srv} · ${modelo} · ${Date.now() - t0} ms` };
      } catch (e) { fallas.push(`${srv}/${modelo}: ${e.message}`); }
    }
  }
  return { ok: false, detalle: fallas.join(" | ") };
}

const PROMPT = `Eres el asistente de un maestro que busca pegas particulares de ELECTRICIDAD y GASFITERÍA en Chile.
Te paso el texto crudo de una publicación de un grupo de Facebook (puede traer basura: nombres, "Me gusta",
"Comentar", horas, etc.). Tu trabajo: decidir si es una persona PIDIENDO/BUSCANDO que le hagan un trabajo de
electricidad o gasfitería (NO alguien ofreciendo sus servicios, NO una publicidad, NO una noticia).

Responde SOLO este JSON:
{"es_solicitud": true/false,
 "tipo": "electricidad|gasfiteria|ambos|otro",
 "resumen": "en 10 palabras qué necesita",
 "comuna": "comuna o sector si lo dice, si no vacío",
 "urgencia": "alta|media|baja",
 "mensaje": "mensaje corto, cálido y natural en chileno para escribirle ofreciéndote, tuteo, sin sonar robot ni spam, 2 o 3 líneas, sin links, cerrando con una pregunta simple para que te responda",
 "frases_clave": ["las palabras/frases exactas del texto que indican que pide el servicio, máx 4"]}

Reglas:
- Si la persona OFRECE servicios (es otro maestro), es_solicitud=false.
- Si no tiene nada que ver con electricidad/gasfitería, es_solicitud=false.
- No inventes comuna ni datos que el texto no diga.
- El mensaje va dirigido a quien publicó; si tienes el contexto del maestro abajo, úsalo (nombre, zona, rubro).`;

export async function clasificar(cfg, texto) {
  const key = cfg.gemini_key || "";
  if (!key || key.startsWith("PEGA")) return null;
  const ctx = [
    cfg.mi_nombre ? `El maestro se llama ${cfg.mi_nombre}.` : "",
    cfg.mi_rubro ? `Ofrece: ${cfg.mi_rubro}.` : "",
    cfg.mi_zona ? `Trabaja en: ${cfg.mi_zona}.` : "",
    cfg.mi_fono ? `Puede dejar su fono ${cfg.mi_fono} si corresponde.` : "",
    cfg.plantilla ? `Tono/plantilla que le gusta: "${cfg.plantilla}"` : ""
  ].filter(Boolean).join(" ");
  const prompt = `${PROMPT}\n\nCONTEXTO DEL MAESTRO: ${ctx || "(sin datos)"}\n\nPUBLICACIÓN:\n"""${(texto || "").slice(0, 1800)}"""`;
  const cuerpo = {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    generationConfig: { responseMimeType: "application/json", temperature: 0.2 }
  };
  let ultimo = null;
  for (const modelo of (cfg.modelos || ["gemini-2.5-flash"])) {
    for (const srv of ordenServidores(cfg)) {
      try {
        const data = await llamar(srv, modelo, cuerpo, key, 30000);
        BUENO = srv;
        const txt = data?.candidates?.[0]?.content?.parts?.[0]?.text || "";
        return extraerJson(txt);
      } catch (e) { ultimo = e; }
    }
  }
  console.warn("[vigía] Gemini no respondió:", ultimo?.message);
  return null;
}
