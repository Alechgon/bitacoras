"""
OPERACIÓN DE PRUEBA: pendientes, ruta organizada y cotejo de bitácoras (rama prueba-ia).

  Pendientes   Lo que reportan las supervisoras (grupo real, por el espejo) y lo que escribes en el grupo Prueba
               queda anotado si le toca a SOSER: Descargas/SOSER-prueba/pendientes.json
  Ruta         "ruta de hoy" en el grupo Prueba: por técnico, máx. 4. Primero lo ya cerrado, después gas y equipos
               de calor, después el resto por orden de emisión (cuándo se subió la tarea o se reportó).
               Junta lo de Datácora (solo lectura) con los pendientes anotados.
  Cotejo       Cuando un técnico cierra una visita en un colegio con pendientes reportados antes, se baja la
               bitácora (Descargas/Verificadores SOSER), se lee el PDF y se dice qué se hizo y qué pendiente
               quedó resuelto. Solo JUNAEB (en jardines la bitácora es física).
               Prueba: "emular bitácora república de brasil hoy" (o "ayer", "18-11").

Comandos (en el grupo Prueba, sin !):
  pendientes · ruta de hoy · ruta de mañana · emular bitácora <colegio> <hoy|ayer|dd-mm> · resuelto <n> · borrar <n>

Termux:  python operacion.py pendientes | ruta | "emular bitácora brasil hoy" | revisar
"""
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
BOT = os.path.dirname(AQUI)
sys.path.insert(0, AQUI)
sys.path.insert(0, BOT)

ESPEJO = os.path.expanduser("~/soser-espejo")
CADA_REVISION = 30 * 60          # cada cuánto se miran los cierres en Datácora (si hay pendientes)
HORARIO = (8, 21)
TAREAS_SEG = 300                 # la lista de tareas de Datácora se reusa 5 min (también entre procesos)


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def _base():
    for b in (os.path.expanduser("~/storage/downloads"), os.path.expanduser("~/storage/shared/Download")):
        if os.path.isdir(b):
            return os.path.join(b, "SOSER-prueba")
    return os.path.expanduser("~/SOSER-prueba")


def _p(*x):
    r = os.path.join(_base(), *x)
    os.makedirs(os.path.dirname(r), exist_ok=True)
    return r


def _json(p, defecto):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return defecto


def _guardar_json(p, x):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(x, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def hoy():
    try:
        import datacora
        return datacora.ahora().date()
    except Exception:
        return date.today()


def dm(d):
    return d.strftime("%d-%m")


# ================================================================ qué es crítico
CRITICO = (r"\b(gas|fuga de gas|olor a gas|huele a gas|cilindro\w*|balon\w*|regulador\w*|flexible de gas|caseta de gas|"
           r"horno\w*|fogon\w*|anafe\w*|cocinilla\w*|quemador\w*|piloto|termocupla\w*|termopar\w*|calefon\w*|calefont|"
           r"marmita\w*|freidora\w*|bano maria|plancha\w*|cocina (industrial|no prende|no enciende|a gas)|"
           r"equipo\w* de calor|no prende|no enciende)\b")


def es_critico(texto):
    return bool(re.search(CRITICO, norm(texto)))


def resumen(texto, n=45):
    t = re.sub(r"\s+", " ", str(texto or "")).strip(" .,;")
    t = re.sub(r"(?i)^(hola|buenas|buenos dias|buenas tardes)\W+", "", t)
    return (t[:n - 1] + "…") if len(t) > n else t


# ================================================================ establecimientos (datos.js)
def colegio(rbd):
    try:
        import nucleo
        e = nucleo.datos()["E"].get(int(rbd))
        if not e:
            return None
        nombre = " ".join(w if w in ("de", "del", "la", "las", "los", "el", "y") else w.capitalize()
                          for w in e["nombre"].lower().split())
        return {"rbd": str(e["rbd"]), "nombre": nombre, "jardin": norm(e.get("inst")) != "junaeb"}
    except Exception:
        return None


def rbd_en(texto):
    try:
        import nucleo
        limpio = re.sub(r"\b\d{1,2}\s*[-/]\s*\d{1,2}(\s*[-/]\s*\d{2,4})?\b", " ", texto)     # fechas fuera
        hits = nucleo.en_texto(limpio)
        if hits:
            return str(hits[0])
        r = nucleo.buscar(limpio)
        if r and r[0][0] >= 85:
            return str(r[0][1])
    except Exception:
        pass
    return None


# ================================================================ Datácora (solo lectura, con calma)
def dc():
    import datacora
    p = os.path.join(ESPEJO, ".tareas_cache.json")
    c = _json(p, None)
    if c and time.time() - c[0] < TAREAS_SEG and "tasks" not in datacora._CACHE:
        datacora._CACHE["tasks"] = (c[0], c[1])
    return datacora


def tareas():
    D = dc()
    ts = D.tareas()
    try:
        c = D._CACHE.get("tasks")
        if c:
            os.makedirs(ESPEJO, exist_ok=True)
            json.dump([c[0], c[1]], open(os.path.join(ESPEJO, ".tareas_cache.json"), "w", encoding="utf-8"))
    except Exception:
        pass
    return ts


def texto_tarea(t):
    """Lo que dice la tarea de Datácora (descripción / observación), si trae algo."""
    for k in ("description", "descripcion", "title", "titulo", "notes", "notas", "observations", "observation",
              "observacion", "comment", "comments", "problem", "detalle", "details"):
        v = t.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def tec_del_colegio(rbd):
    try:
        D = dc()
        n = D._tec_del_colegio(str(rbd))
        return " ".join(n.split()[:2]) if n else ""
    except Exception:
        return ""


# ================================================================ pendientes
def todos():
    return _json(_p("pendientes.json"), [])


def guardar(ps):
    _guardar_json(_p("pendientes.json"), ps)


def abiertos(rbd=None):
    return [p for p in todos() if p["estado"] == "abierto" and (rbd is None or p.get("rbd") == str(rbd))]


def agregar(texto, rbd=None, clave="", origen="Prueba", archivos=None, ts=None, quien="SOSER"):
    """Anota un pendiente. Si ya hay uno abierto igual (mismo colegio y tema, últimos 3 días), devuelve ese."""
    ps = todos()
    ts = ts or time.time()
    rbd = str(rbd) if rbd else ""
    for p in ps:
        if p["estado"] == "abierto" and rbd and p.get("rbd") == rbd and clave and p.get("clave") == clave \
                and abs(ts - p["ts"]) < 3 * 86400:
            return p, False
    c = colegio(rbd) if rbd else None
    n = max([p["id"] for p in ps] or [0]) + 1
    guardados = []
    for i, a in enumerate(archivos or [], 1):
        try:
            import shutil
            dst = _p("pendientes_fotos", f"{n:03d}_{i}{os.path.splitext(a)[1] or '.jpg'}")
            shutil.copy(a, dst)
            guardados.append(dst)
        except Exception:
            pass
    p = {"id": n, "ts": ts, "fecha": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M"), "rbd": rbd,
         "colegio": c["nombre"] if c else "", "jardin": bool(c and c["jardin"]), "que": resumen(texto, 120),
         "clave": clave, "critico": es_critico(texto), "origen": origen, "quien": quien,
         "tecnico": tec_del_colegio(rbd) if rbd else "", "archivos": guardados, "estado": "abierto"}
    ps.append(p)
    guardar(ps)
    return p, True


def _orden(p):
    return (not p.get("critico"), p["ts"])


def listar():
    ab = sorted(abiertos(), key=_orden)
    if not ab:
        return "No hay pendientes anotados."
    lin = [f"Pendientes ({len(ab)})"]
    for p in ab:
        quien = f", {p['tecnico'].split()[0]}" if p.get("tecnico") else ""
        org = f", {p['origen']}" if p.get("origen") and p["origen"] != "Prueba" else ""
        lin.append(f"{p['id']}. {p['colegio'] or 'sin colegio'}: {resumen(p['que'], 50)} "
                   f"({datetime.fromtimestamp(p['ts']).strftime('%d-%m')}{quien}{org})" + (" GAS/CALOR" if p.get("critico") else ""))
    return "\n".join(lin)


def cambiar_estado(n, estado, nota=""):
    ps = todos()
    for p in ps:
        if p["id"] == n:
            p["estado"], p["nota"] = estado, nota
            guardar(ps)
            return p
    return None


# ================================================================ ruta organizada
def ruta(d=None, titulo="Ruta de hoy"):
    """Por técnico (máx. 4): lo cerrado ese día, después gas/calor y el resto por orden de emisión."""
    import datacora as D0
    hoy = D0.ahora().date()
    d = d or hoy
    cupo = D0.credenciales().get("max_por_dia", 4)
    aviso = ""
    try:
        ts = tareas()
        D = dc()
    except Exception:
        ts, D = [], D0
        aviso = "No pude leer Datácora; va solo con lo anotado."
    tecs = {}                                       # clave -> {"nombre", "hechas": [], "cola": []}

    def tec(k, nombre):
        return tecs.setdefault(k, {"nombre": nombre or k.title(), "hechas": [], "cola": []})

    pend_por_rbd = {}
    for p in abiertos():
        pend_por_rbd.setdefault(p["rbd"], []).append(p)
    en_ruta = set()
    for t in ts:
        if D.cancelada(t):
            continue
        n, rbd = D.establecimiento(t)
        k = D.clave_tec(D.tecnico(t))
        nom = D._nombre_tec(k, D.tecnico(t))
        c = colegio(rbd)
        nombre = c["nombre"] if c else n.title()
        if D.hecha(t):
            ch = D.cuando_hecha(t)
            if ch and ch.date() == d:
                tec(k, nom)["hechas"].append({"rbd": rbd, "nombre": nombre, "hora": ch.strftime("%H:%M")})
                en_ruta.add(rbd)
        elif D.fecha_tarea(t) == d:
            ps = pend_por_rbd.get(rbd, [])
            que = texto_tarea(t) or "; ".join(p["que"] for p in ps) or D.tipo_corto(t)
            sub = D.subida(t)
            marcas = ([sub.timestamp()] if sub else []) + [p["ts"] for p in ps]     # emisión: tarea o reporte, lo primero
            em = min(marcas) if marcas else time.time()
            tec(k, nom)["cola"].append({"rbd": rbd, "nombre": nombre, "que": que, "emision": em,
                                        "critico": es_critico(que) or any(p.get("critico") for p in ps)
                                        or D.prioridad(t) == 0, "dc": True})
            en_ruta.add(rbd)
    # lo anotado que no está en Datácora para ese día
    if d >= hoy:
        for rbd, ps in pend_por_rbd.items():
            if rbd in en_ruta or not rbd:
                continue
            p0 = sorted(ps, key=_orden)[0]
            nom = p0.get("tecnico") or tec_del_colegio(rbd) or "Sin técnico"
            k = D.clave_tec(nom) if nom != "Sin técnico" else "SIN TECNICO"
            tec(k, D._nombre_tec(k, nom) if k != "SIN TECNICO" else "Sin técnico")["cola"].append(
                {"rbd": rbd, "nombre": p0["colegio"] or rbd, "que": "; ".join(p["que"] for p in sorted(ps, key=_orden)),
                 "emision": min(p["ts"] for p in ps), "critico": any(p.get("critico") for p in ps), "dc": False})
    if not tecs:
        return "\n".join(x for x in (f"{titulo} ({dm(d)})", "No hay tareas ni pendientes para ese día.", aviso) if x)
    out = [f"{titulo} ({dm(d)})"]
    for k in sorted(tecs, key=lambda k: (k == "SIN TECNICO", k)):
        x = tecs[k]
        cola = sorted(x["cola"], key=lambda c: (not c["critico"], c["emision"]))
        libres = max(0, cupo - len(x["hechas"]))
        out.append("")
        out.append(x["nombre"])
        i = 0
        for h in sorted(x["hechas"], key=lambda h: h["hora"]):
            i += 1
            out.append(f"{i}. {h['nombre']} (finalizado {h['hora']})")
        for c in cola[:libres]:
            i += 1
            extra = "" if c["dc"] else " (sin tarea en Datácora)"
            out.append(f"{i}. {c['nombre']}: {resumen(c['que'], 40)}{extra}")
        if len(cola) > libres:
            out.append("Quedan: " + ", ".join(f"{c['nombre']}" for c in cola[libres:]))
    if aviso:
        out += ["", aviso]
    return "\n".join(out)


# ================================================================ cotejo de bitácoras
# palabras del pendiente -> ítems del cuadro de la bitácora (CATS de datos.js)
ITEMS = [
    (r"foco|luminaria|ampolleta|tubo|fluorescente|iluminacion|luz|led|proteccion", ["Luminarias y protecciones"]),
    (r"enchufe|toma ?corriente", ["Enchufes", "Toma Corriente"]),
    (r"interruptor", ["Interruptor"]),
    (r"automatico|tablero|diferencial|caja de distribucion", ["Cajas de Distribucion"]),
    (r"extractor|ventilador", ["Extractor", "Campana (ductos, filtros)", "Ducto de Ventilacion Campana y Calefont"]),
    (r"campana|ducto|filtro", ["Campana (ductos, filtros)", "Ducto de Ventilacion Campana y Calefont", "Extractor"]),
    (r"gas|fuga|flexible|regulador|cilindro|balon", ["Flexibles, filtraciones y conexiones de gas", "Caseta De Gas"]),
    (r"caseta", ["Caseta De Gas"]),
    (r"calefon|calefont|termo", ["Calefont (caseta, ductos)"]),
    (r"horno", ["Horno"]),
    (r"cocina|fogon|anafe|quemador|piloto|termocupla|termopar|encimera", ["Cocina 4 platos", "Fogon o Anafe", "Cocinilla"]),
    (r"cocinilla", ["Cocinilla"]),
    (r"bano maria", ["Bano Maria"]),
    (r"refri|refrigerador|congelador|freezer|visicooler|frigobar|salad ?bar|frio|enfria", [
        "Refrigerador", "Congelador", "Visicooler", "Frigobar", "Salad Bar", "Balanza Digital y Equipos de frio"]),
    (r"balanza", ["Balanza Digital y Equipos de frio"]),
    (r"malla|mosquitero", ["Mallas Mosquiteras"]),
    (r"puerta|ventana|cerradura|bisagra|manilla", ["Puertas-Ventanas"]),
    (r"vidrio", ["Vidrios", "Puertas-Ventanas"]),
    (r"llave|griferia|grifo|monomando", ["Griferia"]),
    (r"filtra|gotea|goteo|fuga de agua|cañeria|caneria|flexible de agua", ["Filtraciones artefactos y elementos"]),
    (r"desague|tapad|evacuacion|rebalsa|no traga", ["Evacuacion", "Sifon"]),
    (r"sifon", ["Sifon"]),
    (r"desgrasadora|camara", ["Camara Desgrasadora"]),
    (r"meson", ["Meson de Preparacion de Acero inoxidable", "Meson de Desconche"]),
    (r"mueble|vajilla", ["Mueble para vajilla", "Mueble para Articulos de aseo"]),
    (r"estante|estanteria|repisa", ["Estanteria de Bodega"]),
    (r"lavaplatos|lavafondos|lavamanos", ["Lavafondos / Lavaplatos / Lavamanos"]),
    (r"extintor", ["Extintor (soporte, vencimiento)"]),
    (r"dispensador|jabon|toalla", ["Dispensador, jabon y toalla"]),
    (r"botiquin", ["Botiquin"]),
    (r"anclaje|anclar|suelto", ["Anclajes"]),
    (r"senaletica|letrero", ["Senaletica"]),
    (r"carro", ["Carro Transporte"]),
    (r"basurero|contenedor", ["Basureros Cocina y Patio Servicios"]),
    (r"pintura|pintar|hongo|moho|descascar", ["Pintura"]),
]
HECHO = r"(reparaci|cambio|instalaci|reemplazo|ajuste|mantenci|limpieza|retiro)"


def _items_esperados(que):
    t = norm(que)
    out = []
    for rx, its in ITEMS:
        if re.search(r"\b(" + rx + r")", t):
            out += [norm(i) for i in its]
    return list(dict.fromkeys(out))


def _palabras(s):
    stop = set("de la el los las en un una se y o a con por para del al que no hay esta estan muy mas".split())
    return {w for w in re.findall(r"[a-z]{4,}", norm(s)) if w not in stop}


def _evaluar(p, items):
    """('resuelto' | 'revisado' | 'no aparece', ítem que lo respalda)."""
    esperados = _items_esperados(p["que"])
    mejor = None
    for it in items:
        nombre = norm(it.get("item"))
        obs = norm(it.get("observacion"))
        acc = norm(it.get("accion"))
        por_item = any(e and (e in nombre or nombre in e) for e in esperados)
        por_obs = len(_palabras(p["que"]) & _palabras(obs)) >= 1 and bool(obs)
        if not (por_item or por_obs):
            continue
        estado = "resuelto" if re.search(HECHO, acc) else "revisado"
        if not mejor or (estado == "resuelto" and mejor[0] != "resuelto") or (por_item and not mejor[2]):
            mejor = (estado, it, por_item)
    if not mejor:
        return "no aparece", None
    return mejor[0], mejor[1]


def _linea_item(it):
    partes = [it.get("categoria") or "", (it.get("ubicacion") or "").lower()]
    cab = ", ".join(x for x in partes if x)
    txt = f"{it.get('accion') or 'Sin acción'} {it.get('item') or ''}".strip()
    if it.get("cantidad") and str(it["cantidad"]) not in ("1", "0", ""):
        txt += f" ({it['cantidad']})"
    obs = re.sub(r"\s+", " ", it.get("observacion") or "").strip()
    return f"- {cab}: {txt}" + (f". {resumen(obs, 90)}" if obs else "")


def leer_bitacora(pdf):
    try:
        import bitacoras
        cab = bitacoras.leer_pdf(pdf)
        return cab, [i for i in cab.get("items", []) if i.get("accion") or i.get("observacion") or i.get("cantidad")]
    except Exception as e:
        return {"error": str(e)}, []


def cotejar(rbd, d, emulado=False):
    """Baja la bitácora cerrada de ese colegio y día, la lee y la compara con los pendientes de antes del cierre."""
    c = colegio(rbd) or {"rbd": str(rbd), "nombre": f"RBD {rbd}", "jardin": False}
    if c["jardin"]:
        return f"{c['nombre']} es jardín: la bitácora es física, no la puedo leer todavía."
    try:
        D = dc()
        ts = tareas()
    except Exception:
        return "No pude leer Datácora. Prueba en un rato."
    cerradas = [t for t in ts if D.hecha(t) and D.establecimiento(t)[1] == str(rbd) and D.envio_id(t)
                and D.cuando_hecha(t) and D.cuando_hecha(t).date() == d]
    if not cerradas:
        otras = [D.cuando_hecha(t) for t in ts if D.hecha(t) and D.establecimiento(t)[1] == str(rbd) and D.envio_id(t)
                 and D.cuando_hecha(t)]
        ult = f" La última es del {dm(max(otras))}." if otras else ""
        return f"No hay bitácora cerrada de {c['nombre']} el {dm(d)} en Datácora.{ult}"
    t = max(cerradas, key=D.cuando_hecha)
    cierre = D.cuando_hecha(t)
    try:
        _, archivos = D.verificadores(d, d, rbds={str(rbd)}, ids={str(t.get("id"))})
    except Exception:
        archivos = []
    pdf = next((a["ruta"] for a in archivos if a["ruta"].lower().endswith(".pdf")), "")
    if not pdf:
        return f"{c['nombre']}, {d.strftime('%d-%m-%Y')}: no se pudo descargar."
    cab, items = leer_bitacora(pdf)
    tecnico = " ".join((cab.get("tecnico") or D.tecnico(t) or "").split()[:2])
    folio = cab.get("folio") or ""
    lin = [f"Bitácora {c['nombre']}, {dm(d)} {cierre.strftime('%H:%M')}"
           + (f", {tecnico}" if tecnico else "") + (f", folio {folio}" if folio else "")]
    if cab.get("error"):
        lin.append(f"No pude leer el PDF ({resumen(cab['error'], 80)}).")
    elif items:
        lin.append("Trabajos:")
        lin += [_linea_item(i) for i in items[:12]]
        if len(items) > 12:
            lin.append(f"- y {len(items) - 12} más")
    else:
        lin.append("La bitácora no trae trabajos marcados.")
    corte = time.time() if emulado else cierre.timestamp()      # emulado = "el técnico la acaba de cerrar"
    ps = [p for p in abiertos(rbd) if p["ts"] < corte]
    todos_ps = todos()
    if ps:
        lin.append("Pendientes:")
        for p in sorted(ps, key=_orden):
            estado, it = _evaluar(p, items) if items else ("no aparece", None)
            pedido = datetime.fromtimestamp(p["ts"]).strftime("%d-%m")
            if estado == "resuelto":
                lin.append(f"- {resumen(p['que'], 50)} (pedido {pedido}): resuelto ({it.get('accion')} {it.get('item')}).")
            elif estado == "revisado":
                lin.append(f"- {resumen(p['que'], 50)} (pedido {pedido}): lo revisó, sin reparación marcada. Sigue pendiente.")
            else:
                lin.append(f"- {resumen(p['que'], 50)} (pedido {pedido}): no aparece en la bitácora. Sigue pendiente.")
            for q in todos_ps:
                if q["id"] == p["id"]:
                    q.setdefault("cotejos", []).append({"envio": str(D.envio_id(t)), "fecha": d.isoformat(),
                                                        "resultado": estado, "emulado": emulado})
                    if estado == "resuelto":
                        q.update(estado="resuelto", resuelto={"fecha": d.isoformat(), "folio": folio, "pdf": pdf})
        guardar(todos_ps)
    else:
        lin.append("No había pendientes anotados de antes de esa visita.")
    lin.append(f"PDF en Verificadores SOSER/{cierre.strftime('%Y-%m')}.")
    return "\n".join(lin)


def revisar_cierres(forzar=False):
    """Mira (cada 30 min, en horario) si se cerró una visita en un colegio con pendientes; si es así, coteja."""
    ab = [p for p in abiertos() if p.get("rbd") and not p.get("jardin")]
    if not ab:
        return []
    estado_p = _p(".cierres.json")
    est = _json(estado_p, {"t": 0, "vistos": []})
    h = datetime.now().hour
    if not forzar and (time.time() - est["t"] < CADA_REVISION or not (HORARIO[0] <= h < HORARIO[1])):
        return []
    est["t"] = time.time()
    _guardar_json(estado_p, est)
    try:
        D = dc()
        ts = tareas()
    except Exception:
        return []
    rbds = {p["rbd"]: min(x["ts"] for x in ab if x["rbd"] == p["rbd"]) for p in ab}
    avisos = []
    for t in ts:
        if not (D.hecha(t) and D.envio_id(t) and D.cuando_hecha(t)):
            continue
        rbd = D.establecimiento(t)[1]
        sid = str(D.envio_id(t))
        if rbd in rbds and D.cuando_hecha(t).timestamp() > rbds[rbd] and sid not in est["vistos"]:
            est["vistos"].append(sid)
            avisos.append(cotejar(rbd, D.cuando_hecha(t).date()))
    est["vistos"] = est["vistos"][-500:]
    _guardar_json(estado_p, est)
    return avisos


# ================================================================ fechas y comandos
def fecha_en(texto, base=None):
    hoy = base or globals()["hoy"]()
    t = norm(texto)
    if re.search(r"\bantier|anteayer\b", t):
        return hoy - timedelta(days=2)
    if re.search(r"\bayer\b", t):
        return hoy - timedelta(days=1)
    if re.search(r"\bmanana\b", t):
        return hoy + timedelta(days=1)
    m = re.search(r"\b(\d{1,2})\s*[-/]\s*(\d{1,2})(?:\s*[-/]\s*(\d{2,4}))?\b", t)
    if m:
        a = int(m.group(3)) if m.group(3) else hoy.year
        a = a + 2000 if a < 100 else a
        try:
            return date(a, int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    meses = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
             "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
    m = re.search(r"\b(\d{1,2}) de (" + "|".join(meses) + r")\b", t)
    if m:
        return date(hoy.year, meses[m.group(2)], int(m.group(1)))
    return hoy


RX_COMANDO = (r"((ver |lista de |que hay )?pendientes?( de hoy)?|que (hay )?pendiente)$|(emula\w*|simula\w*)\s+(la\s+)?bitacora|"
              r"(la\s+)?ruta\b|(cual es la |dame la |pasame la )ruta|(resuelto|resuelta|listo|lista|cerrar|cerrado|borra|borrar|"
              r"elimina|eliminar|anula|anular)\s+\d+$")


def es_comando(texto):
    return bool(re.match(RX_COMANDO, norm(texto).strip(" !?.")))


def comando(texto):
    """Si el mensaje es un comando de operación, devuelve la respuesta; si no, None."""
    t = norm(texto).strip(" !?.")
    if re.fullmatch(r"(ver |lista de |que hay )?pendientes?( de hoy)?|que (hay )?pendiente", t):
        return listar()
    m = re.match(r"(emula\w*|simula\w*)\s+(la\s+)?bitacora\s*(.*)", t)
    if m:
        resto = m.group(3)
        rbd = rbd_en(resto)
        if not rbd:
            return "¿De qué establecimiento?"
        return cotejar(rbd, fecha_en(resto), emulado=True)
    if re.match(r"(la\s+)?ruta\b", t) or re.fullmatch(r"(cual es la |dame la |pasame la )?ruta.*", t):
        d, h = fecha_en(t), hoy()
        return ruta(d, "Ruta de hoy" if d == h else "Ruta de mañana" if d == h + timedelta(days=1) else f"Ruta del {dm(d)}")
    m = re.fullmatch(r"(resuelto|resuelta|listo|lista|cerrar|cerrado)\s+(\d+)", t)
    if m:
        p = cambiar_estado(int(m.group(2)), "resuelto", "a mano")
        return f"Pendiente {m.group(2)} cerrado." if p else f"No existe el pendiente {m.group(2)}."
    m = re.fullmatch(r"(borra|borrar|elimina|eliminar|anula|anular)\s+(\d+)", t)
    if m:
        p = cambiar_estado(int(m.group(2)), "borrado")
        return f"Pendiente {m.group(2)} borrado." if p else f"No existe el pendiente {m.group(2)}."
    return None


if __name__ == "__main__":
    a = " ".join(sys.argv[1:])
    if not a:
        print(__doc__)
    elif a == "revisar":
        print("\n\n".join(revisar_cierres(forzar=True)) or "Nada nuevo.")
    else:
        print(comando(a) or "No es un comando de operación.")
