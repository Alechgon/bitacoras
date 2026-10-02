"""
ia.py — el "cerebrito". Le pasa a Gemini el mensaje + la lista de tus 93
establecimientos y le pide: ¿de qué establecimiento habla, qué falla es y de
qué tipo? Gemini NO decide fechas ni puntajes: eso lo hace nucleo.py.
Si Gemini falla (sin internet o límite gratis), usa las mismas palabras clave
que tu panel.
"""
import json, re, time, urllib.error, urllib.request
from nucleo import cfg, datos, norm

URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"

PROMPT = """Eres el asistente de mantención de SOSER, sucursal San Pablo (cocinas de colegios JUNAEB y
jardines JUNJI/INTEGRA en Santiago y Estación Central). Las supervisoras escriben en un grupo de
WhatsApp en chileno informal, con faltas de ortografía y nombres abreviados.

LISTA DE ESTABLECIMIENTOS (rbd | nombre | comuna | tipo):
{lista}

TIPOS DE FALLA (elige uno):
- GAS: fuga u olor a gas, flexibles, regulador, caseta de gas, quemadores que se apagan con olor
- FRIO: refrigerador, congelador, visicooler, frigobar, salad bar, cámara, cadena de frío
- AGUA: calefont, agua caliente, grifería, llaves, sifón, filtraciones, desagües, cámara desgrasadora
- ELEC: focos, luminarias, enchufes, interruptores, tablero, cortes de luz
- EQUIPO: horno, cocina, cocinilla, anafe, baño maría, campana, extractor, balanza, mesones
- OTRO: infraestructura, puertas, mallas, pintura, extintor, trámites, certificados, etc.

MENSAJE de {autor}:
\"\"\"{texto}\"\"\"

Responde SOLO este JSON:
{{"es_reporte": true/false,
  "hallazgos": [{{"rbd": número o null, "nombre_mencionado": "como lo escribió",
                  "problema": "resumen claro, máx 12 palabras", "tipo": "GAS|FRIO|AGUA|ELEC|EQUIPO|OTRO",
                  "seguro": true/false}}]}}

Reglas:
- es_reporte = false si es saludo, agradecimiento, coordinación sin falla, o confirmación de trabajo hecho.
- Un hallazgo por cada establecimiento distinto con problema.
- rbd SOLO si estás seguro de que corresponde a la lista; si dudas entre varios pon null y seguro=false.
- No inventes problemas que el mensaje no dice.
"""

PAL = {   # mismas palabras que usa el panel (index.html)
    "GAS": ["fuga de gas", "olor a gas", "olor a la gas", "huele a gas", "gas"],
    "FRIO": ["refrigerador", "visicooler", "congelador", "frigobar", "camara", "cadena de frio", "no enfria",
             "temperatura"],
    "AGUA": ["calefont", "califont", "agua caliente", "llave", "griferia", "sifon", "filtracion", "gotera",
             "inundad", "presion"],
    "ELEC": ["foco", "luminaria", "enchufe", "corte de luz", "electric", "interruptor", "tablero", "sin luz",
             "corriente"],
    "EQUIPO": ["horno", "anafe", "cocinilla", "campana", "extractor", "bano maria", "balanza", "salad bar", "meson"],
}


def tipo_por_palabras(texto):
    t = norm(texto)
    for k in ["GAS", "FRIO", "AGUA", "ELEC", "EQUIPO"]:
        if any(w in t for w in PAL[k]):
            return k
    return "OTRO"


def _lista():
    return "\n".join(f"{e['rbd']} | {e['nombre']} | {e['comuna']} | {e['inst']}" for e in datos()["ESTAB"])


def _gemini(modelo, prompt, key):
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}).encode()
    req = urllib.request.Request(URL.format(m=modelo), data=body, method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=45) as r:
        data = json.loads(r.read())
    txt = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    return json.loads(re.sub(r"^```(?:json)?|```$", "", txt).strip())


def analizar(texto, autor="supervisora"):
    """Devuelve ({"es_reporte":bool, "hallazgos":[...]}, motor)."""
    c = cfg()
    key = c.get("gemini_api_key", "")
    if key and not key.startswith("PEGA_AQUI"):
        prompt = PROMPT.format(lista=_lista(), autor=autor, texto=texto[:2500])
        for modelo in c.get("gemini_modelos", ["gemini-2.5-flash"]):
            for intento in range(2):
                try:
                    r = _gemini(modelo, prompt, key)
                    for h in r.get("hallazgos", []):
                        if h.get("tipo") not in PAL and h.get("tipo") != "OTRO":
                            h["tipo"] = tipo_por_palabras(h.get("problema", "") + " " + texto)
                    return r, modelo
                except urllib.error.HTTPError as err:
                    print(f"[ia] {modelo} HTTP {err.code}: {err.read().decode(errors='ignore')[:160]}")
                    if err.code in (429, 500, 503) and intento == 0:
                        time.sleep(10)
                        continue
                    break
                except Exception as err:
                    print(f"[ia] {modelo} error: {err}")
                    break
    return sin_ia(texto), "palabras-clave"


def sin_ia(texto):
    """Respaldo sin IA: igual que el panel (RBD o alias en el texto + palabras clave),
    pero separando el mensaje en frases para no mezclar fallas de distintos establecimientos."""
    from nucleo import en_texto
    t = norm(texto)
    if not t or "multimedia omitido" in t or "se elimino este mensaje" in t:
        return {"es_reporte": False, "hallazgos": []}
    frases = [f for f in re.split(r"[.;\n]|\by en\b|\by el\b|\by la\b|,\s*en\b", texto, flags=re.I) if f and f.strip()]
    hallazgos, vistos = [], set()
    for f in frases:
        for r in en_texto(f):
            if r in vistos:
                continue
            vistos.add(r)
            tipo = tipo_por_palabras(f)
            if tipo == "OTRO":
                tipo = tipo_por_palabras(texto)
            hallazgos.append({"rbd": r, "nombre_mencionado": "", "problema": f.strip()[:90], "tipo": tipo,
                              "seguro": True})
    for r in en_texto(texto):        # alias partidos entre frases
        if r not in vistos:
            vistos.add(r)
            hallazgos.append({"rbd": r, "nombre_mencionado": "", "problema": texto.strip()[:90],
                              "tipo": tipo_por_palabras(texto), "seguro": True})
    tipo = tipo_por_palabras(texto)
    if not hallazgos and tipo != "OTRO":
        m = re.search(r"((?:escuela|esc\.?|liceo|lic\.?|colegio|complejo|jard[ií]n|j\.?i\.?|sala cuna|sc)\s+"
                      r"[^,.;:\n]{2,40}?)(?=\s+(?:tiene|tienen|est[aá]|sigue|hay|con|el|la|los|las|se)\b|[,.;:\n]|$)",
                      texto, re.I)
        if m:
            hallazgos.append({"rbd": None, "nombre_mencionado": m.group(1).strip(), "problema": texto.strip()[:90],
                              "tipo": tipo, "seguro": False})
    return {"es_reporte": bool(hallazgos), "hallazgos": hallazgos}
