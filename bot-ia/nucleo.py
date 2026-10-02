"""
nucleo.py — el "capataz". Lee tu datos.js (el mismo del panel), guarda la agenda
viva en un cuaderno SQLite y aplica TUS reglas: puntaje 1-20 con los pesos del
panel, bloques por técnico, metas JUNAEB / jardines y la regla de aplazamiento.
Aquí no hay IA: todo es determinista y repetible.
"""
import json, math, os, re, sqlite3, unicodedata
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "agenda.db")
CFG_PATH = os.path.join(BASE, "config.json")
DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
PESO_FALLA = ["GAS", "FRIO", "AGUA", "ELEC", "EQUIPO", "OTRO"]
MOVIBLES = ("VISITA", "PREVENTIVA")          # solo estas clases se pueden aplazar


# ================================================================ config y datos
def cfg():
    with open(CFG_PATH, encoding="utf-8") as f:
        return json.load(f)


_cache = {"mtime": None, "datos": None}


def datos():
    """Lee datos.js (window.SOSER = {...}) y lo deja en caché hasta que cambie."""
    ruta = os.path.normpath(os.path.join(BASE, cfg()["datos_js"]))
    mt = os.path.getmtime(ruta)
    if _cache["mtime"] != mt:
        txt = open(ruta, encoding="utf-8").read()
        d = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        d["E"] = {e["rbd"]: e for e in d["ESTAB"]}
        _cache.update(mtime=mt, datos=d)
    return _cache["datos"]


# ================================================================ calendario
def hoy():
    return date.today()


def a_fecha(x):
    if not x:
        return None
    if isinstance(x, date):
        return x
    try:
        return datetime.strptime(str(x)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def es_habil(d):
    return d.weekday() < 5 and d.isoformat() not in datos()["META"]["feriados"]


def sumar_habiles(d, n):
    while n > 0:
        d += timedelta(days=1)
        if es_habil(d):
            n -= 1
    return d


def sig_habil(d):
    return d if es_habil(d) else sumar_habiles(d, 1)


def habiles_entre(desde, hasta):
    d = desde
    while d <= hasta:
        if es_habil(d):
            yield d
        d += timedelta(days=1)


def bloques(d):
    M = datos()["META"]
    b = M["bloquesV"] if d.weekday() == 4 else M["bloquesLJ"]
    return {int(k): v for k, v in b.items()}


def hora_bloque(d, b):
    return bloques(a_fecha(d)).get(int(b), "bloque extra")


def bonita(d):
    d = a_fecha(d)
    return f"{DIAS[d.weekday()]} {d.strftime('%d-%m')}"


def nombre_tec(t):
    return datos()["META"]["tecnicos"].get(t, {}).get("nombre", t).split()[0]


# ================================================================ cuaderno (SQLite)
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript("""
    CREATE TABLE IF NOT EXISTS tarjetas(
        id TEXT PRIMARY KEY, fecha TEXT, tec TEXT, bloque INTEGER, rbd INTEGER, clase TEXT,
        detalle TEXT, pts INTEGER, crit TEXT, estado TEXT DEFAULT 'programada', aplaz INTEGER DEFAULT 0,
        origen TEXT, limite TEXT, modificada INTEGER DEFAULT 0, hallazgo_id INTEGER);
    CREATE TABLE IF NOT EXISTS hallazgos(
        id INTEGER PRIMARY KEY AUTOINCREMENT, recibido TEXT, autor TEXT, texto TEXT, rbd INTEGER,
        problema TEXT, crit TEXT, prio INTEGER DEFAULT 0, pts INTEGER, tarjeta_id TEXT, estado TEXT,
        candidatos TEXT, respuesta TEXT, motor TEXT);
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS historial(id INTEGER PRIMARY KEY AUTOINCREMENT,
        cuando TEXT DEFAULT (datetime('now','localtime')), evento TEXT);
    """)
    sincronizar_plan(con)
    return con


def log(con, evento):
    con.execute("INSERT INTO historial(evento) VALUES(?)", (evento,))


def limite_de_tarjeta(p, e):
    M = datos()["META"]
    clase = p.get("clase", "")
    if clase == "VISITA" and e and e["inst"] == "Junaeb":
        return M["metaJunaeb"]
    if clase == "PREVENTIVA":
        return M["metaJardines"]
    if clase == "VISITA":
        return M["fin"]
    return p["fecha"]          # correctivos: no se mueven solos


def sincronizar_plan(con):
    """Carga el plan de datos.js. Si regeneraste datos.js, actualiza lo que el bot no ha tocado."""
    D = datos()
    ver = D["META"]["version"]
    fila = con.execute("SELECT v FROM meta WHERE k='version'").fetchone()
    if fila and fila["v"] == ver:
        return
    ids = set()
    for p in D["PLAN"]:
        if p.get("origen") != "plan":
            continue
        ids.add(p["id"])
        e = D["E"].get(p["rbd"])
        vals = (p["fecha"], p["tec"], p["bloque"], p["rbd"], p["clase"], p["detalle"], p["pts"], p.get("crit") or "",
                p["estado"], p.get("aplaz", 0), limite_de_tarjeta(p, e), p["id"])
        existe = con.execute("SELECT modificada FROM tarjetas WHERE id=?", (p["id"],)).fetchone()
        if not existe:
            con.execute("INSERT INTO tarjetas(fecha,tec,bloque,rbd,clase,detalle,pts,crit,estado,aplaz,limite,id,origen)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'plan')", vals)
        elif not existe["modificada"]:
            con.execute("UPDATE tarjetas SET fecha=?,tec=?,bloque=?,rbd=?,clase=?,detalle=?,pts=?,crit=?,estado=?,"
                        "aplaz=?,limite=? WHERE id=?", vals)
    if ids:
        marcas = ",".join("?" * len(ids))
        con.execute(f"DELETE FROM tarjetas WHERE origen='plan' AND modificada=0 AND estado='programada' "
                    f"AND id NOT IN ({marcas})", list(ids))
    con.execute("INSERT OR REPLACE INTO meta VALUES('version',?)", (ver,))
    log(con, f"Plan sincronizado con datos.js versión {ver}")
    con.commit()


# ================================================================ encontrar establecimiento
def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


RUIDO = r"\b(escuela|esc|liceo|lic|colegio|complejo|educacional|centro|jardin|infantil|ji|sala|cuna|sc|basica|" \
        r"especial|rbd|n|nro|numero|el|la|los|las|de|del|y|en)\b"


def _limpio(s):
    return re.sub(r"\s+", " ", re.sub(RUIDO, " ", norm(s))).strip()


def _parecido(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    base = SequenceMatcher(None, a, b).ratio()
    corto, largo = (a, b) if len(a) <= len(b) else (b, a)
    n, mejor = len(corto), 0.0
    for i in range(0, max(1, len(largo) - n + 1)):
        mejor = max(mejor, SequenceMatcher(None, corto, largo[i:i + n]).ratio())
    ta, tb = set(a.split()), set(b.split())
    tok = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(base, mejor * 0.95, tok * 0.9)


def en_texto(texto):
    """Lo mismo que hace el panel: RBD escrito o alias del diccionario dentro del mensaje."""
    D = datos()
    t = norm(texto)
    hits = []
    for x in re.findall(r"\b\d{4,6}\b", texto):
        if int(x) in D["E"] and int(x) not in hits:
            hits.append(int(x))
    for k in sorted(D["ALIAS"], key=len, reverse=True):
        if len(k) > 3 and re.search(rf"\b{re.escape(k)}\b", t):
            r = D["ALIAS"][k]
            if r in D["E"] and r not in hits:
                hits.append(r)
    return hits


def buscar(nombre):
    """Búsqueda difusa por nombre, unidades y alias. Devuelve [(0-100, rbd)]."""
    D = datos()
    q = _limpio(nombre)
    if not q:
        return []
    res = {}
    for e in D["ESTAB"]:
        nombres = [e["nombre"]] + e.get("unidades", [])
        res[e["rbd"]] = max(_parecido(q, _limpio(n)) for n in nombres)
    for k, r in D["ALIAS"].items():
        if r in res:
            res[r] = max(res[r], _parecido(q, _limpio(k)))
    return sorted(((round(p * 100), r) for r, p in res.items()), reverse=True)[:5]


# ================================================================ puntaje (pesos del panel)
def desglose(e):
    """Parte el 'why' del establecimiento: base fija y partes de falla abierta."""
    base, falla, extra = 0, 0, 0
    for parte in (e.get("why") or "").split(";"):
        m = re.match(r"\s*(.*?)\s*\+(\d+)\s*$", parte)
        if not m:
            continue
        etiqueta, pts = m.group(1), int(m.group(2))
        if etiqueta.startswith("falla"):
            falla = max(falla, pts)
        elif "días sin atender" in etiqueta or etiqueta.startswith("prioridad"):
            extra += pts
        else:
            base += pts
    return base, falla, extra


def es_prioridad(texto):
    t = norm(texto)
    return any(norm(p) in t for p in cfg().get("palabras_prioridad", []))


def puntaje(e, crit, prio):
    P = datos()["META"]["pesos"]
    base, falla_vieja, extra = desglose(e)
    pts = base + max(P.get(crit, 1), falla_vieja) + extra
    detalle = f"base {base} + falla {crit} {max(P.get(crit, 1), falla_vieja)}"
    if extra:
        detalle += f" + abierta {extra}"
    if prio and "prioridad" not in (e.get("why") or ""):
        pts += P["prioridad"]
        detalle += f" + prioridad {P['prioridad']}"
    return max(1, min(20, pts)), detalle


# ================================================================ agenda
def ocupados(con, tec, d):
    return {r[0] for r in con.execute("SELECT bloque FROM tarjetas WHERE tec=? AND fecha=? AND estado='programada'",
                                      (tec, d.isoformat()))}


def libres(con, tec, d):
    return sorted(set(bloques(d)) - ocupados(con, tec, d))


def distancia(con, tec, d, e):
    """Km a la tarjeta más cercana que el técnico ya tiene ese día (para acoplar sectores)."""
    E = datos()["E"]
    mejor = 99.0
    for r in con.execute("SELECT rbd FROM tarjetas WHERE tec=? AND fecha=? AND estado='programada'",
                         (tec, d.isoformat())):
        o = E.get(r[0])
        if o and o.get("lat") and e.get("lat"):
            km = math.hypot((o["lat"] - e["lat"]) * 111, (o["lon"] - e["lon"]) * 92)
            mejor = min(mejor, km)
    return mejor


def _nuevo_id(con):
    n = con.execute("SELECT COUNT(*) FROM tarjetas WHERE origen='bot'").fetchone()[0] + 1
    return f"B{datetime.now().strftime('%m%d')}-{n:03d}"


def _hueco_posterior(con, t, desde):
    lim = a_fecha(t["limite"]) or desde
    for d in habiles_entre(desde, lim):
        lb = libres(con, t["tec"], d)
        if lb:
            return d, lb[0]
    return None, None


def agendar(con, rbd, crit, problema, prio, autor, hallazgo_id=None):
    """
    Programa un hallazgo con TUS reglas. Orden de búsqueda:
      0) si el establecimiento ya tiene visita dentro del plazo -> se cierra en esa visita
      1) bloque libre dentro del plazo (técnico preferido por tipo de falla, luego el más cercano)
      2) aplazar UNA visita/preventiva de menor puntaje que nunca se haya aplazado,
         sin pasarla de su meta (JUNAEB 30-oct, jardines 15-dic). Gas no se aplaza nunca.
      3) bloque extra en la fecha límite (las emergencias no tienen límite) y avisa
    Si ya tenía una visita más adelante, en vez de crear otra se ADELANTA esa.
    """
    c = cfg()
    D = datos()
    e = D["E"][rbd]
    pts, detalle_pts = puntaje(e, crit, prio)
    plazo = min(10, c["plazo_habiles"].get(crit, 10))
    if prio:
        plazo = min(plazo, c.get("plazo_si_prioridad", 2))
    inicio_meta = a_fecha(D["META"]["inicio"])
    base = max(hoy(), inicio_meta)
    ahora = datetime.now()
    corte = datetime.strptime(c.get("gas_hoy_si_antes_de", "12:30"), "%H:%M").time()
    if crit == "GAS" and es_habil(base) and (base > hoy() or ahora.time() < corte):
        inicio = base
    else:
        inicio = sumar_habiles(base, 1) if es_habil(base) else sig_habil(base)
    limite = sumar_habiles(inicio, plazo - 1) if plazo > 1 else inicio
    texto_corr = f"CORRECTIVO ({autor.split()[0] if autor else 'supervisora'}): {problema}"

    # --- 0) ya tiene visita dentro del plazo
    ya = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' AND fecha BETWEEN ? AND ? "
                     "ORDER BY fecha LIMIT 1", (rbd, inicio.isoformat(), limite.isoformat())).fetchone()
    if ya:
        _fusionar(con, ya, crit, pts, texto_corr, hallazgo_id)
        return dict(tarjeta=ya["id"], tec=ya["tec"], fecha=a_fecha(ya["fecha"]), bloque=ya["bloque"], pts=max(pts, ya["pts"]),
                    detalle_pts=detalle_pts, limite=limite, modo="fusion", movida=None)

    futura = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' AND fecha>? "
                         "ORDER BY fecha LIMIT 1", (rbd, limite.isoformat())).fetchone()

    pref = c.get("preferencia_tecnico", {}).get(crit)
    tecs = list(D["META"]["tecnicos"])
    # gas: primero solo el instalador de gas certificado; si no puede, cualquiera
    fases = [[pref], tecs] if (crit == "GAS" and pref in tecs) else [tecs]

    def orden(grupo, d):
        if len(grupo) == 1:
            return grupo
        return sorted(grupo, key=lambda t: (t != pref, distancia(con, t, d, e), len(ocupados(con, t, d))))

    def colocar(tec, d, b, sobrecupo=False):
        if futura:   # adelantar la que ya existía en vez de duplicar
            _fusionar(con, futura, crit, pts, texto_corr, hallazgo_id)
            con.execute("UPDATE tarjetas SET fecha=?, tec=?, bloque=?, modificada=1 WHERE id=?",
                        (d.isoformat(), tec, b, futura["id"]))
            log(con, f"Adelantada {e['nombre']} de {futura['fecha']} a {d} por hallazgo {crit}")
            return futura["id"], "adelantada+extra" if sobrecupo else "adelantada"
        tid = _nuevo_id(con)
        con.execute("INSERT INTO tarjetas(id,fecha,tec,bloque,rbd,clase,detalle,pts,crit,estado,aplaz,origen,limite,"
                    "modificada,hallazgo_id) VALUES(?,?,?,?,?,?,?,?,?,'programada',0,'bot',?,1,?)",
                    (tid, d.isoformat(), tec, b, rbd, "CORRECTIVO URGENTE", texto_corr, pts, crit,
                     limite.isoformat(), hallazgo_id))
        return tid, "sobrecupo" if sobrecupo else "nueva"

    def resultado(tid, modo, tec, d, b, movida=None):
        return dict(tarjeta=tid, tec=tec, fecha=d, bloque=b, pts=pts, detalle_pts=detalle_pts, limite=limite,
                    modo=modo, movida=movida, antes=a_fecha(futura["fecha"]) if futura else None)

    for grupo in fases:
        # --- 1) bloque libre
        for d in habiles_entre(inicio, limite):
            for tec in orden(grupo, d):
                lb = libres(con, tec, d)
                if lb:
                    tid, modo = colocar(tec, d, lb[0])
                    return resultado(tid, modo, tec, d, lb[0])
        # --- 2) aplazar una visita/preventiva de menor puntaje (una sola vez)
        for d in habiles_entre(inicio, limite):
            for tec in orden(grupo, d):
                cands = con.execute(
                    f"SELECT * FROM tarjetas WHERE tec=? AND fecha=? AND estado='programada' AND aplaz=0 "
                    f"AND clase IN ({','.join('?' * len(MOVIBLES))}) AND COALESCE(crit,'')<>'GAS' "
                    f"AND rbd<>? ORDER BY pts ASC, limite DESC", (tec, d.isoformat(), *MOVIBLES, rbd)).fetchall()
                for t in cands:
                    nd, nb = _hueco_posterior(con, t, sumar_habiles(d, 1))
                    if nd:
                        con.execute("UPDATE tarjetas SET fecha=?, bloque=?, aplaz=aplaz+1, pts=MIN(20,pts+1), "
                                    "modificada=1 WHERE id=?", (nd.isoformat(), nb, t["id"]))
                        nom = D["E"].get(t["rbd"], {}).get("nombre", t["rbd"])
                        log(con, f"Aplazada {nom} ({t['clase']}) de {t['fecha']} b{t['bloque']} a {nd} b{nb}")
                        tid, modo = colocar(tec, d, t["bloque"])
                        return resultado(tid, modo, tec, d, t["bloque"],
                                         movida={"nombre": nom, "de": d, "a": nd, "tec": t["tec"]})

    # --- 3) bloque extra
    tec = pref if pref in tecs else tecs[0]
    d = inicio if crit == "GAS" else limite
    tid, modo = colocar(tec, d, c.get("bloque_extra", 4), sobrecupo=True)
    return resultado(tid, modo, tec, d, c.get("bloque_extra", 4))


def _fusionar(con, t, crit, pts, texto_corr, hallazgo_id):
    clase = t["clase"]
    if clase == "VISITA":
        clase = "VISITA + CORRECTIVO"
    elif clase == "PREVENTIVA":
        clase = "PREV + CORRECTIVO"
    peso = datos()["META"]["pesos"]
    crit_final = crit if peso.get(crit, 1) >= peso.get(t["crit"] or "OTRO", 1) else t["crit"]
    con.execute("UPDATE tarjetas SET clase=?, detalle=?, pts=MAX(pts,?), crit=?, modificada=1, "
                "hallazgo_id=COALESCE(hallazgo_id,?) WHERE id=?",
                (clase, f"{t['detalle']}  ||  {texto_corr}", pts, crit_final, hallazgo_id, t["id"]))


def agenda(con, desde, hasta, tec=None):
    q = "SELECT * FROM tarjetas WHERE estado='programada' AND fecha BETWEEN ? AND ?"
    p = [desde.isoformat(), hasta.isoformat()]
    if tec:
        q += " AND tec=?"
        p.append(tec)
    return con.execute(q + " ORDER BY fecha, tec, bloque", p).fetchall()


def metas(con):
    """Avance de las dos reglas del plan."""
    D = datos()
    hechas = {r[0] for r in con.execute("SELECT rbd FROM tarjetas WHERE estado='realizada'")}
    jun = [e for e in D["ESTAB"] if e["inst"] == "Junaeb"]
    jar = [e for e in D["ESTAB"] if e["inst"] != "Junaeb"]
    jun_ok = sum(1 for e in jun if e.get("enDatacora") or e["rbd"] in hechas)
    prev_hechas = {r[0] for r in con.execute(
        "SELECT rbd FROM tarjetas WHERE estado='realizada' AND clase LIKE 'PREV%'")}
    jar_ok = sum(1 for e in jar if e.get("prevOK") or e["rbd"] in prev_hechas)
    return {"junaeb": (jun_ok, len(jun), D["META"]["metaJunaeb"]),
            "jardines": (jar_ok, len(jar), D["META"]["metaJardines"])}
