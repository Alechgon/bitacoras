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

INTENCIÓN DEL MENSAJE (elige UNA):
- agendar: pide programar una visita o trabajo (dice agendar, agenden, programen, cuándo pueden venir a arreglar...).
- requerimiento: informa una falla o algo que hay que reparar, pero no pide agendar.
- pregunta: consulta información: qué se hizo, si fueron, cuándo vienen, cómo quedó, quién fue, estado de algo.
- observacion: informa algo sin pedir nada (horarios, que ya funciona, que el técnico llegó, avisos).
- charla: saludos, gracias, emojis, coordinación personal, nada de mantención.

{contexto}MENSAJE de {autor}:
\"\"\"{texto}\"\"\"

Responde SOLO este JSON:
{{"intencion": "agendar|requerimiento|pregunta|observacion|charla",
  "hallazgos": [{{"rbd": número o null, "nombre_mencionado": "como lo escribió",
                  "problema": "resumen claro, máx 12 palabras", "tipo": "GAS|FRIO|AGUA|ELEC|EQUIPO|OTRO",
                  "seguro": true/false}}],
  "pregunta": {{"rbd": número o null, "nombre_mencionado": "", "tema": "palabra clave del tema o vacío",
               "tiempo": "referencia de tiempo tal como la dijo (ej: el otro día, ayer, el lunes) o vacío",
               "sobre": "pasado|futuro|estado"}},
  "observacion": {{"rbd": número o null, "nombre_mencionado": "", "resumen": "máx 15 palabras"}}}}

Reglas:
- hallazgos solo para agendar o requerimiento: uno por establecimiento con problema. Si es agendar sin falla nueva, hallazgos vacío.
- pregunta solo si intencion = pregunta; observacion solo si intencion = observacion.
- rbd SOLO si estás seguro de que corresponde a la lista; si dudas pon null y seguro=false.
- No inventes problemas, fechas ni establecimientos que el mensaje no dice.
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


INTENCIONES = ("agendar", "requerimiento", "pregunta", "observacion", "charla")


def _normalizar(r, texto):
    """Asegura la forma del resultado y aplica la regla dura: la palabra agendar manda."""
    it = r.get("intencion")
    if it not in INTENCIONES:
        it = "requerimiento" if r.get("es_reporte") else "charla"
    if pide_agendar(texto):
        it = "agendar"
    r["intencion"] = it
    r.setdefault("hallazgos", [])
    r["es_reporte"] = it in ("agendar", "requerimiento")
    return r


def pide_agendar(texto):
    t = norm(texto)
    return any(re.search(rf"\b{re.escape(norm(p))}", t) for p in cfg().get("agendar_palabras", ["agendar"]))


def analizar(texto, autor="supervisora", contexto=""):
    """Devuelve ({"intencion", "hallazgos", "pregunta", "observacion"}, motor). Nunca tarda más de ~45 s."""
    c = cfg()
    key = c.get("gemini_api_key", "")
    if key and not key.startswith("PEGA"):
        ctx = f"CONTEXTO (mensaje al que responde o foto adjunta):\n{contexto}\n\n" if contexto else ""
        prompt = PROMPT.format(lista=_lista(), autor=autor, texto=texto[:2500], contexto=ctx)
        t0 = time.time()
        TOPE = 45
        for modelo in c.get("gemini_modelos", ["gemini-2.5-flash"]):
            for intento in range(2):
                quedan = TOPE - (time.time() - t0)
                if quedan < 5:
                    print("[ia] se acabó el tiempo, uso respaldo sin IA")
                    return sin_ia(texto, contexto), "palabras-clave (IA lenta)"
                try:
                    r = _gemini(modelo, prompt, key, timeout=min(30, quedan))
                    for h in r.get("hallazgos", []) or []:
                        if h.get("tipo") not in PAL and h.get("tipo") != "OTRO":
                            h["tipo"] = tipo_por_palabras(h.get("problema", "") + " " + texto)
                    return _normalizar(r, texto), modelo
                except urllib.error.HTTPError as err:
                    print(f"[ia] {modelo} HTTP {err.code}: {err.read().decode(errors='ignore')[:160]}")
                    if err.code in (429, 500, 503) and intento == 0:
                        time.sleep(min(8, max(0, TOPE - (time.time() - t0) - 10)))
                        continue
                    break
                except (urllib.error.URLError, TimeoutError, OSError) as err:
                    print(f"[ia] sin conexión con Gemini ({err}); uso respaldo sin IA")
                    return sin_ia(texto, contexto), "palabras-clave (sin red)"
                except Exception as err:
                    print(f"[ia] {modelo} error: {err}")
                    break
    return sin_ia(texto, contexto), "palabras-clave"


PREGUNTA_RX = (r"\?|^(y )?(que|cuando|cual|quien|como|donde|fueron|vino|vinieron|saben|sabes|alguien sabe|"
               r"hay|se hizo|hicieron|paso|pasaron)\b|\b(se hizo|hicieron|fuiste|fueron|vinieron|cuando vienen|"
               r"cuando van|cuando pasan|que paso|como quedo|quien fue)\b")
RESUELTO_RX = (r"\b(quedo funcionando|ya funciona|funcionando|operativo|solucionado|reparado|arreglado|ya llego|"
               r"llegaron|ya esta|ya quedo|cierran|cierra a las|abren a las|recordar que|aviso que|les aviso)\b")
EMERGENCIA_RX = (r"\b(emergencia|urgente|urgencia|problema con|problemas con|falla|fallando|no funciona|no funcionan|"
                 r"no sirve|no prende|no enciende|se cayo|se rompio|roto|rota|quebrad|danad|malo|mala|ayuda)\b")
CHARLA_RX = r"^(hola|holi|buenos dias|buenas tardes|buenas noches|buenas|gracias|muchas gracias|ok|oki|okey|dale|perfecto|genial|saludos)\b"


def sin_ia(texto, contexto=""):
    """Respaldo sin IA: misma intención y datos usando reglas, alias del panel y palabras clave.
    El contexto (mensaje citado, foto) solo sirve para saber de qué establecimiento hablan."""
    from nucleo import en_texto
    t = norm(texto)
    vacio = {"intencion": "charla", "es_reporte": False, "hallazgos": []}
    if not t or "multimedia omitido" in t or "se elimino este mensaje" in t:
        return vacio
    hits = en_texto(texto) or (en_texto(contexto) if contexto else [])
    tipo = tipo_por_palabras(texto)
    agendar = pide_agendar(texto)
    aviso_falla = re.search(EMERGENCIA_RX, t) and "?" not in texto
    if not agendar and not aviso_falla and re.search(PREGUNTA_RX, t):
        return {"intencion": "pregunta", "es_reporte": False, "hallazgos": [],
                "pregunta": {"rbd": hits[0] if hits else None, "nombre_mencionado": "", "tema": "",
                             "tiempo": "", "sobre": "futuro" if re.search(r"cuando (vienen|van|pasan|viene|va)|proxima", t)
                             else "pasado"}}
    if not agendar and re.search(RESUELTO_RX, t):
        return {"intencion": "observacion" if hits else "charla", "es_reporte": False, "hallazgos": [],
                "observacion": {"rbd": hits[0] if hits else None, "nombre_mencionado": "", "resumen": texto[:90]}}
    if not agendar and re.search(CHARLA_RX, t) and tipo == "OTRO" and not hits:
        return vacio
    def limpio(f):   # "agendar porfa en el 8661 el horno..." -> "en el 8661 el horno..."
        pals = "|".join(re.escape(p) for p in cfg().get("agendar_palabras", ["agendar"]))
        f = re.sub(rf"\b({pals})\b|\b(porfa|por favor|plis|pls)\b", "", f, flags=re.I)
        return re.sub(r"\s+", " ", f).strip(" ,.-")[:90] or f[:90]

    # requerimiento / agendar: separar por frases para no mezclar fallas de distintos establecimientos
    frases = [f for f in re.split(r"[.;\n]|\by en\b|\by el\b|\by la\b|,\s*en\b", texto, flags=re.I) if f and f.strip()]
    hallazgos, vistos = [], set()
    for f in frases:
        for r in en_texto(f):
            if r in vistos:
                continue
            vistos.add(r)
            tf = tipo_por_palabras(f)
            hallazgos.append({"rbd": r, "nombre_mencionado": "", "problema": limpio(f),
                              "tipo": tf if tf != "OTRO" else tipo, "seguro": True})
    for r in hits:
        if r not in vistos and (tipo != "OTRO" or not agendar):
            vistos.add(r)
            hallazgos.append({"rbd": r, "nombre_mencionado": "", "problema": limpio(texto), "tipo": tipo, "seguro": True})
    if agendar and tipo == "OTRO" and not en_texto(texto):
        hallazgos = []                       # "agendar" a secas: se agenda lo ya registrado
    if not hallazgos and tipo != "OTRO":
        m = re.search(r"((?:escuela|esc\.?|liceo|lic\.?|colegio|complejo|jard[ií]n|j\.?i\.?|sala cuna|sc)\s+"
                      r"[^,.;:\n]{2,40}?)(?=\s+(?:tiene|tienen|est[aá]|sigue|hay|con|el|la|los|las|se)\b|[,.;:\n]|$)",
                      texto, re.I)
        if m:
            hallazgos.append({"rbd": None, "nombre_mencionado": m.group(1).strip(), "problema": texto.strip()[:90],
                              "tipo": tipo, "seguro": False})
    if not hallazgos and aviso_falla:
        # "tengo una emergencia en el Vergara Ayares": hay falla aunque no se sepa cuál ni dónde exactamente
        m = re.search(r"\b(?:en|del|de la|en el|en la)\s+(?:el\s+|la\s+)?([^,.;:\n?!]{3,50})$", texto.strip(), re.I)
        nombre = m.group(1).strip() if m else ""
        hallazgos.append({"rbd": hits[0] if hits else None, "nombre_mencionado": nombre,
                          "problema": limpio(texto), "tipo": tipo, "seguro": bool(hits)})
    if agendar:
        return {"intencion": "agendar", "es_reporte": True, "hallazgos": hallazgos}
    if hallazgos and (tipo != "OTRO" or aviso_falla or any(h["tipo"] != "OTRO" for h in hallazgos)):
        return {"intencion": "requerimiento", "es_reporte": True, "hallazgos": hallazgos}
    if hits:
        return {"intencion": "observacion", "es_reporte": False, "hallazgos": [],
                "observacion": {"rbd": hits[0], "nombre_mencionado": "", "resumen": texto[:90]}}
    return vacio


# ---------------------------------------------------------------- texto libre y fotos
def generar(prompt, max_seg=30):
    """Texto libre de Gemini (para redactar respuestas con datos ya buscados). None si no hay IA."""
    c = cfg()
    key = c.get("gemini_api_key", "")
    if not key or key.startswith("PEGA"):
        return None
    cuerpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.2}}
    for modelo in c.get("gemini_modelos", ["gemini-2.5-flash"]):
        for srv in _orden_servidores(key):
            try:
                data = _llamar(srv, modelo, cuerpo, key, timeout=max_seg)
                _bueno["servidor"] = srv
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as e:
                print(f"[ia] generar {srv}/{modelo}: {str(e)[:120]}")
    return None


PROMPT_FOTO = """Eres técnico de mantención de cocinas escolares (SOSER, Chile). Mira la foto que mandó {autor}
{caption}
Responde SOLO este JSON:
{{"que_se_ve": "qué equipo o lugar aparece, máx 12 palabras",
  "falla": "qué problema se ve, o vacío si no se ve ninguno",
  "tipo": "GAS|FRIO|AGUA|ELEC|EQUIPO|OTRO",
  "gravedad": "alta|media|baja|ninguna",
  "materiales": "repuestos o herramientas que convendría llevar, máx 10 palabras, o vacío"}}
No inventes: si no se distingue, dilo en que_se_ve y deja falla vacía."""


def analizar_foto(ruta, autor="", caption=""):
    """Gemini con visión. Devuelve dict o None si no hay IA o falla."""
    import base64, mimetypes
    c = cfg()
    key = c.get("gemini_api_key", "")
    if not key or key.startswith("PEGA") or not c.get("fotos", {}).get("analizar", True):
        return None
    mime = mimetypes.guess_type(ruta)[0] or "image/jpeg"
    with open(ruta, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    texto = PROMPT_FOTO.format(autor=autor or "una supervisora",
                               caption=f'con el texto: "{caption}"' if caption else "(sin texto).")
    cuerpo = {"contents": [{"role": "user", "parts": [{"inline_data": {"mime_type": mime, "data": b64}},
                                                      {"text": texto}]}],
              "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}}
    for modelo in c.get("gemini_modelos", ["gemini-2.5-flash"]):
        for srv in _orden_servidores(key):
            try:
                data = _llamar(srv, modelo, cuerpo, key, timeout=40)
                _bueno["servidor"] = srv
                txt = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                r = json.loads(re.sub(r"^```(?:json)?|```$", "", txt).strip())
                if r.get("tipo") not in PAL and r.get("tipo") != "OTRO":
                    r["tipo"] = tipo_por_palabras(r.get("falla", "") + " " + r.get("que_se_ve", ""))
                return r
            except Exception as e:
                print(f"[ia] foto {srv}/{modelo}: {str(e)[:120]}")
    return None
