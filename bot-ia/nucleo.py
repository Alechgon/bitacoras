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
    """Configuración efectiva: general + perfil activo (ver ajustes.py)."""
    import ajustes
    return ajustes.efectiva()


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


ORDINAL = {1: "1ra", 2: "2da", 3: "3ra", 4: "4ta", 5: "5ta", 6: "6ta", 7: "7ma", 8: "8va"}


def n_bloques(d):
    """Cuántas visitas por técnico y día (sin horarios: el número indica el orden/urgencia)."""
    c = cfg().get("bloques_por_dia", {})
    return int(c.get("viernes", 2) if a_fecha(d).weekday() == 4 else c.get("lunes_a_jueves", 4))


def etiqueta_bloque(b):
    return f"{ORDINAL.get(int(b), str(b) + 'a')} visita"


def bloques(d):
    """{1: '1ra visita', 2: '2da visita', ...} según el día."""
    return {i: etiqueta_bloque(i) for i in range(1, n_bloques(d) + 1)}


def bloque_extra(d):
    return n_bloques(d) + 1


def hora_bloque(d, b):
    """Ya no hay horarios: devuelve '1ra visita', '2da visita'… (o 'visita extra')."""
    return etiqueta_bloque(b) if int(b) in bloques(a_fecha(d)) else "visita extra"


def inicio_bloque(d, b):
    """Hora aproximada en que parte esa visita (solo para saber si ya pasó o si choca con un cierre)."""
    from datetime import time as _t
    M = datos()["META"]
    ref = M["bloquesV"] if a_fecha(d).weekday() == 4 else M["bloquesLJ"]
    ini = {}
    for k, v in ref.items():
        try:
            ini[int(k)] = datetime.strptime(str(v).split("-")[0].strip(), "%H:%M")
        except ValueError:
            pass
    b = int(b)
    if b in ini:
        return ini[b].time()
    base = max(ini) if ini else 1
    h = (ini[base] if ini else datetime.strptime("08:30", "%H:%M")) + timedelta(minutes=150 * (b - base))
    return _t(min(h.hour, 23), h.minute)


def bonita(d):
    d = a_fecha(d)
    return f"{DIAS[d.weekday()]} {d.strftime('%d-%m')}"


def nombre_tec(t):
    return datos()["META"]["tecnicos"].get(t, {}).get("nombre", t).split()[0]


# ================================================================ cuaderno (SQLite)
def db():
    con = sqlite3.connect(DB_PATH, timeout=30)       # si otro hilo está escribiendo, espera en vez de fallar
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")       # leer y escribir a la vez sin trabarse
        con.execute("PRAGMA busy_timeout=30000")
    except sqlite3.OperationalError:
        pass
    con.create_function("REGEXP", 2, lambda p, v: 1 if (v and re.search(p, v, re.I)) else 0)
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
    CREATE TABLE IF NOT EXISTS borradores(
        id INTEGER PRIMARY KEY AUTOINCREMENT, creado TEXT DEFAULT (datetime('now','localtime')),
        origen TEXT, autor TEXT, texto_original TEXT, respuesta TEXT, nota_interna TEXT DEFAULT '',
        rbd INTEGER, crit TEXT, estado TEXT DEFAULT 'pendiente', adjuntos TEXT DEFAULT '[]',
        tarjeta_id TEXT, hallazgo_id INTEGER);
    CREATE TABLE IF NOT EXISTS bitacoras(folio TEXT PRIMARY KEY, rbd INTEGER, establecimiento TEXT,
        fecha TEXT, hora TEXT, comuna TEXT, motivo TEXT, tecnico TEXT, archivo TEXT,
        cargado TEXT DEFAULT (datetime('now','localtime')), n_items INTEGER);
    CREATE TABLE IF NOT EXISTS mensajes(id INTEGER PRIMARY KEY AUTOINCREMENT,
        recibido TEXT DEFAULT (datetime('now','localtime')), origen TEXT, autor TEXT, texto TEXT,
        intencion TEXT, rbd INTEGER, resultado TEXT, motor TEXT);
    CREATE TABLE IF NOT EXISTS observaciones(id INTEGER PRIMARY KEY AUTOINCREMENT,
        recibido TEXT DEFAULT (datetime('now','localtime')), autor TEXT, rbd INTEGER, texto TEXT, resumen TEXT);
    CREATE TABLE IF NOT EXISTS fotos(id INTEGER PRIMARY KEY AUTOINCREMENT,
        recibido TEXT DEFAULT (datetime('now','localtime')), autor TEXT, rbd INTEGER, ruta TEXT,
        caption TEXT, analisis TEXT, hallazgo_id INTEGER);
    CREATE TABLE IF NOT EXISTS bitacora_items(id INTEGER PRIMARY KEY AUTOINCREMENT, folio TEXT,
        rbd INTEGER, categoria TEXT, item TEXT, ubicacion TEXT, cantidad TEXT, accion TEXT, observacion TEXT);
    CREATE TABLE IF NOT EXISTS decisiones(id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, caso INTEGER,
        origen TEXT, supervisora TEXT, rbd INTEGER, estab TEXT, tipo TEXT, crit TEXT, original TEXT, propuesta TEXT,
        decision TEXT, detalle TEXT, texto_final TEXT, tec TEXT, fecha_visita TEXT, bloque TEXT, sync INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS reglas(id TEXT PRIMARY KEY, activa INTEGER, tipo TEXT, alcance TEXT, valor TEXT,
        descripcion TEXT, origen TEXT, creada TEXT, evidencia INTEGER, estado TEXT);
    CREATE TABLE IF NOT EXISTS pedidos_info(id INTEGER PRIMARY KEY AUTOINCREMENT,
        creado TEXT DEFAULT (datetime('now','localtime')), borrador_id INTEGER, rbd INTEGER, autor TEXT,
        pregunta TEXT, estado TEXT DEFAULT 'esperando', respuesta TEXT DEFAULT '', respondido TEXT);
    CREATE TABLE IF NOT EXISTS hilos(id INTEGER PRIMARY KEY AUTOINCREMENT,
        creado TEXT DEFAULT (datetime('now','localtime')), actualizado TEXT DEFAULT (datetime('now','localtime')),
        autor TEXT, texto TEXT, problema TEXT, crit TEXT, rbd INTEGER, cands TEXT DEFAULT '[]', paso TEXT,
        estado TEXT DEFAULT 'abierto', intencion TEXT, hallazgo_id INTEGER, opciones TEXT DEFAULT '[]', libre TEXT,
        msgs TEXT DEFAULT '[]', intentos INTEGER DEFAULT 0, deshacer TEXT, motor TEXT, resultado TEXT);
    CREATE TABLE IF NOT EXISTS ventanas(id INTEGER PRIMARY KEY AUTOINCREMENT,
        creado TEXT DEFAULT (datetime('now','localtime')), autor TEXT, rbd INTEGER, fecha TEXT, desde TEXT,
        hasta TEXT, texto TEXT);
    CREATE TABLE IF NOT EXISTS verificadores(ruta TEXT PRIMARY KEY, mtime REAL, rbd INTEGER, fecha TEXT,
        folio TEXT, origen TEXT, nombre TEXT);
    CREATE TABLE IF NOT EXISTS movimientos(id INTEGER PRIMARY KEY AUTOINCREMENT,
        cuando TEXT DEFAULT (datetime('now','localtime')), tarjeta_id TEXT, rbd INTEGER, clase TEXT,
        de_fecha TEXT, de_tec TEXT, de_bloque INTEGER, a_fecha TEXT, a_tec TEXT, a_bloque INTEGER,
        estado_antes TEXT, estado TEXT, aplaz INTEGER, motivo TEXT);
    -- cada cambio de la agenda queda anotado solo (para la hoja "Movimientos" y el cronograma)
    CREATE TRIGGER IF NOT EXISTS mov_upd AFTER UPDATE OF fecha, tec, bloque, estado ON tarjetas
    WHEN NEW.bloque <> 99 AND (OLD.fecha IS NOT NEW.fecha OR OLD.tec IS NOT NEW.tec OR OLD.estado IS NOT NEW.estado
         OR (OLD.bloque IS NOT NEW.bloque AND OLD.bloque <> 99))
    BEGIN
      INSERT INTO movimientos(tarjeta_id, rbd, clase, de_fecha, de_tec, de_bloque, a_fecha, a_tec, a_bloque,
                              estado_antes, estado, aplaz, motivo)
      VALUES(NEW.id, NEW.rbd, NEW.clase, OLD.fecha, OLD.tec, OLD.bloque, NEW.fecha, NEW.tec, NEW.bloque,
             OLD.estado, NEW.estado, NEW.aplaz, COALESCE((SELECT v FROM meta WHERE k='motivo'), 'bot'));
    END;
    CREATE TRIGGER IF NOT EXISTS mov_ins AFTER INSERT ON tarjetas WHEN NEW.origen = 'bot'
    BEGIN
      INSERT INTO movimientos(tarjeta_id, rbd, clase, a_fecha, a_tec, a_bloque, estado, aplaz, motivo)
      VALUES(NEW.id, NEW.rbd, NEW.clase, NEW.fecha, NEW.tec, NEW.bloque, 'nueva', 0,
             COALESCE((SELECT v FROM meta WHERE k='motivo'), 'bot'));
    END;
    """)
    for alter in ("ALTER TABLE borradores ADD COLUMN recordado INTEGER DEFAULT 0",
                  "ALTER TABLE borradores ADD COLUMN tipo TEXT DEFAULT 'agendar'",
                  "ALTER TABLE hallazgos ADD COLUMN foto TEXT",
                  "ALTER TABLE hilos ADD COLUMN confirmado INTEGER DEFAULT 0",
                  "ALTER TABLE hilos ADD COLUMN detallado INTEGER DEFAULT 0",
                  "ALTER TABLE hallazgos ADD COLUMN insistencias INTEGER DEFAULT 0"):
        try:
            con.execute(alter)            # migración: bases creadas con versiones anteriores
        except sqlite3.OperationalError:
            pass
    sincronizar_plan(con)
    return con


def log(con, evento):
    con.execute("INSERT INTO historial(evento) VALUES(?)", (evento,))


def motivo(con, texto):
    """Por qué cambia la agenda ahora (lo anota el trigger en 'movimientos' y sale en la planilla)."""
    con.execute("INSERT OR REPLACE INTO meta VALUES('motivo', ?)", (str(texto)[:200],))
    con.execute("INSERT OR REPLACE INTO meta VALUES('agenda_cambio', datetime('now','localtime'))")


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
    con.execute("INSERT OR REPLACE INTO meta VALUES('motivo', ?)", (f"Plan regenerado en el panel ({ver})",))
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
    con.execute("INSERT OR REPLACE INTO meta VALUES('motivo', 'bot')")
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


def agendar(con, rbd, crit, problema, prio, autor, hallazgo_id=None, desde=None):
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
    if desde and a_fecha(desde) > inicio:       # plan del día: lo que no elegiste va DESPUÉS de lo tuyo
        inicio = sig_habil(a_fecha(desde))
        limite = max(limite, inicio)
    texto_corr = f"CORRECTIVO ({autor.split()[0] if autor else 'supervisora'}): {problema}"
    motivo(con, f"Falla {crit} en {e['nombre']} ({autor or 'supervisora'}): {problema[:80]}")

    # --- 0) ya tiene visita dentro del plazo
    ya = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' AND fecha BETWEEN ? AND ? "
                     "ORDER BY fecha LIMIT 1", (rbd, inicio.isoformat(), limite.isoformat())).fetchone()
    if ya:
        _fusionar(con, ya, crit, pts, texto_corr, hallazgo_id)
        return dict(tarjeta=ya["id"], tec=ya["tec"], fecha=a_fecha(ya["fecha"]), bloque=ya["bloque"], pts=max(pts, ya["pts"]),
                    detalle_pts=detalle_pts, limite=limite, modo="fusion", movida=None)

    futura = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' AND fecha>? "
                         "ORDER BY fecha LIMIT 1", (rbd, limite.isoformat())).fetchone()

    try:
        import memoria                       # una regla aprendida ("en gas, Camilo") manda sobre la config
        pref = memoria.tecnico_para(crit, rbd, con)
    except Exception:
        pref = None
    pref = pref or c.get("preferencia_tecnico", {}).get(crit)
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
    tid, modo = colocar(tec, d, bloque_extra(d), sobrecupo=True)
    return resultado(tid, modo, tec, d, bloque_extra(d))


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


# ================================================================ colocar a mano (tus órdenes y el plan del día)
def postergar(con, t, desde, evitar=None):
    """
    Mueve la tarjeta t al primer bloque libre desde 'desde' (mismo técnico; si no, el otro).
    Busca dentro de su límite y, si no cabe, hasta 10 días hábiles más (avisando).
    Devuelve dict(de, a, bloque, tec, paso_limite) o None.
    """
    lim = a_fecha(t["limite"]) or desde
    tecs = [t["tec"]] + [x for x in datos()["META"]["tecnicos"] if x != t["tec"]]
    nom = datos()["E"].get(t["rbd"], {}).get("nombre", t["rbd"])
    if cfg().get("postergar", "dia_siguiente") == "dia_siguiente":
        # tu regla: lo que se corre, se corre UN día hábil nomás (tú después vas ordenando)
        nd = sumar_habiles(a_fecha(t["fecha"]), 1)
        b0 = t["bloque"] if t["bloque"] <= n_bloques(nd) else 1
        opciones = [(t["tec"], b0)] + [(t["tec"], x) for x in libres(con, t["tec"], nd) if x != b0] + \
                   [(x, b0) for x in tecs[1:]]
        elegido = next(((tc, bl) for tc, bl in opciones if bl in libres(con, tc, nd)
                        and not (evitar and (tc, nd, bl) in evitar)), None)
        tc, bl = elegido or (t["tec"], bloque_extra(nd))
        con.execute("UPDATE tarjetas SET fecha=?, bloque=?, tec=?, aplaz=aplaz+1, modificada=1 WHERE id=?",
                    (nd.isoformat(), bl, tc, t["id"]))
        log(con, f"Postergada un día {nom} ({t['clase']}) de {t['fecha']} b{t['bloque']} a {nd} b{bl} {tc}")
        return dict(id=t["id"], rbd=t["rbd"], nombre=nom, de=a_fecha(t["fecha"]), a=nd, bloque=bl, tec=tc,
                    tec_antes=t["tec"], paso_limite=nd > lim and t["clase"] in MOVIBLES, clase=t["clase"],
                    extra=elegido is None)
    hasta_max = sumar_habiles(max(lim, desde), 10)
    for tope, paso in ((lim, False), (hasta_max, True)):
        for tec in tecs:
            for d in habiles_entre(desde, tope):
                for b in libres(con, tec, d):
                    if evitar and (tec, d, b) in evitar:
                        continue
                    con.execute("UPDATE tarjetas SET fecha=?, bloque=?, tec=?, aplaz=aplaz+1, modificada=1 WHERE id=?",
                                (d.isoformat(), b, tec, t["id"]))
                    log(con, f"Postergada {nom} ({t['clase']}) de {t['fecha']} b{t['bloque']} a {d} b{b} {tec}")
                    return dict(id=t["id"], rbd=t["rbd"], nombre=nom, de=a_fecha(t["fecha"]), a=d, bloque=b, tec=tec,
                                tec_antes=t["tec"], paso_limite=paso and d > lim, clase=t["clase"])
    return None


def colocar_forzado(con, rbd, crit, problema, prio, autor, hallazgo_id, tec=None, d=None, b=None, tarjeta_id=None):
    """
    Pone una visita donde TÚ digas. Lo que estaba en ese bloque se posterga al siguiente hueco
    (respetando su límite si se puede). Si ya había visita a ese colegio ese día, se juntan.
    Devuelve un dict como agendar() + 'postergadas': [...]
    """
    D = datos()
    e = D["E"][rbd]
    tecs = list(D["META"]["tecnicos"])
    d = sig_habil(a_fecha(d) or hoy())
    pts, detalle_pts = puntaje(e, crit or "OTRO", prio)
    texto_corr = f"CORRECTIVO ({autor.split()[0] if autor else 'supervisora'}): {problema}"
    postergadas = []
    propia = con.execute("SELECT * FROM tarjetas WHERE id=?", (tarjeta_id,)).fetchone() if tarjeta_id else None

    # ya hay visita a ese colegio ese día (y no es la misma tarjeta): se junta
    misma = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND fecha=? AND estado='programada' AND id<>?",
                        (rbd, d.isoformat(), tarjeta_id or "")).fetchone()
    if misma and not b and (not tec or tec == misma["tec"]):
        _fusionar(con, misma, crit or "OTRO", pts, texto_corr, hallazgo_id)
        if propia:
            con.execute("UPDATE tarjetas SET estado='anulada', modificada=1 WHERE id=?", (propia["id"],))
        return dict(tarjeta=misma["id"], tec=misma["tec"], fecha=d, bloque=misma["bloque"], pts=max(pts, misma["pts"]),
                    detalle_pts=detalle_pts, limite=d, modo="fusion", movida=None, antes=None, postergadas=[])

    if not tec:
        try:
            import memoria
            tec = memoria.tecnico_para(crit, rbd, con)
        except Exception:
            tec = None
        tec = tec or cfg().get("preferencia_tecnico", {}).get(crit)
        if tec not in tecs or (b is None and not libres(con, tec, d)) or (b and b in ocupados(con, tec, d)):
            # el que tenga el bloque pedido libre, o más bloques libres ese día, o el más cerca
            tec = sorted(tecs, key=lambda x: (b in ocupados(con, x, d) if b else 0, -len(libres(con, x, d)),
                                              distancia(con, x, d, e)))[0]
    if propia and propia["fecha"] == d.isoformat() and propia["tec"] == tec and (not b or propia["bloque"] == b):
        b = propia["bloque"]               # ya está ahí
    else:
        if b is None:
            lb = libres(con, tec, d)
            b = lb[0] if lb else None
        if b is None:                      # día lleno: se posterga lo de menor puntaje que se pueda mover
            cands = con.execute("SELECT * FROM tarjetas WHERE tec=? AND fecha=? AND estado='programada' "
                                "AND COALESCE(crit,'')<>'GAS' AND id<>? ORDER BY "
                                "CASE WHEN clase IN ('VISITA','PREVENTIVA') THEN 0 ELSE 1 END, pts ASC",
                                (tec, d.isoformat(), tarjeta_id or "")).fetchall()
            b = cands[0]["bloque"] if cands else bloque_extra(d)
        ocupante = con.execute("SELECT * FROM tarjetas WHERE tec=? AND fecha=? AND bloque=? AND estado='programada' "
                               "AND id<>?", (tec, d.isoformat(), b, tarjeta_id or "")).fetchone()
        if ocupante and b <= n_bloques(d):
            # libera el bloque (la propia se mueve después, así su hueco viejo queda disponible)
            con.execute("UPDATE tarjetas SET bloque=99 WHERE id=?", (ocupante["id"],))
            ocup = dict(ocupante)
            mov = postergar(con, ocup, d, evitar={(tec, d, b)})
            if mov:
                postergadas.append(mov)
            else:
                con.execute("UPDATE tarjetas SET bloque=?, fecha=?, modificada=1 WHERE id=?",
                            (bloque_extra(d), d.isoformat(), ocupante["id"]))
    antes = a_fecha(propia["fecha"]) if propia else None
    if propia:
        _fusionar(con, propia, crit or "OTRO", pts, texto_corr, hallazgo_id) if propia["hallazgo_id"] != hallazgo_id else None
        con.execute("UPDATE tarjetas SET fecha=?, tec=?, bloque=?, limite=MAX(COALESCE(limite,''),?), modificada=1 "
                    "WHERE id=?", (d.isoformat(), tec, b, d.isoformat(), propia["id"]))
        tid, modo = propia["id"], "reprogramada"
    else:
        tid, modo = _nuevo_id(con), "a_mano"
        while con.execute("SELECT 1 FROM tarjetas WHERE id=?", (tid,)).fetchone():
            tid = tid[:-3] + f"{int(tid[-3:]) + 1:03d}"
        con.execute("INSERT INTO tarjetas(id,fecha,tec,bloque,rbd,clase,detalle,pts,crit,estado,aplaz,origen,limite,"
                    "modificada,hallazgo_id) VALUES(?,?,?,?,?,?,?,?,?,'programada',0,'bot',?,1,?)",
                    (tid, d.isoformat(), tec, b, rbd, "CORRECTIVO URGENTE", texto_corr, pts, crit or "OTRO",
                     d.isoformat(), hallazgo_id))
    log(con, f"Colocada a mano {e['nombre']} -> {tec} {d} b{b}" +
        (f" (postergó {', '.join(p['nombre'] for p in postergadas)})" if postergadas else ""))
    movida = None
    if postergadas:
        p = postergadas[0]
        movida = {"nombre": p["nombre"], "de": p["de"], "a": p["a"], "tec": p["tec"]}
    return dict(tarjeta=tid, tec=tec, fecha=d, bloque=b, pts=pts, detalle_pts=detalle_pts, limite=d,
                modo=modo + ("+extra" if b > n_bloques(d) else ""), movida=movida, antes=antes, postergadas=postergadas)
