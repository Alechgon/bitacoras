"""
IA DE PRUEBA (modo sombra) — rama prueba-ia, carpeta ~/soser-prueba.

Lee lo que el bot real copia del grupo "Mantención - operaciones" (~/soser-espejo, el espejo) y trata de ENTENDER
qué piden las supervisoras, con el contexto de la licitación y los procedimientos (carpeta conocimiento).
NUNCA manda nada a WhatsApp ni toca Datácora: solo lee y deja todo en Descargas/SOSER-prueba/
  solicitudes.xlsx  -> una fila por solicitud: supervisora, colegio, tipo, rubro, qué piden, plazo y la
                       respuesta que el bot HABRÍA dado
  Colegios/<colegio>/<fecha hora rubro>/  -> fotos, audios y nota.md
  conocimiento/*.md -> lo que la IA sabe (lo editas tú; se lee en cada solicitud)
  conocimiento/correcciones.jsonl -> tus correcciones: la IA las usa como ejemplos (así aprende)

Uso (Termux, en ~/soser-prueba/bot-ia/prueba):
  python sombra.py                    procesa lo nuevo del espejo (lo llama iniciar_prueba.sh cada 2 min)
  python sombra.py ver [10]           las últimas solicitudes entendidas
  python sombra.py corrige 12 rubro ELEC; colegio brasil; tipo REQUERIMIENTO; quiere fijar el tubo
  python sombra.py importar <chat.zip | chat.txt>   historial exportado de WhatsApp (para educarla con lo viejo)
  python sombra.py reprocesar         borra lo entendido y vuelve a leer todo (después de mejorar el conocimiento)
  python sombra.py probar "Foco suelto" "Republica de brasil"   prueba rápida sin espejo

Lo que entiende lo manda al grupo "Prueba" a través del bot real (buzón ~/soser-espejo/salida). Desde WhatsApp:
  !ia ver · !ia corrige 12 rubro ELEC; quiere … · !ia probar Foco suelto | Republica de brasil
"""
import json
import os
import re
import shutil
import sys
import time
import urllib.request
import zipfile
from datetime import date, datetime, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
BOT = os.path.dirname(AQUI)
sys.path.insert(0, BOT)

import bandeja  # noqa: E402  (transcribir, ocr, pdf_texto, norm)

ESPEJO = os.path.expanduser("~/soser-espejo")
OLLAMA = "http://127.0.0.1:11434"
VENTANA_MIN = 8            # mensajes de la misma supervisora con menos de 8 min entre sí = una solicitud
RUBROS = ["GAS", "FRIO", "AGUA", "ELEC", "EQUIPO", "INFRA", "OTRO"]
TIPOS = ["REQUERIMIENTO", "PREGUNTA", "AVISO", "RECLAMO", "INFORMACION"]
PLAZO = {"GAS": 1, "FRIO": 2, "AGUA": 2, "ELEC": 3, "EQUIPO": 5, "INFRA": 10, "OTRO": 10}
CLAVES = [
    ("GAS", r"\b(gas|fuga|piloto|quemador|termopar|termocupla|regulador|cilindro|balon)\b"),
    ("FRIO", r"\b(refrigerador|refri|freezer|congelador|camara de frio|no enfria|descongel\w*|burlete)\b"),
    ("AGUA", r"\b(agua|gotea|filtra\w*|llave|desague|lavaplatos|tapad\w*|rebalsa|desgrasadora|wc|bano)\b"),
    ("ELEC", r"\b(luz|foco|tubo|luminaria|enchufe|automatico|cable|electric\w*|ampolleta|fluorescente)\b"),
    ("INFRA", r"\b(malla|mosquitero|ventilador|extractor|rejilla|proteccion|puerta|ventana|cielo|pintura|"
              r"humedad|piso|muro|hermetic\w*|descascar\w*)\b"),
    ("EQUIPO", r"\b(horno|cocina|marmita|campana|batidora|balanza|freidora|equipo)\b"),
]
# plazos que exige la licitación 85-34-LR25 (doc. técnico de mantención) según lo que se nombra
LICITACION = [
    (r"\b(foco\w*|ampolleta\w*|luminaria\w*|tubos?|fluorescente\w*|led)\b", "5 días hábiles (luminaria)"),
    (r"\b(refrigerador\w*|refri|freezer|congelador\w*|camara de frio|no enfria)\b", "10 días hábiles (reparar frío; falla total: reponer en 5)"),
    (r"\b(llaves?|griferia|grifos?|gotea\w*)\b", "5 días hábiles (grifería)"),
    (r"\b(lavaplatos|lavafondos)\b", "60 días corridos (reponer lavaplatos)"),
    (r"\b(basurero\w*|papelero\w*)\b", "3 días hábiles (basurero)"),
    (r"\b(desgrasadora|camara grasa)\b", "3 días hábiles si lo pide la Dir. Regional (desgrasadora)"),
    (r"\b(malla|mosquitero|hermetic\w*)\b", "30 días corridos (malla mosquitera)"),
    (r"\b(meson|mesones)\b", "30 días desde la solicitud (mesón)"),
    (r"\b(estante\w*|estanteria\w*|repisa\w*|mueble\w*)\b", "30 días desde la solicitud (mueble/estante)"),
    (r"\b(carros?)\b", "30 días corridos (carro)"),
    (r"\b(campana\w*|extractor\w*|ventilador\w*|ducto\w*|filtro\w*)\b", "mantención anual o cuando se requiera (campana/extracción)"),
    (r"\b(extintor\w*)\b", "operativo siempre; mantención anual (extintor)"),
    (r"\b(gas|fuga|piloto|quemador|termopar|calefon)\b", "inmediato; instalador SEC + prueba de hermeticidad (gas)"),
]


def plazo_licitacion(texto):
    t = bandeja.norm(texto)
    return " · ".join(dict.fromkeys(p for rx, p in LICITACION if re.search(rx, t)))


URGENTE = r"\b(urgente|urgencia|prioridad|no pueden cocinar|peligro|riesgo|emergencia|olor a gas|fuga)\b"


# ------------------------------------------------------------------ carpetas
def base():
    for b in (os.path.expanduser("~/storage/downloads"), os.path.expanduser("~/storage/shared/Download")):
        if os.path.isdir(b):
            return os.path.join(b, "SOSER-prueba")
    return os.path.expanduser("~/SOSER-prueba")


def ruta(*p):
    r = os.path.join(base(), *p)
    os.makedirs(os.path.dirname(r) if os.path.splitext(r)[1] else r, exist_ok=True)
    return r


def conocimiento_dir():
    """Copia el conocimiento base al celular. Si lo actualizo y tú NO editaste ese archivo, se actualiza;
    si lo editaste, se respeta lo tuyo."""
    import hashlib
    d = ruta("conocimiento")
    h = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()   # noqa: E731
    reg_p = os.path.join(d, ".base.json")
    try:
        reg = json.load(open(reg_p, encoding="utf-8"))
    except Exception:
        reg = {}
    for f in sorted(os.listdir(os.path.join(AQUI, "conocimiento_base"))):
        src, dst = os.path.join(AQUI, "conocimiento_base", f), os.path.join(d, f)
        if not os.path.exists(dst) or (reg.get(f) and h(dst) == reg[f] and h(src) != reg[f]):
            shutil.copy(src, dst)
            reg[f] = h(src)
        elif f not in reg and h(dst) == h(src):
            reg[f] = h(src)
    json.dump(reg, open(reg_p, "w", encoding="utf-8"))
    return d


def conocimiento():
    d = conocimiento_dir()
    partes = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".md") or f.endswith(".txt"):
            partes.append(open(os.path.join(d, f), encoding="utf-8").read().strip())
    return "\n\n".join(partes)[:16000]


def correcciones(n=6):
    p = os.path.join(conocimiento_dir(), "correcciones.jsonl")
    if not os.path.exists(p):
        return []
    xs = []
    for linea in open(p, encoding="utf-8"):
        try:
            xs.append(json.loads(linea))
        except Exception:
            pass
    return xs[-n:]


def _estado():
    try:
        return json.load(open(ruta(".estado.json"), encoding="utf-8"))
    except Exception:
        return {"leidos": {}, "abiertas": []}


def _guardar_estado(e):
    p = ruta(".estado.json")
    json.dump(e, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(p + ".tmp", p)


def leer_registro():
    p = ruta("solicitudes.jsonl")
    if not os.path.exists(p):
        return []
    out = []
    for linea in open(p, encoding="utf-8"):
        try:
            out.append(json.loads(linea))
        except Exception:
            pass
    return out


def guardar_registro(items):
    p = ruta("solicitudes.jsonl")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    os.replace(p + ".tmp", p)
    excel(items)


def excel(items):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except Exception:
        return
    wb = Workbook()
    ws = wb.active
    ws.title = "Solicitudes"
    cols = ["#", "Fecha", "Hora", "Supervisora", "Colegio", "RBD", "Tipo", "Rubro", "Qué piden", "Equipo",
            "Urgente", "Plazo interno", "Plazo licitación", "Visita en Datácora", "Respuesta que habría dado", "Mensajes originales",
            "Archivos", "Corregido", "Carpeta"]
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
    for it in items:
        ws.append([it["id"], it["fecha"], it["hora"], it.get("supervisora", ""), it.get("colegio", ""), it.get("rbd", ""),
                   it.get("tipo", ""), it.get("rubro", ""), it.get("que_piden", ""), it.get("equipo", ""),
                   "sí" if it.get("urgente") else "", it.get("plazo", ""), it.get("licitacion", ""), it.get("datacora", ""),
                   it.get("respuesta", ""), it.get("mensajes", "")[:1500], len(it.get("archivos", [])),
                   "sí" if it.get("corregido") else "", it.get("carpeta", "")])
    for col, ancho in zip("ABCDEFGHIJKLMNOPQRS", (5, 11, 6, 14, 26, 8, 15, 8, 40, 14, 8, 11, 30, 22, 50, 60, 8, 9, 40)):
        ws.column_dimensions[col].width = ancho
    for fila in ws.iter_rows(min_row=2):
        for c in fila:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    p = ruta("solicitudes.xlsx")
    try:
        wb.save(p + ".tmp.xlsx")
        os.replace(p + ".tmp.xlsx", p)
    except Exception:
        pass


# ------------------------------------------------------------------ espejo -> solicitudes
def nuevos_mensajes(est):
    d = os.path.join(ESPEJO, "mensajes")
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".jsonl"):
            continue
        p = os.path.join(d, f)
        ya = est["leidos"].get(f, 0)
        tam = os.path.getsize(p)
        if tam <= ya:
            continue
        with open(p, encoding="utf-8") as fh:
            fh.seek(ya)
            for linea in fh:
                try:
                    out.append(json.loads(linea))
                except Exception:
                    pass
            est["leidos"][f] = fh.tell()
    return sorted(out, key=lambda x: x.get("ts", 0))


def agrupar(est, msgs, ahora_ts):
    """Junta mensajes seguidos de la misma persona en una solicitud. Devuelve las que ya se cerraron."""
    abiertas = est.get("abiertas", [])
    for m in msgs:
        if m.get("tipo") == "sticker":
            continue
        quien = m.get("numero") or m.get("autor")
        g = next((a for a in abiertas if a["quien"] == quien and m["ts"] - a["ultimo"] <= VENTANA_MIN * 60), None)
        if g:
            g["msgs"].append(m)
            g["ultimo"] = m["ts"]
        else:
            abiertas.append({"quien": quien, "autor": m.get("autor", ""), "ultimo": m["ts"], "msgs": [m]})
    listas = [a for a in abiertas if ahora_ts - a["ultimo"] > VENTANA_MIN * 60]
    est["abiertas"] = [a for a in abiertas if a not in listas]
    return listas


# ------------------------------------------------------------------ entender
def supervisora(autor):
    a = bandeja.norm(autor)
    for k, n in (("anahi", "Annahi"), ("annahi", "Annahi"), ("stephania", "Stephania"), ("estefania", "Stephania"),
                 ("carla", "Carla")):
        if k in a:
            return n
    return (autor or "").split("(")[0].strip()[:30]


def colegio_de(lineas):
    import nucleo
    junto = " \n ".join(lineas)
    hits = [str(r) for r in nucleo.en_texto(junto)]
    if hits:
        return hits[0]
    # una línea corta que es solo un nombre ("Republica de brasil")
    for ln in lineas:
        if 1 <= len(ln.split()) <= 6:
            r = nucleo.buscar(ln)
            if r and r[0][0] >= 80:
                return str(r[0][1])
    return ""


def nombre_colegio(rbd):
    try:
        import nucleo
        return nucleo.datos()["E"].get(int(rbd), {}).get("nombre", f"RBD {rbd}")
    except Exception:
        return f"RBD {rbd}"


def reglas(texto):
    t = bandeja.norm(texto)
    rub = next((r for r, rx in CLAVES if re.search(rx, t)), "")
    tipo = ("PREGUNTA" if re.search(r"\?|\b(cuando|que paso|para cuando|van a venir|hay fecha)\b", t)
            else "RECLAMO" if re.search(r"\b(no llego|no llegaron|se fue sin|no vino|nadie vino)\b", t)
            else "AVISO" if re.search(r"\b(seremi|junaeb|auditoria|fiscaliza\w*|supervision|cierra|cerrado|horario)\b", t)
            else "")
    return {"rubro": rub, "tipo": tipo, "urgente": bool(re.search(URGENTE, t))}


def ia(mensajes_txt):
    ej = "\n".join(f"Mensajes: {c['mensajes'][:300]}\nJSON: {json.dumps(c['respuesta'], ensure_ascii=False)}"
                   for c in correcciones())
    prompt = (
        "Eres el asistente del encargado de mantención de SOSER. Este es tu conocimiento:\n\n"
        + conocimiento()
        + ("\n\nEjemplos corregidos por Manuel (síguelos):\n" + ej if ej else "")
        + "\n\nLee los mensajes de la supervisora y responde SOLO un JSON con las claves: "
          '"tipo" (REQUERIMIENTO, PREGUNTA, AVISO, RECLAMO o INFORMACION), '
          '"rubro" (GAS, FRIO, AGUA, ELEC, EQUIPO, INFRA u OTRO), "que_piden" (máx 12 palabras), '
          '"equipo", "urgente" (true/false). No inventes nada que no esté en los mensajes.\n\n'
        + f"Mensajes:\n{mensajes_txt[:2500]}\nJSON:")
    try:
        modelo = "qwen2.5:1.5b"
        req = urllib.request.Request(OLLAMA + "/api/generate", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"model": modelo, "prompt": prompt, "stream": False,
                                                      "format": "json", "keep_alive": "10m",
                                                      "options": {"temperature": 0.1, "num_ctx": 8192}}).encode())
        with urllib.request.urlopen(req, timeout=300) as r:
            out = json.loads(json.loads(r.read()).get("response", "{}"))
        return {
            "tipo": next((x for x in TIPOS if x == str(out.get("tipo", "")).upper()), ""),
            "rubro": next((x for x in RUBROS if x == str(out.get("rubro", "")).upper()), ""),
            "que_piden": str(out.get("que_piden", "")).strip()[:140],
            "equipo": str(out.get("equipo", "")).strip()[:40],
            "urgente": bool(out.get("urgente")),
        }
    except Exception as e:
        return {"_error": str(e)}


def habiles(desde, n):
    d = desde
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def en_datacora(rbd):
    """Próxima tarea pendiente de ese colegio en Datácora (solo lectura, con la caché del bot)."""
    if not rbd:
        return ""
    try:
        import datacora
        if not datacora.configurado():
            return ""
        hoy = datacora.ahora().date()
        xs = [t for t in datacora.tareas() if datacora.pendiente(t) and datacora.establecimiento(t)[1] == rbd]
        xs.sort(key=lambda t: datacora.fecha_tarea(t) or hoy)
        if xs:
            t = xs[0]
            return f"{datacora._dm(datetime.combine(datacora.fecha_tarea(t) or hoy, datetime.min.time()))} · " \
                   f"{datacora._primer_nombre(datacora.tecnico(t))} · {datacora.tipo_corto(t)}"
    except Exception:
        return ""
    return ""


def respuesta_simulada(it):
    """Lo que el bot HABRÍA contestado (no se manda: es para que tú lo evalúes)."""
    sup = it.get("supervisora") or ""
    col = it.get("colegio") or "ese colegio"
    if it["tipo"] == "PREGUNTA":
        return f"{sup}, lo reviso y te confirmo la fecha de {col}." if not it.get("datacora") else \
            f"{sup}, {col} ya tiene visita: {it['datacora']}."
    if it["tipo"] == "AVISO":
        return f"Gracias {sup}, priorizamos lo pendiente de {col}."
    if it["tipo"] == "RECLAMO":
        return f"{sup}, disculpa, lo reviso altiro y te aviso cuándo vuelve el técnico a {col}."
    if it["tipo"] == "INFORMACION":
        return ""
    base_txt = f"Recibido {sup} 👍 {it.get('que_piden') or 'lo informado'} en {col}."
    if it.get("datacora"):
        return base_txt + f" Ya tiene visita: {it['datacora']}, se ve ahí."
    return base_txt + f" Lo dejamos antes del {it.get('plazo', '')}" + (" (urgente)." if it.get("urgente") else ".")


def interpretar(sol, items):
    msgs = sol["msgs"]
    lineas, archivos = [], []
    for m in msgs:
        t = (m.get("texto") or "").strip()
        src = os.path.join(ESPEJO, m["archivo"]) if m.get("archivo") else ""
        extra = ""
        if src and os.path.exists(src):
            archivos.append(src)
            if m["tipo"] == "audio":
                extra = bandeja.transcribir(src)
                extra = f"[audio{' reenviado' if m.get('reenviado') else ''}] {extra}" if extra else "[audio sin transcribir]"
            elif m["tipo"] == "documento" and src.lower().endswith(".pdf"):
                extra = "[PDF] " + bandeja.pdf_texto(src)[:600]
            elif m["tipo"] == "imagen" and not t:
                o = bandeja.ocr(src)
                extra = "[foto con texto] " + o[:300] if o else "[foto]"
            elif m["tipo"] == "imagen":
                extra = "[foto]"
        hora = datetime.fromtimestamp(m["ts"]).strftime("%H:%M")
        if m.get("citado"):
            t = f'(respondiendo a: "{m["citado"][:80]}") {t}'
        lineas.append(f"{hora} {t} {extra}".strip())
    texto = "\n".join(lineas)
    solo_textos = [(m.get("texto") or "").strip() for m in msgs if (m.get("texto") or "").strip()]
    rbd = colegio_de(solo_textos + [texto])
    r = reglas(texto)
    x = ia(texto)
    tipo = r["tipo"] or x.get("tipo") or "REQUERIMIENTO"
    rubro = r["rubro"] if r["rubro"] in ("GAS",) else (x.get("rubro") or r["rubro"] or "OTRO")
    urgente = r["urgente"] or (x.get("urgente") and rubro in ("GAS", "AGUA", "ELEC", "FRIO"))
    que = x.get("que_piden", "")
    if que and not bandeja._fiel(que, texto):
        que = ""
    cuando = datetime.fromtimestamp(msgs[0]["ts"])
    plazo_d = 2 if urgente and rubro != "GAS" else PLAZO.get(rubro, 10)
    it = {
        "id": max([i["id"] for i in items] or [0]) + 1,
        "fecha": cuando.strftime("%Y-%m-%d"), "hora": cuando.strftime("%H:%M"),
        "supervisora": supervisora(sol.get("autor", "")), "rbd": rbd,
        "colegio": nombre_colegio(rbd) if rbd else "", "tipo": tipo, "rubro": rubro,
        "que_piden": que or " · ".join(t for t in solo_textos
                                       if not (rbd and bandeja.norm(t) in bandeja.norm(nombre_colegio(rbd))))[:140],
        "equipo": x.get("equipo", ""),
        "urgente": bool(urgente), "plazo": habiles(cuando.date(), plazo_d).strftime("%d-%m"),
        "mensajes": texto, "ia_error": x.get("_error", ""), "ids": [m["id"] for m in msgs],
    }
    it["licitacion"] = plazo_licitacion(texto)
    it["datacora"] = en_datacora(rbd) if tipo in ("REQUERIMIENTO", "PREGUNTA") else ""
    it["respuesta"] = respuesta_simulada(it)
    # carpeta con copia de fotos/audios (el espejo queda intacto)
    sub = f'{it["fecha"]} {it["hora"].replace(":", "")} {it["rubro"]}'
    rel = os.path.join("Colegios", bandeja._limpio(f'{it["colegio"]} ({rbd})'), sub) if rbd else os.path.join("Sin colegio", sub)
    it["carpeta"] = rel
    it["archivos"] = []
    for a in archivos:
        dst = ruta(rel, os.path.basename(a))
        shutil.copy(a, dst)
        it["archivos"].append(os.path.relpath(dst, base()))
    with open(ruta(rel, "nota.md"), "w", encoding="utf-8") as f:
        f.write(f'# #{it["id"]} · {it["tipo"]} · {it["rubro"]} · {it["colegio"] or "sin colegio"}\n\n'
                f'- Supervisora: {it["supervisora"]}\n- Fecha: {it["fecha"]} {it["hora"]}\n'
                f'- Qué piden: {it["que_piden"]}\n- Plazo: {it["plazo"]}{" (urgente)" if it["urgente"] else ""}\n'
                f'- Licitación: {it.get("licitacion") or "-"}\n- Datácora: {it["datacora"] or "-"}\n- Habría respondido: {it["respuesta"] or "-"}\n\n'
                f'## Mensajes\n\n{texto}\n')
    return it


def avisar(texto, archivos=None):
    """Deja un mensaje en el buzón: el bot real lo manda SOLO al grupo Prueba."""
    d = os.path.join(ESPEJO, "salida")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{time.time():.6f}.json")
    json.dump({"texto": texto, "archivos": archivos or []}, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(p + ".tmp", p)


def tarjeta(it):
    lin = [f'🧪 *IA de prueba* · #{it["id"]}',
           f'👩‍💼 {it["supervisora"] or "?"} · 🏫 {it["colegio"] or "_sin colegio_"}',
           f'📋 {it["tipo"]} · {it["rubro"]}{" · 🚨 URGENTE" if it.get("urgente") else ""} · plazo {it["plazo"]}']
    if it.get("que_piden"):
        lin.append(f'🔧 {it["que_piden"]}')
    if it.get("licitacion"):
        lin.append(f'⚖️ Licitación: {it["licitacion"]}')
    if it.get("datacora"):
        lin.append(f'📅 Datácora: {it["datacora"]}')
    if it.get("archivos"):
        lin.append(f'📎 {len(it["archivos"])} archivo(s)')
    if it.get("respuesta"):
        lin.append(f'💬 Habría respondido: «{it["respuesta"]}»')
    lin.append("🗨️ " + it["mensajes"][:300].replace("\n", " | "))
    lin.append(f'_Si está mal: *!ia corrige {it["id"]} rubro ELEC; colegio brasil; tipo REQUERIMIENTO; quiere …*_')
    return "\n".join(lin)


def comandos_pendientes():
    """Lo que escribiste con !ia en WhatsApp (el bot real lo deja en comandos.jsonl)."""
    p = os.path.join(ESPEJO, "comandos.jsonl")
    if not os.path.exists(p):
        return
    tmp = p + ".leyendo"
    os.replace(p, tmp)
    for linea in open(tmp, encoding="utf-8"):
        try:
            c = json.loads(linea)["texto"].strip()
        except Exception:
            continue
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            partes = c.split()
            if partes and partes[0].lower() in ("corrige", "corregir") and len(partes) >= 3:
                corrige(partes[1], " ".join(partes[2:]))
            elif partes and partes[0].lower() == "ver":
                ver(int(partes[1]) if len(partes) > 1 and partes[1].isdigit() else 5)
            elif partes and partes[0].lower() == "probar":
                probar([x.strip() for x in " ".join(partes[1:]).split("|") if x.strip()])
            elif partes and partes[0].lower() == "reprocesar":
                print("Reprocesar se hace desde Termux: python sombra.py reprocesar")
            else:
                print("Comandos: *!ia ver* · *!ia ver 10* · *!ia corrige 12 rubro ELEC; colegio brasil; quiere …* · "
                      "*!ia probar Foco suelto | Republica de brasil*")
        avisar("🧪 " + (buf.getvalue().strip() or "Listo.")[:3500])
    os.remove(tmp)


def pasada(forzar_cierre=False):
    comandos_pendientes()
    est = _estado()
    msgs = nuevos_mensajes(est)
    listas = agrupar(est, msgs, time.time() + (10 ** 9 if forzar_cierre else 0))
    items = leer_registro()
    nuevos = []
    for sol in listas:
        it = interpretar(sol, items)
        items.append(it)
        nuevos.append(it)
    if nuevos:
        guardar_registro(items)
    _guardar_estado(est)
    for it in nuevos:
        avisar(tarjeta(it))
    for it in nuevos:
        print(f'{datetime.now():%H:%M} #{it["id"]} {it["supervisora"]} · {it["colegio"] or "?"} · {it["tipo"]} · '
              f'{it["rubro"]} · {it["que_piden"]}', flush=True)
    return nuevos


# ------------------------------------------------------------------ herramientas
def ver(n=10):
    for it in leer_registro()[-n:]:
        print(f'#{it["id"]} {it["fecha"]} {it["hora"]} · {it["supervisora"]} · {it["colegio"] or "sin colegio"}\n'
              f'   {it["tipo"]} · {it["rubro"]}{" · URGENTE" if it.get("urgente") else ""} · plazo {it["plazo"]}\n'
              f'   qué piden: {it["que_piden"]}\n   habría dicho: {it.get("respuesta") or "-"}\n'
              f'   mensajes: {it["mensajes"][:200].replace(chr(10), " | ")}\n')


def corrige(num, txt):
    items = leer_registro()
    it = next((x for x in items if str(x["id"]) == str(num)), None)
    if not it:
        print("No existe ese número.")
        return
    t = bandeja.norm(txt)
    for parte in [p.strip() for p in txt.split(";") if p.strip()]:
        pn = bandeja.norm(parte)
        if pn.startswith("rubro"):
            it["rubro"] = next((r for r in RUBROS if r.lower() in pn), it["rubro"])
        elif pn.startswith("tipo"):
            it["tipo"] = next((r for r in TIPOS if r.lower() in pn), it["tipo"])
        elif pn.startswith("colegio"):
            import nucleo
            q = parte.split(" ", 1)[1] if " " in parte else ""
            hits = nucleo.en_texto(q) or [r for s, r in nucleo.buscar(q) if s >= 60][:1]
            if hits:
                it["rbd"], it["colegio"] = str(hits[0]), nombre_colegio(hits[0])
        elif pn.startswith(("quiere", "que piden", "piden")):
            it["que_piden"] = re.sub(r"^\s*(quiere|que piden|qué piden|piden)\s*:?\s*", "", parte, flags=re.I)
        elif pn.startswith("urgente"):
            it["urgente"] = "no" not in pn
    if "urgente" in t and "no urgente" not in t:
        it["urgente"] = True
    it["corregido"] = True
    it["respuesta"] = respuesta_simulada(it)
    guardar_registro(items)
    with open(os.path.join(conocimiento_dir(), "correcciones.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"mensajes": it["mensajes"], "respuesta": {
            "tipo": it["tipo"], "rubro": it["rubro"], "que_piden": it["que_piden"], "equipo": it.get("equipo", ""),
            "urgente": it.get("urgente", False)}}, ensure_ascii=False) + "\n")
    print("✏️ Corregido y guardado como ejemplo para la IA:")
    ver_uno(it)


def ver_uno(it):
    print(f'#{it["id"]} {it["supervisora"]} · {it["colegio"]} · {it["tipo"]} · {it["rubro"]} · {it["que_piden"]}')


RX_LINEA = re.compile(r"^‎?\[?(\d{1,2})/(\d{1,2})/(\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::\d{2})?\s*([ap])?\.?\s*m?\.?\]?"
                      r"\s*(?:-|–)?\s*([^:]{1,60}):\s(.*)$", re.I)
RX_ADJ = re.compile(r"([\w\-]+\.(?:jpg|jpeg|png|webp|opus|ogg|m4a|mp3|mp4|pdf|docx?|xlsx?))", re.I)


def importar(ruta_in):
    """Historial exportado de WhatsApp (Exportar chat -> Incluir archivos) -> formato del espejo."""
    tmp = os.path.join(ESPEJO, "import", datetime.now().strftime("%Y%m%d%H%M%S"))
    os.makedirs(tmp, exist_ok=True)
    if ruta_in.lower().endswith(".zip"):
        with zipfile.ZipFile(ruta_in) as z:
            z.extractall(tmp)
        txts = [os.path.join(tmp, f) for f in os.listdir(tmp) if f.endswith(".txt")]
    else:
        txts = [ruta_in]
    if not txts:
        print("No encontré el .txt del chat dentro del archivo.")
        return
    filas = []
    for linea in open(txts[0], encoding="utf-8", errors="ignore"):
        linea = linea.replace(" ", " ").replace(" ", " ").rstrip("\n")
        m = RX_LINEA.match(linea)
        if not m:
            if filas:
                filas[-1]["texto"] += "\n" + linea
            continue
        d, mo, a, h, mi, ap, autor, txt = m.groups()
        a = int(a) + (2000 if int(a) < 100 else 0)
        h = int(h)
        if ap and ap.lower() == "p" and h < 12:
            h += 12
        if ap and ap.lower() == "a" and h == 12:
            h = 0
        try:
            ts = datetime(a, int(mo), int(d), h, int(mi)).timestamp()
        except ValueError:
            continue
        fila = {"id": f"imp{len(filas)}", "ts": ts, "grupo": "importado", "autor": autor.strip(), "numero": "",
                "tipo": "texto", "texto": txt, "archivo": "", "citado": "", "citado_id": "", "reenviado": False}
        adj = RX_ADJ.search(txt)
        if adj and ("adjunto" in txt.lower() or "omitted" in txt.lower() or "<" in txt):
            nombre = adj.group(1)
            src = os.path.join(tmp, nombre)
            if os.path.exists(src):
                fila["archivo"] = os.path.relpath(src, ESPEJO)
            ext = nombre.lower().rsplit(".", 1)[-1]
            fila["tipo"] = ("imagen" if ext in ("jpg", "jpeg", "png", "webp") else "audio" if ext in ("opus", "ogg", "m4a", "mp3")
                            else "video" if ext == "mp4" else "documento")
            fila["texto"] = RX_ADJ.sub("", txt).replace("(archivo adjunto)", "").replace("<adjunto:", "").strip(" >‎")
        if "multimedia omitido" in txt.lower() or "<media omitted>" in txt.lower():
            fila["tipo"], fila["texto"] = "imagen", ""
        filas.append(fila)
    os.makedirs(os.path.join(ESPEJO, "mensajes"), exist_ok=True)
    out = os.path.join(ESPEJO, "mensajes", f"0000-importado-{datetime.now():%Y%m%d%H%M%S}.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for x in filas:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"📥 Importados {len(filas)} mensajes ({sum(1 for x in filas if x['archivo'])} con archivo). "
          f"Ahora corre: python sombra.py  (la primera vez se demora: entiende uno por uno)")


def reprocesar():
    for f in ("solicitudes.jsonl", "solicitudes.xlsx", ".estado.json"):
        try:
            os.remove(ruta(f))
        except Exception:
            pass
    for d in ("Colegios", "Sin colegio"):
        shutil.rmtree(os.path.join(base(), d), ignore_errors=True)
    print("🧹 Listo: se vuelve a leer todo el espejo con el conocimiento actual (sin avisar al grupo).")
    global avisar
    avisar = lambda *a, **k: None    # noqa: E731
    pasada(forzar_cierre=True)


def probar(frases):
    now = time.time()
    sol = {"autor": "Prueba", "msgs": [{"id": f"p{i}", "ts": now + i, "tipo": "texto", "texto": f, "archivo": ""}
                                       for i, f in enumerate(frases)]}
    it = interpretar(sol, leer_registro())
    print(json.dumps({k: it[k] for k in ("colegio", "tipo", "rubro", "que_piden", "equipo", "urgente", "plazo", "licitacion",
                                         "datacora", "respuesta", "ia_error")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        pasada()
    elif a[0] == "ver":
        ver(int(a[1]) if len(a) > 1 else 10)
    elif a[0] == "corrige" and len(a) >= 3:
        corrige(a[1], " ".join(a[2:]))
    elif a[0] == "importar" and len(a) >= 2:
        importar(a[1])
    elif a[0] == "reprocesar":
        reprocesar()
    elif a[0] == "probar" and len(a) >= 2:
        probar(a[1:])
    elif a[0] == "cerrar":
        pasada(forzar_cierre=True)
    else:
        print(__doc__)
