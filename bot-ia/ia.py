"""
ia.py — el "cerebrito". Le pasa a Gemini el mensaje + la lista de tus 93
establecimientos y le pide: ¿de qué establecimiento habla, qué falla es y de
qué tipo? Gemini NO decide fechas ni puntajes: eso lo hace nucleo.py.
Si Gemini falla (sin internet o límite gratis), usa las mismas palabras clave
que tu panel.
"""
import json, re, time, urllib.error, urllib.parse, urllib.request
from nucleo import cfg, datos, norm

# Google tiene dos servidores para Gemini. Las claves de AI Studio (AIza…) van al
# primero; las claves "AQ." (Vertex AI modo express) van al segundo. En modo
# "auto" se prueban los dos y se recuerda el que respondió.
SERVIDORES = {
    "aistudio": ("https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", "header"),
    "vertex": ("https://aiplatform.googleapis.com/v1/publishers/google/models/{m}:generateContent", "query"),
}
_bueno = {"servidor": None}

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


def _orden_servidores(key):
    modo = cfg().get("gemini_endpoint", "auto")
    if modo in SERVIDORES:
        return [modo]
    orden = ["vertex", "aistudio"] if key.startswith("AQ.") else ["aistudio", "vertex"]
    if _bueno["servidor"] in orden:
        orden.remove(_bueno["servidor"])
        orden.insert(0, _bueno["servidor"])
    return orden


def _llamar(servidor, modelo, cuerpo, key, timeout=45):
    url, modo = SERVIDORES[servidor]
    url = url.format(m=modelo)
    headers = {"Content-Type": "application/json"}
    if modo == "query":
        url += "?key=" + urllib.parse.quote(key, safe="")
    else:
        headers["x-goog-api-key"] = key
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _gemini(modelo, prompt, key, timeout=30):
    cuerpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
              "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
    ultimo = None
    fin = time.time() + timeout                 # el tope es para los dos servidores juntos
    for srv in _orden_servidores(key):
        quedan = fin - time.time()
        if quedan < 3:
            break
        try:
            data = _llamar(srv, modelo, cuerpo, key, timeout=quedan)
            _bueno["servidor"] = srv
            txt = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            return json.loads(re.sub(r"^```(?:json)?|```$", "", txt).strip())
        except urllib.error.HTTPError as err:
            if err.code in (429, 500, 503):      # servidor correcto pero saturado: reintenta el que llama
                raise
            ultimo = err                          # clave no válida aquí o modelo inexistente: prueba el otro
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            ultimo = err                          # sin red hacia ese servidor: prueba el otro
    raise ultimo or TimeoutError("Gemini no respondió a tiempo")


def probar():
    """Para !diagnostico: (ok, detalle). Prueba servidores y modelos con un mensaje mínimo."""
    c = cfg()
    key = c.get("gemini_api_key", "")
    if not key or key.startswith("PEGA"):
        return False, "no hay clave en config.json"
    cuerpo = {"contents": [{"role": "user", "parts": [{"text": "Responde solo: ok"}]}]}
    fallas = []
    inicio = time.time()
    for srv in _orden_servidores(key):
        for modelo in c.get("gemini_modelos", ["gemini-2.5-flash"]):
            if time.time() - inicio > 40:
                return False, " | ".join(fallas + ["(se cortó la prueba por tiempo)"])[:700]
            t0 = time.time()
            try:
                _llamar(srv, modelo, cuerpo, key, timeout=15)
                _bueno["servidor"] = srv
                return True, f"{srv} · {modelo} · {int((time.time() - t0) * 1000)} ms"
            except urllib.error.HTTPError as e:
                fallas.append(f"{srv}/{modelo}: HTTP {e.code} {e.read().decode(errors='ignore')[:90]}")
            except Exception as e:
                fallas.append(f"{srv}: sin conexión ({str(e)[:60]})")
                break                       # sin red a ese servidor: no insistir con otros modelos
    return False, " | ".join(fallas)[:700]


def analizar(texto, autor="supervisora"):
    """Devuelve ({"es_reporte":bool, "hallazgos":[...]}, motor). Nunca tarda más de ~45 s."""
    c = cfg()
    key = c.get("gemini_api_key", "")
    if key and not key.startswith("PEGA"):
        prompt = PROMPT.format(lista=_lista(), autor=autor, texto=texto[:2500])
        t0 = time.time()
        TOPE = 45
        for modelo in c.get("gemini_modelos", ["gemini-2.5-flash"]):
            for intento in range(2):
                quedan = TOPE - (time.time() - t0)
                if quedan < 5:
                    print("[ia] se acabó el tiempo, uso respaldo sin IA")
                    return sin_ia(texto), "palabras-clave (IA lenta)"
                try:
                    r = _gemini(modelo, prompt, key, timeout=min(30, quedan))
                    for h in r.get("hallazgos", []):
                        if h.get("tipo") not in PAL and h.get("tipo") != "OTRO":
                            h["tipo"] = tipo_por_palabras(h.get("problema", "") + " " + texto)
                    return r, modelo
                except urllib.error.HTTPError as err:
                    print(f"[ia] {modelo} HTTP {err.code}: {err.read().decode(errors='ignore')[:160]}")
                    if err.code in (429, 500, 503) and intento == 0:
                        time.sleep(min(8, max(0, TOPE - (time.time() - t0) - 10)))
                        continue
                    break
                except (urllib.error.URLError, TimeoutError, OSError) as err:
                    print(f"[ia] sin conexión con Gemini ({err}); uso respaldo sin IA")
                    return sin_ia(texto), "palabras-clave (sin red)"
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
