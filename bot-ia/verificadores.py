"""
verificadores.py — las bitácoras en PDF como verificador, a pedido en el grupo.

Tú guardas los PDF en la carpeta "datacora" del teléfono (el bot la encuentra sola en el almacenamiento).
Sirve cualquier nombre que diga el colegio y la fecha, o el nombre que pone Datácora:
    Nemesio Antunez 30-09-2026.pdf · Nemesio Antúnez, 30.09.2026.pdf · 2026-09-30 Nemesio.pdf
    Bit_cora_Mantenci_n_N__Folio_621_RBD_25575.pdf   (el colegio sale del RBD y la fecha se lee del PDF)
También entran las bitácoras que le mandas al bot por WhatsApp (carpeta archivo/).

En el grupo:
    Carla: necesito el verificador del Nemesio Antúnez
    Bot:   Del Nemesio Antúnez tengo estas bitácoras:
           1. 30-09-2026 (folio 621)
           2. 12-09-2026
           ¿Cuál necesitas? Dime el número.
    Carla: la 2
    Bot:   Ahí va la del 12-09-2026.   [PDF adjunto]
Si hay una sola, la manda de una. Si no hay ninguna, te avisa a ti.
"""
import json, os, re, time
from datetime import date, datetime

from nucleo import BASE, buscar, cfg, datos, en_texto, log, norm

PIDE_RX = r"\b(verificador|verificadores|verificacion|respaldo de la visita|respaldo de visita|comprobante de (la )?visita)\b"
VERBO_RX = (r"\b(necesito|necesita|necesitan|necesitamos|mandame|mandeme|manda|mandan|envia|enviame|envien|enviar|"
            r"mandar|pasame|pasa|pasan|adjunta|adjuntar|adjuntame|tienes|tiene|tienen|hay|puedes|pueden|me falta|falta)\b")
NO_ES = r"\b(que se hizo|que hicieron|que dice|por que|porque|cuando|como quedo)\b"
MESES = {m: i for i, m in enumerate(["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov",
                                     "dic"], start=1)}
_ultimo_indice = {"t": 0}


def conf():
    return cfg().get("verificadores", {})


def es_pedido(texto):
    if not conf().get("activa", True):
        return False
    t = norm(texto)
    if re.search(PIDE_RX, t):
        return True
    return bool(re.search(r"\bbitacoras?\b", t) and re.search(VERBO_RX, t) and not re.search(NO_ES, t))


# ---------------------------------------------------------------- índice de PDFs
_encontradas = {"t": 0, "rutas": []}


def _buscar_por_nombre(nombre, raiz="~/storage/shared", prof=3):
    """Busca en el almacenamiento del teléfono carpetas que se llamen así (sin importar mayúsculas ni tildes)."""
    if time.time() - _encontradas["t"] < 600:
        return _encontradas["rutas"]
    raiz = os.path.expanduser(raiz)
    out = []
    if os.path.isdir(raiz):
        base = raiz.rstrip(os.sep).count(os.sep)
        for d, subs, _ in os.walk(raiz):
            if d.count(os.sep) - base >= prof:
                subs[:] = []
                continue
            subs[:] = [x for x in subs if not x.startswith(".") and x.lower() != "android"]
            if norm(os.path.basename(d)) == norm(nombre):
                out.append(d)
    _encontradas.update(t=time.time(), rutas=out)
    return out


def carpetas():
    out = [os.path.expanduser(c) for c in conf().get("carpetas", ["~/storage/shared/Documents/Datacora"])]
    if conf().get("nombre_carpeta", "datacora"):
        out += _buscar_por_nombre(conf().get("nombre_carpeta", "datacora"))
    out.append(os.path.join(BASE, cfg().get("archivo_carpeta", "archivo")))
    vistos, res = set(), []
    for c in out:
        r = os.path.realpath(c)
        if os.path.isdir(c) and r not in vistos:
            vistos.add(r)
            res.append(c)
    return res


def _fecha_de_nombre(n):
    s = n.lower()
    m = re.search(r"(20\d{2})[-_. ](\d{1,2})[-_. ](\d{1,2})", s)
    if m:
        return _f(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(?<!\d)(\d{1,2})[-_. ](\d{1,2})[-_. ](\d{2,4})(?!\d)", s)
    if m:
        a = int(m.group(3))
        return _f(a + 2000 if a < 100 else a, int(m.group(2)), int(m.group(1)))
    m = re.search(r"(?<!\d)(\d{1,2})\s*(?:de\s*)?(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)[a-z]*\.?\s*"
                  r"(?:de\s*)?(20\d{2})?", s)
    if m:
        return _f(int(m.group(3) or date.today().year), MESES[m.group(2)], int(m.group(1)))
    m = re.search(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)", s)
    if m:
        return _f(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _f(a, m, d):
    try:
        return date(a, m, d).isoformat()
    except ValueError:
        return None


def _rbd_de_nombre(ruta):
    E = datos()["E"]
    n = os.path.basename(ruta)
    m = re.search(r"rbd[\s_-]*(\d{4,6})", n, re.I)
    if m and int(m.group(1)) in E:
        return int(m.group(1))
    carpeta = os.path.basename(os.path.dirname(ruta))            # archivo/8489_TERESA_PRAT/...
    m = re.match(r"(\d{4,6})_", carpeta)
    if m and int(m.group(1)) in E:
        return int(m.group(1))
    limpio = re.sub(r"\.pdf$", "", n, flags=re.I)
    limpio = re.sub(r"\d{1,4}[-_. ]\d{1,2}[-_. ]\d{2,4}|folio[\s_-]*\d+|bit[aá_]?cora|verificador|mantenci[oó_]?n|"
                    r"preventiva|correctiva|visita|[_]+", " ", limpio, flags=re.I)
    hits = en_texto(limpio)
    if hits:
        return hits[0]
    top = buscar(limpio)
    return top[0][1] if top and top[0][0] >= 80 else None


def indexar(con, forzar=False):
    """Revisa las carpetas (como mucho una vez por minuto) y anota cada PDF con su colegio y fecha."""
    if not forzar and time.time() - _ultimo_indice["t"] < 60:
        return
    _ultimo_indice["t"] = time.time()
    vistos = set()
    for c in carpetas():
        for raiz, _, archivos in os.walk(c):
            for a in archivos:
                if not a.lower().endswith(".pdf"):
                    continue
                ruta = os.path.join(raiz, a)
                vistos.add(ruta)
                mt = os.path.getmtime(ruta)
                fila = con.execute("SELECT mtime FROM verificadores WHERE ruta=?", (ruta,)).fetchone()
                if fila and fila["mtime"] == mt:
                    continue
                rbd, fecha = _rbd_de_nombre(ruta), _fecha_de_nombre(a)
                m = re.search(r"folio[\s_-]*(\d+)", a, re.I)
                folio = m.group(1) if m else ""
                if (not rbd or not fecha) and conf().get("leer_pdf", True):
                    try:                                          # el PDF de Datácora trae RBD, fecha y folio adentro
                        import bitacoras
                        cab = bitacoras.leer_pdf(ruta)
                        rbd = rbd or (int(cab["rbd"]) if str(cab.get("rbd") or "").isdigit() else None)
                        fecha = fecha or (cab.get("fecha") or None)
                        folio = folio or (cab.get("folio") or "")
                    except Exception:
                        pass
                if not fecha:                                     # último recurso: el día que se descargó
                    fecha = datetime.fromtimestamp(mt).date().isoformat()
                    origen_f = "descarga"
                else:
                    origen_f = "carpeta"
                con.execute("INSERT OR REPLACE INTO verificadores(ruta,mtime,rbd,fecha,folio,origen,nombre) "
                            "VALUES(?,?,?,?,?,?,?)", (ruta, mt, rbd, fecha, str(folio or ""),
                                                      "archivo" if os.sep + "archivo" + os.sep in ruta else origen_f, a))
    for f in con.execute("SELECT ruta FROM verificadores").fetchall():
        if f["ruta"] not in vistos:
            con.execute("DELETE FROM verificadores WHERE ruta=?", (f["ruta"],))
    con.commit()


def de(con, rbd):
    indexar(con)
    filas = con.execute("SELECT * FROM verificadores WHERE rbd=? ORDER BY COALESCE(fecha,'') DESC", (rbd,)).fetchall()
    out, vistos = [], set()
    for f in filas:                       # la misma bitácora en dos carpetas cuenta una vez
        k = (f["fecha"], f["folio"]) if f["folio"] else (f["fecha"], f["nombre"])
        if k in vistos:
            continue
        vistos.add(k)
        out.append(dict(f))
    return out


def _fecha_cl(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d-%m-%Y")
    except (TypeError, ValueError):
        return "sin fecha"


def _etiqueta(f):
    return _fecha_cl(f["fecha"]) + (f" (folio {f['folio']})" if f.get("folio") else "") + \
        (" (fecha de descarga)" if f.get("origen") == "descarga" else "")


def _archivo(f, rbd):
    from conversacion import nom
    return {"ruta": f["ruta"], "nombre": f"Bitacora {nom(rbd)} {_fecha_cl(f['fecha'])}.pdf"}


def _fotos(f, rbd):
    """Si junto al PDF hay un zip de fotos de ese folio (8678_307_Fotos.zip), se manda también."""
    if not f.get("folio") or not conf().get("mandar_fotos", True):
        return []
    carpeta = os.path.dirname(f["ruta"])
    out = []
    for a in os.listdir(carpeta):
        if a.lower().endswith(".zip") and re.match(rf"^{rbd}[_\s-]+{f['folio']}(?!\d)", a):
            out.append({"ruta": os.path.join(carpeta, a), "nombre": a})
    return out


# ---------------------------------------------------------------- conversación
def _salida(con, hid, texto, out, resumen, autor):
    from conversacion import _anotar_msg, _hilo
    out["grupo"].append(texto)
    if hid:
        _anotar_msg(con, _hilo(con, hid), texto)
    if cfg().get("conversacion", {}).get("copiar_encargado", True):
        out["admin"].append(f"Verificador ({autor}): {resumen}.")
    con.commit()
    return out


def _rbd_del_texto(texto):
    hits = en_texto(texto)
    if hits:
        return hits[0], []
    limpio = re.sub(PIDE_RX + "|" + VERBO_RX + r"|\b(el|la|del|de|los|las|un|una|me|por favor|porfa|bitacoras?)\b",
                    " ", norm(texto))
    top = buscar(limpio) if limpio.strip() else []
    if top and top[0][0] >= 82 and (len(top) == 1 or top[0][0] - top[1][0] >= 5):
        return top[0][1], []
    return None, [x for p, x in top if p >= 60][:3]


def pedir(con, texto, autor, origen="grupo"):
    """Primer mensaje: 'necesito el verificador del X'. Devuelve la salida para bot.mjs."""
    from conversacion import nom
    out = {"grupo": [], "admin": [], "archivos_grupo": [], "archivos_admin": [], "intencion": "verificador"}
    n = (autor or "").split()[0]
    rbd, cands = _rbd_del_texto(texto)
    if not rbd:
        if origen != "grupo":
            out["admin"].append("¿De qué colegio? Ej: *verificador del Nemesio Antúnez*")
            return out
        hid = con.execute("INSERT INTO hilos(autor,texto,cands,paso,intencion,motor) VALUES(?,?,?,?,?,?)",
                          (autor, texto, json.dumps(cands), "verif_lugar", "verificador", "regla")).lastrowid
        pregunta = (f"{n}, ¿de qué colegio necesitas el verificador?" +
                    (f" ¿Del {nom(cands[0])}?" if len(cands) == 1 else
                     (" ¿Del " + ", del ".join(nom(r) for r in cands[:-1]) + f" o del {nom(cands[-1])}?" if cands else "")))
        return _salida(con, hid, pregunta, out, "le pregunté de qué colegio", autor)
    return _ofrecer(con, rbd, texto, autor, origen, out)


def _ofrecer(con, rbd, texto, autor, origen, out, hid=None):
    from conversacion import nom
    n = (autor or "").split()[0]
    lista = de(con, rbd)
    # si pidió una fecha ("el del 30/09", "el de septiembre"), se filtra
    from consultas import rango_tiempo
    desde, hasta, _ = rango_tiempo(texto)
    if desde:
        en_rango = [f for f in lista if f["fecha"] and desde.isoformat() <= f["fecha"] <= hasta.isoformat()]
        lista = en_rango or lista
    lista = lista[:int(conf().get("max_lista", 10))]
    clave_arch = "archivos_grupo" if origen == "grupo" else "archivos_admin"
    clave_txt = "grupo" if origen == "grupo" else "admin"
    if not lista:
        msg = (f"{n}, del {nom(rbd)} no tengo bitácoras guardadas todavía. Le aviso a Manuel para que la suba.")
        out[clave_txt].append(msg)
        if origen == "grupo":
            out["admin"].append(f"Piden verificador del {nom(rbd)} (RBD {rbd}) y no tengo PDF. Guárdalo en la carpeta "
                                f"datacora del teléfono o mándamelo por acá con «Nombre, dd/mm/aaaa».")
        if hid:
            con.execute("UPDATE hilos SET estado='cerrado', resultado='sin PDF' WHERE id=?", (hid,))
        con.commit()
        return out
    if len(lista) == 1:
        f = lista[0]
        cuando = f" del {_etiqueta(f)}" if f.get("fecha") else (f" (folio {f['folio']})" if f.get("folio") else "")
        out[clave_txt].append(f"{n}, te mando la bitácora del {nom(rbd)}{cuando}.")
        out[clave_arch].append(_archivo(f, rbd))
        out[clave_arch] += _fotos(f, rbd)
        if origen == "grupo":
            out["admin"].append(f"Mandé al grupo el verificador del {nom(rbd)} ({_etiqueta(f)}) que pidió {autor}.")
        if hid:
            con.execute("UPDATE hilos SET estado='cerrado', resultado=? WHERE id=?", (f"envió {f['fecha']}", hid))
        log(con, f"Verificador {rbd} {f['fecha']} enviado a {autor}")
        con.commit()
        return out
    # varias: se pregunta cuál
    m = re.search(r"\b(\d{1,2})\s*$", texto.strip())          # "verificador del nemesio 2" (desde tu privado)
    if m and origen != "grupo" and 1 <= int(m.group(1)) <= len(lista):
        f = lista[int(m.group(1)) - 1]
        out["admin"].append(f"Ahí va la del {_etiqueta(f)}.")
        out["archivos_admin"].append(_archivo(f, rbd))
        out["archivos_admin"] += _fotos(f, rbd)
        return out
    txt = (f"Del {nom(rbd)} tengo estas bitácoras:\n" + "\n".join(f"{i}. {_etiqueta(f)}" for i, f in enumerate(lista, 1))
           + "\n¿Cuál necesitas? Dime el número (o *todas*).")
    if origen != "grupo":
        out["admin"].append(txt + f"\nEscríbeme: *verificador {nom(rbd)} N*")
        return out
    opciones = [{"ruta": f["ruta"], "fecha": f["fecha"], "folio": f.get("folio", ""), "origen": f.get("origen")}
                for f in lista]
    if hid:
        con.execute("UPDATE hilos SET paso='verificador', rbd=?, opciones=? WHERE id=?",
                    (rbd, json.dumps(opciones), hid))
    else:
        hid = con.execute("INSERT INTO hilos(autor,texto,rbd,paso,intencion,motor,opciones) VALUES(?,?,?,?,?,?,?)",
                          (autor, texto, rbd, "verificador", "verificador", "regla", json.dumps(opciones))).lastrowid
    return _salida(con, hid, txt, out, f"le mostré {len(lista)} bitácoras del {nom(rbd)} para que elija", autor)


def continuar(con, h, texto, autor):
    from conversacion import _guardar, nom
    out = {"grupo": [], "admin": [], "archivos_grupo": [], "archivos_admin": []}
    t = norm(texto)
    n = (autor or "").split()[0]
    if h["paso"] == "verif_lugar":
        cands = json.loads(h["cands"] or "[]")
        rbd, _ = _rbd_del_texto(texto)
        if not rbd and cands and re.match(r"^(si|ese|esa|ya|ok|del primero|el primero|1)\b", t):
            rbd = cands[0]
        if not rbd:
            top = buscar(texto)
            rbd = top[0][1] if top and top[0][0] >= 75 else None
        if not rbd:
            _guardar(con, h["id"], estado="vencido", resultado="no se identificó el colegio")
            out["grupo"].append(f"No lo encuentro, {n}. Escríbeme el nombre completo o el RBD y te lo busco.")
            con.commit()
            return out
        _guardar(con, h["id"], rbd=rbd)
        return _ofrecer(con, rbd, h["texto"] + " " + texto, h["autor"], "grupo", out, hid=h["id"])
    # paso verificador: elegir de la lista
    ops = json.loads(h["opciones"] or "[]")
    elegidas = []
    if re.search(r"\b(todas|todos|las dos|ambas|las tres|todo)\b", t):
        elegidas = ops
    elif re.search(r"\b(ultima|ultimo|mas reciente|mas nueva)\b", t):
        elegidas = ops[:1]
    else:
        m = re.search(r"(\d{1,2})[/-](\d{1,2})", texto)
        if m:
            elegidas = [o for o in ops if o["fecha"] and o["fecha"][8:10] == f"{int(m.group(1)):02d}"
                        and o["fecha"][5:7] == f"{int(m.group(2)):02d}"]
        if not elegidas:
            nums = [int(x) for x in re.findall(r"\b(\d{1,2})\b", t)]
            elegidas = [ops[x - 1] for x in nums if 1 <= x <= len(ops)]
            if not elegidas and nums:                         # "la del 30" = el día
                elegidas = [o for o in ops if o["fecha"] and int(o["fecha"][8:10]) in nums]
    if not elegidas:
        if t and len(t.split()) <= 6:
            out["grupo"].append(f"{n}, dime el número de la lista (1 a {len(ops)}) o *todas*.")
        return out if out["grupo"] else None
    for o in elegidas:
        out["archivos_grupo"].append(_archivo(o, h["rbd"]))
        out["archivos_grupo"] += _fotos(o, h["rbd"])
    fechas = ", ".join(_fecha_cl(o["fecha"]) for o in elegidas)
    out["grupo"].append(f"Ahí va{'n' if len(elegidas) > 1 else ''} {'las' if len(elegidas) > 1 else 'la'} del "
                        f"{fechas}." if len(elegidas) <= 3 else f"Ahí van las {len(elegidas)} bitácoras del {nom(h['rbd'])}.")
    out["admin"].append(f"Mandé al grupo {len(elegidas)} verificador(es) del {nom(h['rbd'])} ({fechas}) que pidió {autor}.")
    _guardar(con, h["id"], estado="cerrado", paso="hecho", resultado=f"envió {fechas}")
    log(con, f"Verificadores {h['rbd']} {fechas} enviados a {autor}")
    con.commit()
    return out


def resumen(con):
    indexar(con, forzar=True)
    total = con.execute("SELECT COUNT(*) FROM verificadores").fetchone()[0]
    sin = con.execute("SELECT nombre FROM verificadores WHERE rbd IS NULL OR fecha IS NULL").fetchall()
    cs = carpetas()
    txt = (f"{total} PDF en {len(cs)} carpeta(s): " + ", ".join(cs) if cs else
           "No encuentro la carpeta datacora. En Termux corre una vez: termux-setup-storage (y acepta el permiso).")
    if sin:
        txt += "\nSin colegio o fecha reconocidos (renómbralos «Colegio dd-mm-aaaa.pdf»): " + \
               ", ".join(f["nombre"] for f in sin[:8])
    return txt
