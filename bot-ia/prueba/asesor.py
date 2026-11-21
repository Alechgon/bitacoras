"""
ASESOR CONVERSACIONAL de la licitación 85-34-LR25 (IA de prueba).

Conversa como un colega: le cuentas el problema ("tengo un vidrio roto en el República de Haití"), te pregunta lo
que necesita para entender el caso ("¿sabes cómo se rompió?"), llega a quién le corresponde y te ofrece el porqué.
Si dices que sí, te manda la explicación POR ESCRITO con las frases tal cual de las Bases / SGC y su página
(sirve para reenviarla al director o al sostenedor).

Cómo piensa:
  - Las fichas (fichas.py) dicen qué preguntar y a qué se llega según la respuesta, todo apoyado en la licitación.
  - La IA del celular (Qwen) entiende tus respuestas aunque no uses las palabras exactas y redacta natural.
    Si la IA se pone creativa (cambia la conclusión o inventa números), se usa el texto de la ficha.
  - Si preguntas otra cosa (multas, plazos, auditorías…), busca en los documentos y te responde corto; el
    detalle con páginas te lo da si se lo pides.

Archivos (Descargas/SOSER-prueba):
  .asesor.json               la conversación en curso (se olvida sola a los 30 min)
  conversaciones/AAAA-MM-DD.md  todo lo conversado (para revisar)
  asesor_correcciones.jsonl  cuando le dices "está mal, …"

Prueba en Termux:  python asesor.py "tengo un vidrio roto en el republica de haiti"   (y luego: python asesor.py "lo rompio un alumno")
                   python asesor.py --nueva     (olvida la conversación)
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.dirname(AQUI))

import fichas as F  # noqa: E402
import licitacion as L  # noqa: E402

VIDA = 30 * 60
USAR_IA = True          # False = solo textos de las fichas (más rápido, más "mecánico")
MAX_REPREGUNTAS = 1     # si no entiende la respuesta, pregunta de nuevo 1 vez; después sigue con "no se sabe"

SI = r"^\s*(si+|sí+|sip|sipo|dale|ya+|ya po|bueno|ok|okey|okay|porfa|por favor|claro|obvio|de una|comparte\w*|mand\w*|" \
     r"muestr\w*|explica\w*|quiero|me sirve|si porfa|si gracias|por que|porque|el porque)\b"
NO = r"^\s*(no+|nop|nah|no gracias|despues|tranqui|asi esta bien|no es necesario|gracias|listo|vale gracias)\b"
NUEVA = r"^\s*(nueva|otra consulta|otra cosa|olvida\w*|reset|reinicia\w*|empecemos de nuevo|cambio de tema)\b"
CORRIGE = r"^\s*(esta mal|eso esta mal|no es asi|te equivocas|te equivocaste|error|incorrecto|corrige\w*|mal ahi)\b"
PIDE_DECISION = (r"\b(corresponde\w*|le toca|nos toca|toca a|quien (paga|ve|arregla|repara|cambia|se hace cargo)|de quien|"
                 r"responsab\w*|hay que (cambiar|reparar|arreglar|reponer)|necesito (cambiar|reparar|arreglar|reponer)|"
                 r"se (rompio|quebro|echo a perder|cayo|tapo|corto|solto)|rot[oa]s?|quebrad[oa]|mal[oa] |no funciona|"
                 r"no anda|no prende|falla\w*|danad\w*|dano\w*|tengo un|tengo una|hay un|hay una)\b")


# ================================================================ utilidades
def norm(s):
    return L.norm(s)


def _base():
    return L._base()


def _estado_p():
    return os.path.join(_base(), ".asesor.json")


def estado():
    try:
        e = json.load(open(_estado_p(), encoding="utf-8"))
        if time.time() - e.get("t", 0) < VIDA:
            return e
    except Exception:
        pass
    return {}


def guardar(e):
    e["t"] = time.time()
    os.makedirs(_base(), exist_ok=True)
    json.dump(e, open(_estado_p(), "w", encoding="utf-8"), ensure_ascii=False)


def olvidar():
    try:
        os.remove(_estado_p())
    except OSError:
        pass


def activa():
    return bool(estado())


def registrar(quien, texto):
    d = os.path.join(_base(), "conversaciones")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, datetime.now().strftime("%Y-%m-%d") + ".md"), "a", encoding="utf-8") as f:
        f.write(f"**{quien}** ({datetime.now():%H:%M}): {texto}\n\n")


def ollama(prompt, n=200, temp=0.3, timeout=180):
    req = urllib.request.Request(L.OLLAMA + "/api/generate", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"model": L.MODELO, "prompt": prompt, "stream": False, "keep_alive": "15m",
                                                  "options": {"temperature": temp, "num_ctx": 4096, "num_predict": n}}).encode())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()).get("response", "").strip()


# ================================================================ establecimiento
def establecimiento(texto):
    """(rbd, nombre, tipo) si en el texto viene un colegio/jardín conocido."""
    try:
        import nucleo
        hits = nucleo.en_texto(texto)
        if not hits:
            return None
        e = nucleo.datos()["E"][int(hits[0])]
        tipo = "colegio" if norm(e.get("inst")) == "junaeb" else "jardin" if e.get("inst") else ""
        nombre = " ".join(w if w in ("de", "del", "la", "las", "los", "el", "y") else w.capitalize()
                          for w in e["nombre"].lower().split())
        return {"rbd": e["rbd"], "nombre": nombre, "tipo": tipo, "inst": e.get("inst", "")}
    except Exception:
        return None


# ================================================================ entender respuestas
def _opciones(p):
    return p["opciones"]


def por_palabras(p, texto):
    """Opción que calza por palabras clave ('nose' solo si no calza otra)."""
    t = norm(texto)
    nose_rx = _opciones(p).get("nose", (None, None))[1]
    t_sin = re.sub(nose_rx, " ", t) if nose_rx else t
    for val, (_, rx) in _opciones(p).items():
        if val != "nose" and re.search(rx, t_sin):
            return val
    if nose_rx and re.search(nose_rx, t):
        return "nose"
    return None


def por_ia(p, texto):
    """La IA elige la opción cuando las palabras no alcanzan."""
    if not USAR_IA:
        return None
    ops = [(v, d) for v, (d, _) in _opciones(p).items()]
    letras = "ABCDEFGH"
    lista = "\n".join(f"{letras[i]}) {d}" for i, (_, d) in enumerate(ops))
    prompt = (f"Pregunté: «{p['texto']}»\nMe respondieron: «{texto}»\n\n¿Qué opción describe mejor la respuesta?\n{lista}\n"
              f"Z) ninguna, no responde la pregunta\n\nResponde SOLO con la letra.\nLetra:")
    try:
        r = ollama(prompt, n=4, temp=0)
    except Exception:
        return None
    m = re.search(r"[A-HZ]", r.upper())
    if not m or m.group(0) == "Z":
        return None
    i = letras.index(m.group(0))
    return ops[i][0] if i < len(ops) else None


def llenar(e, ficha, texto, pendiente=None, corrigiendo=False):
    """Saca de lo que escribiste todos los datos que se puedan (no solo la pregunta pendiente).
    Un dato ya sabido solo se cambia si es lo que pregunté o si me estás corrigiendo después de concluir.
    Devuelve (cambios, reconocidos)."""
    cambios, reconocidos = {}, {}
    preguntas = [(sid, p) for sid, p in F.GLOBAL.items()] + [(p["id"], p) for p in ficha["preguntas"]]
    for sid, p in preguntas:
        v = por_palabras(p, texto)
        if v is None and sid == pendiente:
            v = por_ia(p, texto)
        if not v or (v == "nose" and sid != pendiente):
            continue
        reconocidos[sid] = v
        actual = e["datos"].get(sid)
        if actual == v:
            continue
        if actual is None or sid == pendiente or corrigiendo:
            cambios[sid] = v
    e["datos"].update(cambios)
    return cambios, reconocidos


# ================================================================ razonar con la ficha
def _todas_preguntas(ficha):
    d = {p["id"]: p for p in ficha["preguntas"]}
    for k, p in F.GLOBAL.items():
        d.setdefault(k, p)
    return d


def _valor(e, sid):
    v = e["datos"].get(sid)
    if v is None and sid in F.GLOBAL and "defecto" in F.GLOBAL[sid]:
        return F.GLOBAL[sid]["defecto"]
    return v


def decidir(e, ficha):
    """('concluir', conclusion) o ('preguntar', id_pregunta)."""
    preg = _todas_preguntas(ficha)
    for c in ficha["conclusiones"]:
        falta, choca = None, False
        for sid, quiere in c["si"].items():
            v = _valor(e, sid)
            quiere = quiere if isinstance(quiere, (list, tuple)) else [quiere]
            if v is None:
                p = preg.get(sid, {})
                if all(_valor(e, k) == val for k, val in p.get("cuando", {}).items()) \
                        and e["preguntadas"].get(sid, 0) <= MAX_REPREGUNTAS:
                    falta = falta or sid
                else:
                    choca = True             # no se pudo saber: esta conclusión no aplica
            elif v not in quiere:
                choca = True
        if choca:
            continue
        if falta:
            return "preguntar", falta
        return "concluir", c
    return "concluir", ficha["conclusiones"][-1]


def elegir_ficha(texto):
    t = norm(texto)
    mejor, n = None, 0
    for f in F.TEMAS:
        k = len(re.findall(f["claves"], t))
        if k > n:
            mejor, n = f, k
    return mejor


def ficha_por_id(fid):
    if fid == "general":
        return F.GENERAL
    return next((f for f in F.TEMAS if f["id"] == fid), F.GENERAL)


# ================================================================ hablar natural
ESTILO = ("Eres SOSER-IA, colega del jefe de mantención de SOSER (empresa que da la alimentación escolar PAE). "
          "Hablas por WhatsApp en español de Chile: cercano, directo, sin listas, sin títulos, sin emojis de más.")


def _numeros(s):
    return set(re.findall(r"\d+", s))


def natural(base, dijo, debe_contener=None, es_pregunta=False):
    """La IA lo dice con sus palabras; si se arranca (cambia la conclusión, inventa números, se alarga), va el texto base."""
    if not USAR_IA:
        return base
    prompt = (f"{ESTILO}\n\nÉl te escribió: «{dijo}»\n\nTEXTO BASE (lo que tienes que decir):\n{base}\n\n"
              "Reescríbelo con tus palabras, natural y breve (1 a 3 frases). No agregues datos, números, plazos, "
              "nombres ni lugares que no estén en el TEXTO BASE. "
              + ("Termina con la pregunta. " if es_pregunta else "")
              + "\nTU MENSAJE:")
    try:
        r = ollama(prompt, n=160, temp=0.4, timeout=120)
    except Exception:
        return base
    r = re.sub(r"^(tu mensaje|mensaje|respuesta)\s*:\s*", "", r.strip().strip('"«»'), flags=re.I).strip()
    ok = (20 < len(r) <= max(len(base) * 1.6, 160)
          and _numeros(r) <= _numeros(base + " " + dijo)
          and (not es_pregunta or r.rstrip().endswith("?"))
          and not re.search(r"(?i)\b(como (ia|modelo)|no puedo|lo siento)\b", r)
          and all(norm(x) in norm(r) for x in (debe_contener or [])))
    return r if ok else base


# ================================================================ el porqué, por escrito
_PAGS = {}


def _paginas():
    if not _PAGS:
        import glob
        import gzip
        for f in glob.glob(os.path.join(AQUI, "documentos_texto", "*.jsonl.gz")):
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                for x in fh:
                    d = json.loads(x)
                    k = (d["doc"], d["pagina"])
                    _PAGS[k] = (_PAGS.get(k, "") + " " + re.sub(r"\s+", " ", d["texto"])).strip()
    return _PAGS


def textual(c):
    """La frase TAL CUAL del documento, desde 'inicio' hasta el punto (máx. ~650 caracteres)."""
    if c.get("texto"):
        return c["texto"]
    t = _paginas().get((c["doc"], c["pag"]), "")
    i = t.find(c["inicio"])
    if i < 0:
        i = norm(t).find(norm(c["inicio"]))
    if i < 0:
        return ""
    resto = t[i:]
    m = re.search(r"\.(?=\s+[A-ZÁÉÍÓÚÑ•o0-9]|\s*$)", resto[60:])
    fin = 60 + m.end() if m else len(resto)
    frase = resto[:min(fin, 650)].strip()
    return frase + ("…" if fin > 650 else "")


def citas_para(c, tipo):
    return [x for x in c.get("citas", []) if not x.get("tipo") or not tipo or x["tipo"] == tipo]


def porque(e):
    c = next((x for x in ficha_por_id(e["ficha"])["conclusiones"] if x["id"] == e["conclusion"]), None)
    if not c:
        return "No tengo a mano la conclusión anterior. ¿Me cuentas de nuevo el caso?"
    tipo = e["datos"].get("tipo")
    lugar = (e.get("est") or {}).get("nombre", "")
    q = c["quien"]
    cab = (f"📄 *Por qué {q}*" if norm(q).startswith(("depende", "ojo", "los dos"))
           else f"📄 *Por qué le toca al {q[3:]}*" if q.startswith("el ") else f"📄 *Por qué le toca a {q}*")
    tema = ficha_por_id(e["ficha"])["nombre"] if e["ficha"] != "general" else "«" + e.get("inicio", "")[:70] + "»"
    sub = " · ".join(x for x in (tema, lugar,
                                 {"colegio": "colegio JUNAEB", "jardin": "jardín JUNJI/INTEGRA"}.get(tipo, "")) if x)
    lin = [cab, f"_{sub}_" if sub else "", "", "Según la licitación ID 85-34-LR25:", ""]
    n = 0
    for x in citas_para(c, tipo):
        frase = textual(x)
        if not frase:
            continue
        n += 1
        donde = f"{F.NOMBRES_DOC.get(x['doc'], x['doc'])}, pág. {x['pag']}"
        lin.append(f"{n}. *{donde}*" + (f" ({x['titulo']})" if x.get("titulo") else "") + f":\n«{frase}»\n")
    lin.append(f"*En simple:* {c['corto']}")
    if c.get("nota"):
        lin.append(f"*Ojo:* {c['nota']}")
    if c.get("criterio"):
        lin.append("*Ojo:* esto es criterio de mantención de SOSER aplicando esas reglas; la licitación no nombra este caso con esas palabras.")
    if c.get("hacer"):
        lin.append(f"*Qué hacer:* {c['hacer']}")
    return "\n".join(x for x in lin if x is not None).replace("\n\n\n", "\n\n")


# ================================================================ preguntas libres (multas, plazos, etc.)
def libre(texto, e):
    trozos = L.indice().buscar(texto, k=4)
    if not trozos:
        return "Eso no lo encuentro en los documentos de la licitación. ¿Me lo dices de otra forma?"
    extractos = "\n\n".join(f"{L.cita(d)} {re.sub(r'\s+', ' ', d['texto'])[:1100]}" for d in trozos)
    base = ""
    if USAR_IA:
        prompt = (f"{ESTILO}\n\nEXTRACTOS DE LA LICITACIÓN:\n{extractos}\n\nPREGUNTA: {texto}\n\n"
                  "Responde en 2 o 3 frases usando SOLO los extractos, como colega. Si no está en los extractos, di que no "
                  "lo encuentras. Sin citas, sin listas.\nRESPUESTA:")
        try:
            base = ollama(prompt, n=220, temp=0.2, timeout=300)
        except Exception:
            base = ""
        if base and not _numeros(base) <= _numeros(extractos + texto):
            base = ""                      # inventó un número: mejor no
    if not base:
        base = f"Lo más cercano que encuentro es esto: «{_mejores_frases(trozos[0]['texto'], texto, 1)[:350]}»"
    e.update(ficha=None, conclusion=None, fase="ofrecido_libre", trozos=[
        {k: d[k] for k in ("doc", "archivo", "pagina", "texto")} for d in trozos[:3]], pregunta_libre=texto)
    return base + "\n\n¿Quieres que te muestre de dónde sale?"


def _limpio(s):
    s = re.sub(r"^\[[^\]]*\]\s*", "", s.strip())            # "[título]" que se repite en la guía
    s = re.sub(r"#+\s*|\*\*|\|---[|-]*|\|", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _mejores_frases(texto, pregunta, n=2):
    q = set(L.tokens(pregunta))
    frases = [f for f in re.split(r"(?<=\.)\s+|\n", texto) if len(_limpio(f)) > 25]
    if not frases:
        return _limpio(texto)[:500]
    mejor = sorted(range(len(frases)), key=lambda j: -len(q & set(L.tokens(frases[j]))))[:n]
    return " … ".join(_limpio(frases[j]) for j in sorted(mejor))


def porque_libre(e):
    lin = ["📄 *De dónde sale* (licitación ID 85-34-LR25)", ""]
    for i, d in enumerate(e.get("trozos", []), 1):
        sel = _mejores_frases(d["texto"], e.get("pregunta_libre", ""))[:600]
        donde = L.cita(d).strip("[]")
        if d["doc"] == "GUÍA":
            donde += " (guía interna, resume las bases con su página)"
        lin.append(f"{i}. *{donde}*:\n«{sel}»\n")
    return "\n".join(lin)


# ================================================================ la conversación
def _intro(e, ficha):
    est = e.get("est") or {}
    if est.get("nombre"):
        return f"Ya, {ficha['nombre']} en el {est['nombre']}."
    return f"Ya, {ficha['nombre']}." if ficha["id"] != "general" else "Ya."


def _preguntar(e, ficha, sid, dijo, intro="", no_entendi=False):
    p = _todas_preguntas(ficha)[sid]
    veces = e["preguntadas"].get(sid, 0)
    e["preguntadas"][sid] = veces + 1
    e["pendiente"], e["fase"] = sid, "preguntando"
    base = "No te pillé bien. " + p["texto"] if (veces and no_entendi) else p["texto"]
    return natural((intro + " " + base).strip(), dijo, es_pregunta=True)


def _concluir(e, c, dijo, intro=""):
    e.update(conclusion=c["id"], fase="ofrecido", pendiente=None)
    quien = c["quien"]
    base = (intro + " " + c["corto"]).strip()
    clave = [w for w in ("soser", "sostenedor", "establecimiento", "nosotros", "depende") if w in norm(c["corto"])][:1]
    txt = natural(base, dijo, debe_contener=clave)
    return f"{txt}\n\n👉 *Le toca a: {quien}*\n¿Quieres que te comparta el porqué?"


def avanzar(e, dijo, intro="", no_entendi=False):
    ficha = ficha_por_id(e["ficha"])
    accion, x = decidir(e, ficha)
    if accion == "preguntar":
        return _preguntar(e, ficha, x, dijo, intro, no_entendi)
    return _concluir(e, x, dijo, intro)


def nuevo_caso(texto, ficha, previo=None):
    e = {"ficha": ficha["id"], "datos": {}, "preguntadas": {}, "pendiente": None, "fase": "", "inicio": texto}
    est = establecimiento(texto) or (previo or {}).get("est")       # si no nombras otro, sigue el mismo establecimiento
    if est:
        e["est"] = est
        if est.get("tipo"):
            e["datos"]["tipo"] = est["tipo"]
    elif (previo or {}).get("datos", {}).get("tipo"):
        e["datos"]["tipo"] = previo["datos"]["tipo"]
    llenar(e, ficha, texto)
    return e


def conversar(texto, libre_msg=False):
    """Un mensaje tuyo -> la respuesta de la IA (texto para WhatsApp)."""
    texto = (texto or "").strip()
    if not texto:
        return ""
    registrar("Tú", texto)
    t = norm(texto)
    e = estado()

    if re.search(NUEVA, t):
        olvidar()
        r = "Listo, empecemos de cero. ¿Qué pasó?"
    elif e and re.search(CORRIGE, t):
        with open(os.path.join(_base(), "asesor_correcciones.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "texto": texto, "estado": e}, ensure_ascii=False) + "\n")
        r = ("Anotado 👍 Lo dejo para revisar la ficha. Si me dices cómo es en la práctica, también lo anoto "
             "(empieza con \"está mal, …\").")
        guardar(e)
    elif e.get("fase") in ("ofrecido", "ofrecido_libre") and re.search(SI, t) and len(t.split()) <= 6:
        r = porque(e) if e["fase"] == "ofrecido" else porque_libre(e)
        e["fase"] = "explicado"
        guardar(e)
    elif e.get("fase") in ("ofrecido", "ofrecido_libre", "explicado") and re.search(NO, t) and len(t.split()) <= 5 \
            and not re.search(F.NOSE[1], t):
        r = "Dale 👍 Cualquier otra cosa me dices."
        e["fase"] = "cerrado"
        guardar(e)
    elif e.get("fase") in ("ofrecido", "explicado") and re.search(F.NOSE[1], t) and len(t.split()) <= 5:
        r = "Dale. Cuando sepas más me cuentas y lo vemos 👍"
        e["fase"] = "cerrado"
        guardar(e)
    elif e.get("fase") in ("explicado", "cerrado", None, "") and len(t.split()) <= 3 and (re.search(SI, t) or re.search(NO, t)
                                                                                      or re.search(r"^\s*(perfecto|buena|vale|bacan|genial|gracias)", t)):
        r = "👍"                            # "dale", "gracias", "ok" cuando no hay nada pendiente
    else:
        r = _responder(texto, e)
    registrar("IA", r)
    return r


def _responder(texto, e):
    t = norm(texto)
    ficha_txt = elegir_ficha(texto)
    # ¿responde a lo que pregunté?
    if e.get("fase") == "preguntando" and e.get("ficha"):
        ficha = ficha_por_id(e["ficha"])
        cambios, _ = llenar(e, ficha, texto, pendiente=e["pendiente"])
        if cambios or not (ficha_txt and ficha_txt["id"] != ficha["id"] and len(t.split()) > 4):
            r = avanzar(e, texto, no_entendi=not cambios)
            guardar(e)
            return r
    # ¿corrige o agrega un dato del caso ya concluido? ("en realidad lo rompió la manipuladora")
    if e.get("ficha") and e.get("fase") in ("ofrecido", "explicado", "cerrado") and not (ficha_txt and ficha_txt["id"] != e["ficha"]):
        ficha = ficha_por_id(e["ficha"])
        antes = e.get("conclusion")
        cambios, reconocidos = llenar(e, ficha, texto, corrigiendo=True)
        if cambios:
            accion, x = decidir(e, ficha)
            intro = "Ah, eso cambia la cosa." if accion == "preguntar" or x["id"] != antes else "Igual queda en lo mismo."
            r = avanzar(e, texto, intro)
            guardar(e)
            return r
        if reconocidos:
            guardar(e)
            return "Sí, eso ya lo tenía considerado 👍 ¿Te comparto el porqué?" if e["fase"] == "ofrecido" else \
                "Sí, eso ya lo tenía considerado 👍"
    # caso nuevo
    if ficha_txt or re.search(PIDE_DECISION, t):
        ficha = ficha_txt or F.GENERAL
        cambia = bool(e.get("ficha"))
        e = nuevo_caso(texto, ficha, previo=e)
        r = avanzar(e, texto, ("Ah, entonces es otro tema: " + ficha["nombre"] + ".") if cambia and ficha["id"] != "general"
                    else _intro(e, ficha))
        guardar(e)
        return r
    # pregunta libre sobre la licitación (si no parece pregunta, mejor preguntar qué necesita)
    if len(t.split()) < 4 and "?" not in texto and not re.search(
            r"\b(cual|cuanto|cuantos|cuantas|que|como|cuando|donde|quien|puedo|se puede|hay que|plazo|multa)\b", t):
        return "No te pillé 🤔 ¿Me cuentas qué pasó o qué quieres saber de la licitación?"
    e = {"datos": {}, "preguntadas": {}}
    r = libre(texto, e)
    guardar(e)
    return r


# ================================================================ prueba
if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--nueva":
        olvidar()
        print("Conversación olvidada.")
    elif a and a[0] == "--sin-ia":
        USAR_IA = False
        print(conversar(" ".join(a[1:])))
    elif a:
        print(conversar(" ".join(a)))
    else:
        print(__doc__)
