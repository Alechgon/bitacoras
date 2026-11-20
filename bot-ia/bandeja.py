"""
Rama BANDEJA del bot SOSER.

Todo lo que Manuel manda al grupo bandeja (texto, foto, audio, PDF) se entiende, se clasifica y se archiva:
  - audio  -> whisper.cpp -> texto
  - foto   -> se guarda; si es un documento, tesseract saca su texto
  - PDF    -> pdftotext
  - texto  -> reglas (colegio, técnico, supervisora, fecha) + IA local (categoría y resumen)
Queda en Descargas/SOSER/Colegios/<colegio>/<fecha hora categoría>/ y en Trabajos/registro.xlsx.

Nada de esto toca Datácora ni el repositorio: todo vive en el celular.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.request
from datetime import date, datetime, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

CATS = ["Emergencia", "Correctiva", "Preventiva", "Compra", "Pendiente", "Nota"]
ICONO = {"Emergencia": "🚨", "Correctiva": "🔧", "Preventiva": "🧰", "Compra": "🛒", "Pendiente": "📌", "Nota": "📝"}
MIN_JUNTAR = 10            # fotos/audios sueltos se juntan con el trabajo de los últimos 10 min
LOCK = threading.Lock()
WHISPER = os.path.expanduser("~/whisper.cpp")
OLLAMA = "http://127.0.0.1:11434"


# ------------------------------------------------------------------ carpetas y registro
def base():
    for b in (os.path.expanduser("~/storage/downloads"), os.path.expanduser("~/storage/shared/Download")):
        if os.path.isdir(b):
            return os.path.join(b, "SOSER")
    return os.path.expanduser("~/SOSER")


def _ruta(*p):
    r = os.path.join(base(), *p)
    os.makedirs(os.path.dirname(r) if os.path.splitext(r)[1] else r, exist_ok=True)
    return r


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _limpio(s):
    return re.sub(r'[\\/:*?"<>|]+', " ", str(s)).strip()[:80]


def leer():
    p = _ruta("Trabajos", "registro.jsonl")
    if not os.path.exists(p):
        return []
    out = []
    for linea in open(p, encoding="utf-8"):
        try:
            out.append(json.loads(linea))
        except Exception:
            pass
    return out


def guardar(items):
    p = _ruta("Trabajos", "registro.jsonl")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    os.replace(p + ".tmp", p)
    _excel(items)


def _excel(items):
    """Trabajos/registro.xlsx: una fila por trabajo (se rehace entero, son pocos)."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except Exception:
        return
    wb = Workbook()
    ws = wb.active
    ws.title = "Trabajos"
    cols = ["#", "Fecha", "Hora", "Categoría", "Colegio", "RBD", "Técnico", "Supervisora", "Para el",
            "Resumen", "Texto", "Archivos", "Estado", "Carpeta"]
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
    for it in items:
        if it.get("estado") == "borrado":
            continue
        ws.append([it["id"], it["fecha"], it["hora"], it["categoria"], it.get("colegio", ""), it.get("rbd", ""),
                   it.get("tecnico", ""), it.get("supervisora", ""), it.get("para", ""), it.get("resumen", ""),
                   it.get("texto", "")[:500], len(it.get("archivos", [])), it.get("estado", "abierto"),
                   it.get("carpeta", "")])
    for col, ancho in zip("ABCDEFGHIJKLMN", (5, 11, 6, 12, 28, 8, 10, 18, 10, 40, 60, 8, 9, 50)):
        ws.column_dimensions[col].width = ancho
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    p = _ruta("Trabajos", "registro.xlsx")
    try:
        wb.save(p + ".tmp.xlsx")
        os.replace(p + ".tmp.xlsx", p)
    except Exception:
        pass


def _espera():
    p = _ruta("Trabajos", ".espera.json")
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return []


def _espera_guardar(x):
    json.dump(x, open(_ruta("Trabajos", ".espera.json"), "w", encoding="utf-8"), ensure_ascii=False)


# ------------------------------------------------------------------ sacar texto de audios, fotos y PDF
def _correr(cmd, seg):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=seg)
        return r.stdout or ""
    except Exception:
        return ""


def transcribir(ruta):
    cli = os.path.join(WHISPER, "build", "bin", "whisper-cli")
    modelo = next((os.path.join(WHISPER, "models", f"ggml-{m}.bin") for m in ("small", "base")
                   if os.path.exists(os.path.join(WHISPER, "models", f"ggml-{m}.bin"))), None)
    if not (os.path.exists(cli) and modelo):
        return ""
    wav = ruta + ".wav"
    _correr(["ffmpeg", "-y", "-loglevel", "error", "-i", ruta, "-ar", "16000", "-ac", "1", wav], 120)
    if not os.path.exists(wav):
        return ""
    pista = ("Mantención SOSER. Técnicos Camilo y Rodrigo. Supervisoras Annahi, Stephania y Carla. "
             "Ruta, verificadores, bitácora, emergencia, colegio, jardín, cocina, horno, termopar.")
    txt = _correr([cli, "-m", modelo, "-l", "es", "-nt", "-t", "4", "--prompt", pista, "-f", wav], 600)
    try:
        os.remove(wav)
    except Exception:
        pass
    return re.sub(r"\s+", " ", txt).strip()


def ocr(ruta):
    txt = _correr(["tesseract", ruta, "stdout", "-l", "spa"], 120)
    txt = re.sub(r"[ \t]+", " ", txt).strip()
    palabras = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{3,}", txt)
    return txt if len(palabras) >= 6 else ""          # foto de un equipo: casi no hay texto -> se ignora


def pdf_texto(ruta):
    return re.sub(r"[ \t]+", " ", _correr(["pdftotext", "-l", "3", ruta, "-"], 60)).strip()


# ------------------------------------------------------------------ entender
CLAVES = [
    ("Emergencia", r"\b(emergencia|urgente|urgencia|fuga|olor a gas|huele a gas|inunda\w*|corto ?circuito|sin luz|"
                   r"sin gas|sin agua|no hay (luz|gas|agua)|se corto (la luz|el gas|el agua)|incendio|humo|chispa\w*|"
                   r"electrocut\w*|peligro)\b"),
    ("Compra", r"\b(comprar|compra|cotiza\w*|cotizacion|presupuesto|oc|orden de compra|factura\w*|pre-?oc|"
               r"repuesto\w*|\$ ?\d)"),
    ("Preventiva", r"\b(preventiv\w*|mantencion|limpieza|revision|inspeccion|chequeo|pintura|pintar)\b"),
    ("Correctiva", r"\b(no prende|no enciende|no funciona|no anda|no calienta|no enfria|roto|rota|se rompio|falla\w*|"
                   r"reparar|cambiar|cambio de|gotea|filtra|tapad\w*|quemad\w*|malo|mala)\b"),
    ("Pendiente", r"\b(pendiente|falta|faltan|hay que|recordar|acordarse|ver lo de|revisar despues)\b"),
]


def _tecnicos():
    try:
        import nucleo
        return {k.lower(): v.get("nombre", k).split()[0] for k, v in nucleo.datos()["META"]["tecnicos"].items()}
    except Exception:
        return {"camilo": "Camilo", "rodrigo": "Rodrigo"}


def reglas(texto):
    t = norm(texto)
    out = {"categoria": None, "rbds": [], "tecnico": "", "supervisora": "", "para": ""}
    for cat, rx in CLAVES:
        if re.search(rx, t):
            out["categoria"] = cat
            break
    try:
        import nucleo
        out["rbds"] = [str(r) for r in nucleo.en_texto(texto)]
    except Exception:
        pass
    for k, nom in _tecnicos().items():
        if re.search(rf"\b{k}\b", t):
            out["tecnico"] = nom
            break
    try:
        import datacora
        s = datacora.sup_en_texto(t) if hasattr(datacora, "sup_en_texto") else None
        if not s and out["rbds"]:
            s = datacora._sup_de_rbd().get(out["rbds"][0], "")
        out["supervisora"] = s or ""
        if datacora.tiene_fecha(t):
            d, _, _ = datacora._rango(t, datacora.ahora().date(), futuro=True)
            out["para"] = d.isoformat()
    except Exception:
        pass
    return out


def _ejemplos(n=8):
    p = _ruta("Trabajos", "ejemplos_ia.jsonl")
    if not os.path.exists(p):
        return []
    xs = []
    for linea in open(p, encoding="utf-8"):
        try:
            xs.append(json.loads(linea))
        except Exception:
            pass
    return xs[-n:]


def _modelo():
    try:
        c = json.load(open(os.path.expanduser("~/.datacora.json"), encoding="utf-8"))
        m = c.get("ollama_modelo") or "qwen2.5:1.5b"
        return "qwen2.5:1.5b" if m == "soser" else m
    except Exception:
        return "qwen2.5:1.5b"


def ia(texto):
    """IA local: categoría + resumen corto + equipo. Si Ollama no está, devuelve {}."""
    ej = "\n".join(f'Texto: {e["texto"][:200]}\nJSON: {json.dumps({"categoria": e["categoria"], "resumen": e.get("resumen", "")}, ensure_ascii=False)}'
                   for e in _ejemplos())
    prompt = (
        "Eres el asistente de mantención de SOSER (cocinas de colegios en Santiago, Chile). "
        "Clasifica la nota de trabajo y responde SOLO un JSON con: "
        '"categoria" (una de: Emergencia, Correctiva, Preventiva, Compra, Pendiente, Nota), '
        '"resumen" (máximo 10 palabras, qué pasa o qué hay que hacer), '
        '"equipo" (el equipo involucrado, ej. horno, cocina, campana, refrigerador; vacío si no hay).\n'
        "Emergencia = riesgo o servicio detenido (gas, electricidad, agua). Correctiva = algo malo que reparar. "
        "Preventiva = mantención programada. Compra = comprar, cotizar, OC o factura. "
        "Pendiente = algo por hacer o recordar. Nota = información.\n"
        + (f"Ejemplos corregidos por Manuel:\n{ej}\n" if ej else "")
        + f"Texto: {texto[:1500]}\nJSON:")
    try:
        req = urllib.request.Request(OLLAMA + "/api/generate", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"model": _modelo(), "prompt": prompt, "stream": False,
                                                      "format": "json", "keep_alive": "10m",
                                                      "options": {"temperature": 0.1}}).encode())
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.loads(json.loads(r.read()).get("response", "{}"))
        cat = next((c for c in CATS if norm(c) == norm(out.get("categoria", ""))), None)
        return {"categoria": cat, "resumen": str(out.get("resumen", "")).strip()[:120],
                "equipo": str(out.get("equipo", "")).strip()[:40]}
    except Exception:
        return {}


def _colegio(rbd):
    try:
        import nucleo
        e = nucleo.datos()["E"].get(int(rbd)) or {}
        return e.get("nombre") or f"RBD {rbd}"
    except Exception:
        return f"RBD {rbd}"


PREGUNTA = re.compile(r"(\?|^\s*(y\s+)?(ahi\s+)?(cual|cuales|que|donde|cuando|como|cuanto|cuantos|dame|mandame|"
                      r"pasame|necesito|quiero|muestrame|dime)\b)")


def consulta(texto):
    """Si el mensaje PREGUNTA algo de Datácora (ruta, dónde está, qué hizo, verificadores), lo responde."""
    t = norm(texto)
    if not t or not PREGUNTA.search(t):
        return None
    try:
        import datacora
        if datacora.PATRON.search(t):
            return datacora.responder(texto + "!", "Manuel", None, quien="bandeja")
        # la IA "soser" traduce frases sueltas a un comando ("qué anda haciendo el camilo" -> donde esta camilo!)
        req = urllib.request.Request(OLLAMA + "/api/generate", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"model": "soser", "prompt": texto[:300], "stream": False,
                                                      "keep_alive": "10m"}).encode())
        with urllib.request.urlopen(req, timeout=60) as r:
            cmd = norm(json.loads(r.read()).get("response", "")).strip().splitlines()[0:1]
        cmd = cmd[0] if cmd else ""
        if cmd and "no_entendi" not in cmd and datacora.PATRON.search(cmd):
            return datacora.responder(cmd if cmd.endswith("!") else cmd + "!", "Manuel", None, quien="bandeja")
    except Exception:
        return None
    return None


def _fiel(resumen, texto):
    """El resumen tiene que compartir palabras con el texto; si no, la IA lo inventó."""
    if not resumen:
        return False
    a = {w for w in re.findall(r"[a-z]{4,}", norm(resumen))}
    b = {w for w in re.findall(r"[a-z]{4,}", norm(texto))}
    return len(a & b) >= max(1, len(a) // 3)


# ------------------------------------------------------------------ archivar
def _carpeta_item(it):
    stamp = f'{it["fecha"]} {it["hora"].replace(":", "")} {it["categoria"]}'
    if it.get("rbd"):
        return os.path.join("Colegios", _limpio(f'{it["colegio"]} ({it["rbd"]})'), stamp)
    return os.path.join("Bandeja", stamp)


def _mover(ruta, carpeta_rel):
    if not ruta or not os.path.exists(ruta):
        return None
    dest_dir = _ruta(carpeta_rel)
    os.makedirs(dest_dir, exist_ok=True)
    nombre = os.path.basename(ruta)
    nombre = re.sub(r"^\d{10,}_", "", nombre)
    dest = os.path.join(dest_dir, nombre)
    k = 2
    while os.path.exists(dest):
        b, e = os.path.splitext(nombre)
        dest = os.path.join(dest_dir, f"{b} ({k}){e}")
        k += 1
    shutil.move(ruta, dest)
    return os.path.relpath(dest, base())


def _nota(it):
    p = _ruta(it["carpeta"], "nota.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(f'# #{it["id"]} · {it["categoria"]} · {it.get("colegio") or "sin colegio"}\n\n')
        f.write(f'- Fecha: {it["fecha"]} {it["hora"]}\n')
        for k, lbl in (("resumen", "Resumen"), ("equipo", "Equipo"), ("tecnico", "Técnico"),
                       ("supervisora", "Supervisora"), ("para", "Para el"), ("estado", "Estado")):
            if it.get(k):
                f.write(f"- {lbl}: {it[k]}\n")
        f.write(f'\n## Texto\n\n{it.get("texto", "")}\n')
        if it.get("archivos"):
            f.write("\n## Archivos\n\n" + "\n".join(f"- {os.path.basename(a)}" for a in it["archivos"]) + "\n")


def _sup_indice(it):
    if not it.get("supervisora"):
        return
    p = _ruta("Supervisoras", _limpio(it["supervisora"]) + ".md")
    with open(p, "a", encoding="utf-8") as f:
        f.write(f'- #{it["id"]} {it["fecha"]} · {it["categoria"]} · {it.get("colegio") or "-"} · {it.get("resumen", "")}\n')


def _dm(iso):
    try:
        d = date.fromisoformat(iso)
        return ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"][d.weekday()] + d.strftime(" %d-%m")
    except Exception:
        return iso


def confirmacion(it, extra=""):
    l1 = f'{ICONO.get(it["categoria"], "📌")} *#{it["id"]} · {it["categoria"]}*'
    l1 += f' · {it["colegio"]}' if it.get("colegio") else " · _sin colegio_"
    lineas = [l1]
    if it.get("resumen"):
        lineas.append(f'📝 {it["resumen"]}')
    det = []
    if it.get("tecnico"):
        det.append(f'👷 {it["tecnico"]}')
    if it.get("supervisora"):
        det.append(f'👩‍💼 {it["supervisora"].split()[0]}')
    if it.get("para"):
        det.append(f'📅 {_dm(it["para"])}')
    if it.get("archivos"):
        det.append(f'📎 {len(it["archivos"])}')
    if det:
        lineas.append(" · ".join(det))
    if extra:
        lineas.append(extra)
    return "\n".join(lineas)


# ------------------------------------------------------------------ entrada principal
def procesar(tipo, texto="", ruta=None, autor="", ts=None, nombre_archivo=""):
    """
    tipo: texto | imagen | audio | documento | video
    Devuelve {"texto": confirmación} o {"reaccion": "📎"} (foto/audio pegado a un trabajo anterior).
    """
    with LOCK:
        cuando = datetime.fromtimestamp(ts) if ts else datetime.now()
        texto = (texto or "").strip()
        sacado, origen = "", ""
        if tipo == "audio" and ruta:
            sacado, origen = transcribir(ruta), "🎤"
        elif tipo == "imagen" and ruta and not texto:
            sacado, origen = ocr(ruta), "🔤"
        elif tipo == "documento" and ruta and ruta.lower().endswith(".pdf"):
            sacado, origen = pdf_texto(ruta)[:3000], "📄"
        items = leer()

        # foto/video/documento sin texto útil: se pega al trabajo de los últimos minutos, o queda esperando el texto
        if ruta and not texto and not sacado:
            ult = next((it for it in reversed(items) if it.get("estado") != "borrado"), None)
            if ult and time.time() - ult.get("ts", 0) < MIN_JUNTAR * 60:
                ult.setdefault("archivos", []).append(_mover(ruta, ult["carpeta"]))
                ult["ts"] = time.time()
                guardar(items)
                _nota(ult)
                return {"reaccion": "📎"}
            esp = [e for e in _espera() if time.time() - e["t"] < MIN_JUNTAR * 60]
            esp.append({"t": time.time(), "ruta": _mover(ruta, os.path.join("Bandeja", "esperando"))})
            _espera_guardar(esp)
            return {"reaccion": "⏳"}

        completo = "\n".join(x for x in (texto, sacado) if x)
        resp = consulta(completo)
        if resp:
            if ruta:
                try:
                    os.remove(ruta)
                except Exception:
                    pass
            if origen == "🎤":
                resp["texto"] = f"🎤 «{sacado[:200]}»\n\n" + (resp.get("texto") or "")
            return resp
        r = reglas(completo)
        intel = ia(completo) if completo else {}
        # Emergencia SOLO por palabras clave (la IA chica a veces la inventa); el resto: IA, si no reglas
        cat_ia = intel.get("categoria") if intel.get("categoria") != "Emergencia" else None
        cat = "Emergencia" if r["categoria"] == "Emergencia" else (r["categoria"] or cat_ia or "Nota")
        if r["categoria"] in (None, "Pendiente") and cat_ia:
            cat = cat_ia
        if not _fiel(intel.get("resumen", ""), completo):     # resumen que no sale del texto = inventado
            intel["resumen"] = ""
        rbd = r["rbds"][0] if r["rbds"] else ""
        it = {
            "id": max([x["id"] for x in items] or [0]) + 1,
            "ts": time.time(), "fecha": cuando.strftime("%Y-%m-%d"), "hora": cuando.strftime("%H:%M"),
            "categoria": cat, "rbd": rbd, "colegio": _colegio(rbd) if rbd else "",
            "otros_rbd": r["rbds"][1:], "tecnico": r["tecnico"], "supervisora": r["supervisora"], "para": r["para"],
            "resumen": intel.get("resumen") or (texto or sacado)[:80], "equipo": intel.get("equipo", ""),
            "texto": completo, "origen": tipo, "autor": autor, "estado": "abierto" if cat != "Nota" else "",
            "archivos": [],
        }
        it["carpeta"] = _carpeta_item(it)
        if ruta:
            it["archivos"].append(_mover(ruta, it["carpeta"]))
        # lo que estaba esperando (fotos mandadas antes del texto) se suma a este trabajo
        resto = []
        for e in _espera():
            if time.time() - e["t"] < MIN_JUNTAR * 60 and e.get("ruta"):
                it["archivos"].append(_mover(os.path.join(base(), e["ruta"]), it["carpeta"]))
            else:
                resto.append(e)
        _espera_guardar(resto)
        it["archivos"] = [a for a in it["archivos"] if a]
        items.append(it)
        guardar(items)
        _nota(it)
        _sup_indice(it)
        extra = ""
        if origen == "🎤" and sacado:
            extra = f"🎤 «{sacado[:220]}{'…' if len(sacado) > 220 else ''}»"
        elif origen == "🎤":
            extra = "🎤 _No pude transcribir el audio (¿whisper instalado?). Quedó guardado igual._"
        if not rbd:
            extra += ("\n" if extra else "") + "_No reconocí el colegio: *!corrige colegio <nombre>*_"
        return {"texto": confirmacion(it, extra)}


# ------------------------------------------------------------------ comandos
RX_CMD = re.compile(r"^!\s*(corrige|corregir|listo|lista|trabajos|que paso|qué pasó|que paso en|resumen|borrar)\b", re.I)


def es_comando(texto):
    return bool(RX_CMD.match(norm(texto).strip()))


def _buscar_rbd(txt):
    try:
        import nucleo
        h = nucleo.en_texto(txt)
        if h:
            return str(h[0])
        r = nucleo.buscar(txt)
        if r and r[0][0] >= 70:
            return str(r[0][1])
    except Exception:
        pass
    return ""


def comando(texto):
    t = norm(texto).strip().lstrip("!").strip()
    with LOCK:
        items = leer()
        vivos = [x for x in items if x.get("estado") != "borrado"]

        m = re.match(r"(corrige|corregir)\s*(\d+)?\s*(.*)", t)
        if m:
            it = next((x for x in vivos if str(x["id"]) == m.group(2)), None) if m.group(2) else (vivos[-1] if vivos else None)
            if not it:
                return {"texto": "No encuentro ese trabajo."}
            resto = m.group(3)
            cambios = []
            for c in CATS:
                if re.search(rf"\b{norm(c)}\b", resto):
                    it["categoria"] = c
                    it["estado"] = "abierto" if c != "Nota" else ""
                    cambios.append(c)
            mc = re.search(r"\b(?:colegio|en|del|de la)\s+(.+)$", resto)
            rbd = _buscar_rbd(mc.group(1)) if mc else _buscar_rbd(resto)
            if rbd and rbd != it.get("rbd"):
                it["rbd"], it["colegio"] = rbd, _colegio(rbd)
                try:
                    import datacora
                    it["supervisora"] = datacora._sup_de_rbd().get(rbd, it.get("supervisora", ""))
                except Exception:
                    pass
                cambios.append(it["colegio"])
            for k, nom in _tecnicos().items():
                if re.search(rf"\b{k}\b", resto):
                    it["tecnico"] = nom
                    cambios.append(nom)
            if not cambios:
                return {"texto": "No entendí qué corregir. Ej: *!corrige emergencia* · *!corrige colegio antilen* · *!corrige rodrigo*"}
            # la carpeta se mueve a donde corresponde ahora
            nueva = _carpeta_item(it)
            if nueva != it["carpeta"] and os.path.isdir(os.path.join(base(), it["carpeta"])):
                destino = _ruta(nueva)
                for f in os.listdir(os.path.join(base(), it["carpeta"])):
                    shutil.move(os.path.join(base(), it["carpeta"], f), os.path.join(destino, f))
                try:
                    os.rmdir(os.path.join(base(), it["carpeta"]))
                except Exception:
                    pass
                it["archivos"] = [os.path.join(nueva, os.path.basename(a)) for a in it.get("archivos", [])]
                it["carpeta"] = nueva
            guardar(items)
            _nota(it)
            # la corrección queda como ejemplo para la IA (así aprende)
            with open(_ruta("Trabajos", "ejemplos_ia.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"texto": it.get("texto", ""), "categoria": it["categoria"],
                                    "resumen": it.get("resumen", "")}, ensure_ascii=False) + "\n")
            return {"texto": "✏️ Corregido\n" + confirmacion(it)}

        m = re.match(r"(listo|lista|borrar)\s+(\d+)", t)
        if m:
            it = next((x for x in vivos if str(x["id"]) == m.group(2)), None)
            if not it:
                return {"texto": "No encuentro ese trabajo."}
            it["estado"] = "borrado" if m.group(1) == "borrar" else "listo"
            guardar(items)
            if it["estado"] != "borrado":
                _nota(it)
            return {"texto": f'{"🗑️ Borrado del registro" if it["estado"] == "borrado" else "✅ Listo"}: #{it["id"]} {it.get("colegio") or ""} — {it.get("resumen", "")}'}

        m = re.match(r"(?:que paso|que paso en)\s+(?:en\s+)?(.+)", t)
        if m:
            rbd = _buscar_rbd(m.group(1))
            if not rbd:
                return {"texto": "No reconocí ese colegio."}
            xs = [x for x in vivos if x.get("rbd") == rbd or rbd in x.get("otros_rbd", [])][-12:]
            if not xs:
                return {"texto": f"📭 No tengo nada guardado de {_colegio(rbd)}."}
            return {"texto": f"🏫 *{_colegio(rbd)}* — {len(xs)} registro(s)\n" + "\n".join(
                f'{ICONO.get(x["categoria"], "•")} #{x["id"]} {x["fecha"][8:]}-{x["fecha"][5:7]} {x["categoria"]}'
                f'{" ✅" if x.get("estado") == "listo" else ""} — {x.get("resumen", "")}' for x in xs)}

        m = re.match(r"trabajos\s*(.*)", t)
        if m:
            f = m.group(1).strip()
            xs = [x for x in vivos if x.get("estado") == "abierto"]
            if f:
                cat = next((c for c in CATS if norm(c).startswith(f[:5])), None)
                tec = next((nom for k, nom in _tecnicos().items() if k in f), None)
                rbd = "" if (cat or tec) else _buscar_rbd(f)
                xs = [x for x in xs if (cat and x["categoria"] == cat) or (tec and x.get("tecnico") == tec)
                      or (rbd and x.get("rbd") == rbd)]
            if not xs:
                return {"texto": "🎉 No hay trabajos abiertos" + (f" de *{f}*" if f else "") + "."}
            orden = {c: i for i, c in enumerate(CATS)}
            xs.sort(key=lambda x: (orden.get(x["categoria"], 9), x["fecha"]))
            return {"texto": f"📋 *Trabajos abiertos{(' · ' + f) if f else ''}* ({len(xs)})\n" + "\n".join(
                f'{ICONO.get(x["categoria"], "•")} #{x["id"]} {x.get("colegio") or "sin colegio"} — {x.get("resumen", "")}'
                f'{" · 👷 " + x["tecnico"] if x.get("tecnico") else ""}' for x in xs[:30])
                + "\n\n_Cerrar uno: *!listo 12*_"}

        m = re.match(r"resumen\s*(hoy|semana|mes)?", t)
        if m:
            per = m.group(1) or "semana"
            hoy = date.today()
            desde = hoy if per == "hoy" else (hoy - timedelta(days=hoy.weekday()) if per == "semana" else hoy.replace(day=1))
            xs = [x for x in vivos if x["fecha"] >= desde.isoformat()]
            if not xs:
                return {"texto": f"📭 Nada registrado desde el {desde.strftime('%d-%m')}."}
            por_cat = {c: sum(1 for x in xs if x["categoria"] == c) for c in CATS}
            por_sup = {}
            for x in xs:
                por_sup[(x.get("supervisora") or "sin supervisora").split()[0]] = por_sup.get(
                    (x.get("supervisora") or "sin supervisora").split()[0], 0) + 1
            abiertos = sum(1 for x in xs if x.get("estado") == "abierto")
            return {"texto": f"📊 *Resumen {per}* (desde {desde.strftime('%d-%m')}): {len(xs)} registros, {abiertos} abiertos\n"
                             + " · ".join(f"{ICONO[c]} {c} {n}" for c, n in por_cat.items() if n) + "\n"
                             + " · ".join(f"👩‍💼 {s} {n}" for s, n in sorted(por_sup.items(), key=lambda z: -z[1]))}
        return {"texto": "Comandos de la bandeja: *!trabajos* · *!trabajos camilo* · *!que paso en molina* · "
                         "*!resumen semana* · *!corrige emergencia* · *!listo 12* · *!borrar 12*"}


if __name__ == "__main__":
    # prueba rápida desde Termux:  python bandeja.py "en molina el horno no prende, que vaya camilo el lunes"
    if len(sys.argv) > 1 and sys.argv[1].startswith("!"):
        print(comando(" ".join(sys.argv[1:]))["texto"])
    elif len(sys.argv) > 1:
        print(procesar("texto", " ".join(sys.argv[1:]))["texto"])
    else:
        print("Uso: python bandeja.py \"texto de prueba\"   |   python bandeja.py \"!trabajos\"")
