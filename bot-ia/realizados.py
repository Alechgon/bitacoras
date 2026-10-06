"""
realizados.py — lo que se hizo, contado por ti desde tu WhatsApp (privado con el bot).

Escribes como hablas:
  hoy se hicieron silvia salas, teresa prat y el 8661
  rodrigo hizo hoy japón, confederación suiza y lecaros            (en ese orden: 1ra, 2da, 3ra visita)
  camilo hizo: 1 silvia salas 2 república de austria 3 haití        (el número manda)
  el 02/10 rodrigo fue al darío salas (2da) y al japón (1ra)
  ayer: rodrigo japón, suiza. camilo lecaros, silvia salas
  se hicieron todas  ·  rodrigo hizo todas las de hoy
  pásalas   -> lo que quedó sin hacer ese día pasa al día hábil siguiente (una sola vez)
  deshacer hechos -> vuelve atrás el último reporte

Cómo queda en la agenda (y en el cronograma de la planilla y del panel de GitHub):
  - Si esa visita estaba ese día: queda HECHA (con el técnico y el orden que dices).
  - Si estaba para más adelante: se adelanta a ese día y queda hecha (avisa de qué fecha venía).
  - Si estaba atrasada (de un día anterior): queda hecha en el día que dices.
  - Si no estaba en la agenda: se agrega como visita hecha.
  - Orden: si nombras al técnico, el orden en que los dices es el orden del día (1ra, 2da…); un número o
    "(2da)" junto al colegio manda; si no dices técnico ni orden, cada visita conserva su bloque.
  - Lo que el técnico tenía ese día y no nombraste queda pendiente: te lo digo y con "pásalas" se corre.
"""
import json
import re
import threading
from datetime import datetime, timedelta

from nucleo import (a_fecha, bloque_extra, bloques, buscar, cfg, datos, en_texto, es_habil, hoy, log, metas, motivo,
                    n_bloques, nombre_tec, norm, postergar, sig_habil, sumar_habiles)

VERBOS = (r"\b(se hicieron|se hizo|hizo|hicieron|hice|realizo|realizaron|realizada|realizadas|realizado|realizados|"
          r"hecha|hechas|hecho|hechos|fue a|fue al|fueron a|fueron al|visito|visitaron|paso por|pasaron por|atendio|"
          r"atendieron|termino|terminaron|alcanzo a|alcanzaron a|cumplio|cumplieron|ejecuto|ejecutaron|"
          r"se atendieron|se atendio|se visito|se visitaron|listos|listas)\b")
TODAS = r"\b(todas|todos|todo lo de|todas las de|todo lo que tenia|completo|completa)\b"
PASALAS = r"^\s*(pasalas|pasalos|pasa las que faltan|pasa lo que falta|corrrelas|correlas|corre las que faltan|" \
          r"las que faltan pasalas|las demas pasalas|pasalas al siguiente|pasa las pendientes|pasar pendientes)\b"
ORDINALES = {"primera": 1, "primero": 1, "segunda": 2, "segundo": 2, "tercera": 3, "tercero": 3, "cuarta": 4,
             "cuarto": 4, "quinta": 5, "quinto": 5}
DIAS_SEM = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
_ultimo = {}            # último reporte (para "pásalas" y "deshacer hechos")


def conf():
    return cfg().get("realizados", {})


# ---------------------------------------------------------------- ¿es un reporte de lo hecho?
def es_pasalas(texto):
    return bool(re.match(PASALAS, norm(texto)))


def es_deshacer(texto):
    return bool(re.match(r"^\s*deshacer\s+(hechos?|hechas?|realizad\w*|lo ultimo|el reporte|eso)\s*$", norm(texto)))


def es_reporte(texto):
    """True si el mensaje cuenta visitas hechas (con al menos un colegio reconocible o 'todas')."""
    if not conf().get("activa", True):
        return False
    t = norm(texto)
    if not t or "?" in texto or re.match(r"^(caso|casos|regla|que|cuando|como|donde|por que|ok|no)\b", t):
        return False
    if not re.search(VERBOS, t):
        # "camilo: 1 silvia salas 2 teresa prat" (sin verbo): técnico + lista numerada de 2 o más colegios
        # o "ayer: rodrigo japón, suiza. camilo lecaros" (fecha + técnico + 2 o más colegios)
        t2 = re.sub(r"^(hoy|ayer|anteayer|antes de ayer|el (lunes|martes|miercoles|jueves|viernes)( pasado)?|"
                    r"el \d{1,2} \d{1,2}( \d{2,4})?|\d{1,2} \d{1,2}( \d{2,4})?)\s+", "", t)
        m = re.match(r"^(\w+)\b", t2)
        futuro = re.search(r"\b(manana|pasado manana|proxima|proximo|semana que viene)\b", t)
        if futuro or not (m and m.group(1) in _tec_rx() and len(_ubicar(t2)) >= 2):
            return False
    return bool(re.search(TODAS, t) or en_texto(texto) or _algun_colegio(t))


def _algun_colegio(t):
    for trozo in re.split(r",|;|\by\b|\n", t):
        trozo = _sin_ruido(trozo)
        if len(trozo) >= 4:
            top = buscar(trozo)
            if top and top[0][0] >= 85:
                return True
    return False


# ---------------------------------------------------------------- fecha
def fecha_reporte(texto, base=None):
    """Día del que hablas (pasado): hoy, ayer, anteayer, el lunes, el 02/10, 2-10-2026. Por defecto hoy."""
    base = base or hoy()
    t = norm(texto)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", str(texto))
    if m:
        dd, mm, aa = int(m.group(1)), int(m.group(2)), m.group(3)
        a = (int(aa) + (2000 if len(aa) == 2 else 0)) if aa else base.year
        try:
            from datetime import date
            f = date(a, mm, dd)
            if not aa and f > base + timedelta(days=30):
                f = date(a - 1, mm, dd)
            return f
        except ValueError:
            pass
    if re.search(r"\b(anteayer|antes de ayer)\b", t):
        return base - timedelta(days=2)
    if re.search(r"\bayer\b", t):
        f = base - timedelta(days=1)
        return f if es_habil(f) or not conf().get("ayer_habil", True) else _habil_anterior(f)
    m = re.search(r"\b(el )?(lunes|martes|miercoles|jueves|viernes|sabado|domingo)( pasado)?\b", t)
    if m:
        atras = (base.weekday() - DIAS_SEM[m.group(2)]) % 7
        return base - timedelta(days=atras)            # "el lunes" dicho un lunes = hoy
    return base


def _habil_anterior(d):
    while not es_habil(d):
        d -= timedelta(days=1)
    return d


# ---------------------------------------------------------------- entender la lista
RUIDO = (r"\b(hoy|ayer|anteayer|antes de ayer|el|la|los|las|al|a|del|de la|en el|en la|en|y|e|tambien|ademas|"
         r"despues|luego|primero|finalmente|se hicieron|se hizo|hizo|hicieron|hice|realizo|realizaron|realizadas?|"
         r"realizados?|hechas?|hechos?|fue|fueron|visito|visitaron|paso por|pasaron por|atendio|atendieron|"
         r"termino|terminaron|alcanzo|alcanzaron|cumplio|cumplieron|ejecuto|ejecutaron|se atendieron|se atendio|"
         r"se visito|se visitaron|listos|listas|visitas?|colegios?|establecimientos?|jardines|jardin|escuela|liceo|"
         r"lunes|martes|miercoles|jueves|viernes|pasado|en ese orden|en orden|por orden|ese orden|orden|"
         r"preventivas?|correctivas?|con|por|para|que|lo|le|les|su|sus|tenia|tenian|bien|ok|nomas|no mas|"
         r"todas|todos|todo|de|las de|cada una|completas?)\b")


def _sin_ruido(s):
    s = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", " ", s)
    s = re.sub(RUIDO, " ", norm(s))
    return re.sub(r"\s+", " ", s).strip()


def _tec_rx():
    alias = {}
    for clave, info in datos()["META"]["tecnicos"].items():
        for n in {norm(clave), norm(info.get("nombre", "")).split()[0]}:
            if n:
                alias[n] = clave
                if len(n) > 4:
                    alias[n[:4]] = clave
    return alias


def _ubicar(t):
    """Colegios nombrados en un texto normalizado, con su posición: [(inicio, fin, rbd)] sin solaparse."""
    D = datos()
    hits = []
    for m in re.finditer(r"\b\d{4,6}\b", t):
        if int(m.group()) in D["E"]:
            hits.append((m.start(), m.end(), int(m.group())))
    nombres = {}
    for k, r in D["ALIAS"].items():
        if len(k) > 3:
            nombres[norm(k)] = r
    for e in D["ESTAB"]:
        nombres.setdefault(norm(e["nombre"]), e["rbd"])
    for k in sorted(nombres, key=len, reverse=True):
        for m in re.finditer(rf"\b{re.escape(k)}\b", t):
            if not any(a < m.end() and m.start() < b for a, b, _ in hits):
                hits.append((m.start(), m.end(), nombres[k]))
    return sorted(hits)


def _orden_en(trozo_antes, trozo_despues):
    """Número de visita escrito junto al colegio: '2 silvia salas', '2da: …', '… (2da)', '… b2', 'segunda visita …'."""
    m = re.search(r"(?:^|\s)([1-8])\s*(?:ra|da|ta|er|era|a|o)?\s*(?:visita)?\s*$", trozo_antes)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(primera|primero|segunda|segundo|tercera|tercero|cuarta|cuarto|quinta|quinto)\s*(?:visita)?\s*$",
                  trozo_antes)
    if m:
        return ORDINALES[m.group(1)]
    m = re.match(r"^\s*(?:b|bloque|en la|como)?\s*([1-8])\s*(?:ra|da|ta|er|era)\s*(?:visita)?\b", trozo_despues) or \
        re.match(r"^\s*(?:b|bloque)\s*([1-8])\b", trozo_despues)
    if m:
        return int(m.group(1))
    return None


def interpretar(texto, base=None):
    """
    -> {fecha, grupos: [{tec, todas, items: [{rbd, orden}], ordenado}], no_reconocidos: [..], todas_sin_tec}
    """
    fecha = fecha_reporte(texto, base)
    t = norm(texto)
    alias = _tec_rx()
    marcas = []                                    # dónde empieza lo de cada técnico
    for m in re.finditer(r"\b(\w+)\b", t):
        if m.group(1) in alias:
            marcas.append((m.start(), m.end(), alias[m.group(1)]))
    segmentos = []
    if not marcas:
        segmentos.append((None, t))
    else:
        if marcas[0][0] > 0:
            segmentos.append((None, t[:marcas[0][0]]))
        for i, (a, b, tec) in enumerate(marcas):
            fin = marcas[i + 1][0] if i + 1 < len(marcas) else len(t)
            segmentos.append((tec, t[b:fin]))
    grupos, no_rec, vistos = [], [], set()
    explicito_orden = bool(re.search(r"\b(en ese orden|en orden|por orden)\b", t))
    for tec, seg in segmentos:
        hits = _ubicar(seg)
        items = []
        cursor = 0
        for a, b, rbd in hits:
            antes = seg[cursor:a]
            for trozo in re.split(r",|;|\by\b|\be\b", antes):     # nombres que no calzaron exacto: búsqueda difusa
                r = _difuso(trozo)
                if r and r not in vistos:
                    vistos.add(r)
                    items.append({"rbd": r, "orden": _orden_en(trozo, "")})
                elif _sin_ruido(trozo) and len(_sin_ruido(trozo)) > 3 and not r and not re.fullmatch(r"[\d\s]+", _sin_ruido(trozo)):
                    no_rec.append(_sin_ruido(trozo))
            if rbd not in vistos:
                vistos.add(rbd)
                items.append({"rbd": rbd, "orden": _orden_en(seg[max(0, a - 18):a], seg[b:b + 18])})
            cursor = b
        for trozo in re.split(r",|;|\by\b|\be\b", seg[cursor:]):
            r = _difuso(trozo)
            if r and r not in vistos:
                vistos.add(r)
                items.append({"rbd": r, "orden": _orden_en(trozo, "")})
            elif _sin_ruido(trozo) and len(_sin_ruido(trozo)) > 3 and not r and \
                    not re.fullmatch(r"[\d\s]+|(b|bloque)?\s*\d(ra|da|ta)?( visita)?", _sin_ruido(trozo)):
                no_rec.append(_sin_ruido(trozo))
        todas = bool(re.search(TODAS, seg))
        if items or todas:
            grupos.append({"tec": tec, "todas": todas and not items, "items": items,
                           "ordenado": bool(tec) and (explicito_orden or conf().get("orden_lista", "numero") == "siempre")})
        elif tec is None and not items:
            continue
    return {"fecha": fecha, "grupos": grupos, "no_reconocidos": [x for x in no_rec if not _es_tec_o_ruido(x)]}


def _es_tec_o_ruido(x):
    return x in _tec_rx() or len(x) <= 3


def _difuso(trozo):
    q = _sin_ruido(re.sub(r"\(.*?\)", " ", trozo))
    q = re.sub(r"\b([1-8])\s*(ra|da|ta|er|era)?\b|\bb\s*\d\b|\bbloque\s*\d\b", " ", q).strip()
    if len(q) < 4 or q in _tec_rx():
        return None
    top = buscar(q)
    if top and top[0][0] >= int(conf().get("parecido_min", 80)) and (len(top) == 1 or top[0][0] - top[1][0] >= 4):
        return top[0][1]
    return None


# ---------------------------------------------------------------- marcar una visita
def _tec_por_defecto(con, rbd, d):
    """Si no dices quién: el que la tenía en agenda; si no, el que andaba más cerca ese día; si no, el preferido."""
    t = con.execute("SELECT tec FROM tarjetas WHERE rbd=? AND estado IN ('programada','realizada') "
                    "ORDER BY ABS(julianday(fecha)-julianday(?)) LIMIT 1", (rbd, d.isoformat())).fetchone()
    if t:
        return t["tec"], "tenía la visita"
    import en_vivo
    mejor, km_min = None, 999
    for tec in datos()["META"]["tecnicos"]:
        for r in con.execute("SELECT rbd FROM tarjetas WHERE tec=? AND fecha=? AND estado IN ('programada','realizada')",
                             (tec, d.isoformat())):
            k = en_vivo.km(r["rbd"], rbd)
            if k is not None and k < km_min:
                mejor, km_min = tec, k
    if mejor:
        return mejor, "andaba cerca"
    return list(datos()["META"]["tecnicos"])[0], "por defecto"


def marcar(con, rbd, d, tec=None, bloque=None, fuente="reporte", bloque_fijo=False, clase=None):
    """
    Deja HECHA la visita a ese colegio ese día. Devuelve dict(accion, id, rbd, tec, bloque, de_fecha, nota).
    accion: hecha | adelantada | atrasada | nueva | ya_estaba
    """
    d = a_fecha(d)
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    E = datos()["E"]
    t = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND fecha=? AND estado='programada' "
                    "ORDER BY (tec=?) DESC, bloque LIMIT 1", (rbd, d.isoformat(), tec or "")).fetchone()
    accion, de_fecha = "hecha", None
    if not t:
        t = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND fecha=? AND estado='realizada' LIMIT 1",
                        (rbd, d.isoformat())).fetchone()
        if t:
            accion = "ya_estaba"
    if not t:
        ventana = (d + timedelta(days=int(conf().get("adelantar_hasta_dias", 60)))).isoformat()
        t = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' AND fecha>? AND fecha<=? "
                        "ORDER BY fecha LIMIT 1", (rbd, d.isoformat(), ventana)).fetchone()
        if t:
            accion, de_fecha = "adelantada", t["fecha"]
    if not t:
        t = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' AND fecha<? "
                        "ORDER BY fecha DESC LIMIT 1", (rbd, d.isoformat())).fetchone()
        if t:
            accion, de_fecha = "atrasada", t["fecha"]
    tec_nota = ""
    if not tec:
        if t:
            tec = t["tec"]
        else:
            tec, tec_nota = _tec_por_defecto(con, rbd, d)
    if t:
        if bloque is None:
            bloque = t["bloque"] if (t["fecha"] == d.isoformat() and t["tec"] == tec) else _libre(con, tec, d)
        else:
            _desocupar(con, tec, d, bloque, t)
        con.execute("UPDATE tarjetas SET estado='realizada', fecha=?, tec=?, bloque=?, modificada=1, hecho=?, "
                    "hecho_por=? WHERE id=?", (d.isoformat(), tec, bloque, ahora, fuente, t["id"]))
        tid = t["id"]
        if t["hallazgo_id"]:
            con.execute("UPDATE hallazgos SET estado='resuelto' WHERE id=? AND estado='agendado'", (t["hallazgo_id"],))
        con.execute("UPDATE hallazgos SET estado='resuelto' WHERE tarjeta_id=? AND estado='agendado'", (tid,))
    else:
        accion = "nueva"
        if bloque is None:
            bloque = _libre(con, tec, d)
        else:
            _desocupar(con, tec, d, bloque, None)
        e = E.get(rbd, {})
        clase = clase or ("VISITA" if e.get("inst") == "Junaeb" else "PREVENTIVA")
        from nucleo import _nuevo_id
        tid = _nuevo_id(con)
        while con.execute("SELECT 1 FROM tarjetas WHERE id=?", (tid,)).fetchone():
            tid = tid[:-3] + f"{int(tid[-3:]) + 1:03d}"
        con.execute("INSERT INTO tarjetas(id,fecha,tec,bloque,rbd,clase,detalle,pts,crit,estado,aplaz,origen,limite,"
                    "modificada,hecho,hecho_por) VALUES(?,?,?,?,?,?,?,?,?,'realizada',0,'bot',?,1,?,?)",
                    (tid, d.isoformat(), tec, bloque, rbd, clase, f"Visita hecha (informada: {fuente})",
                     e.get("pts", 0), "", d.isoformat(), ahora, fuente))
    log(con, f"Realizada {E.get(rbd, {}).get('nombre', rbd)} {d} {tec} b{bloque} [{accion}] ({fuente})")
    return {"accion": accion, "id": tid, "rbd": rbd, "tec": tec, "bloque": bloque, "de_fecha": de_fecha,
            "nota": tec_nota}


def _desocupar(con, tec, d, bloque, t):
    """Si otra visita ocupa ese bloque, se va al bloque que deja libre la hecha (o al primer libre del día)."""
    otra = con.execute("SELECT * FROM tarjetas WHERE tec=? AND fecha=? AND bloque=? AND estado IN ('programada','realizada') "
                       "AND id<>?", (tec, d.isoformat(), bloque, t["id"] if t else "")).fetchone()
    if not otra:
        return
    destino = t["bloque"] if (t and t["fecha"] == d.isoformat() and t["tec"] == tec) else None
    con.execute("UPDATE tarjetas SET bloque=99 WHERE id=?", (otra["id"],))
    con.execute("UPDATE tarjetas SET bloque=?, modificada=1 WHERE id=?", (destino or _libre(con, tec, d), otra["id"]))


def _libre(con, tec, d):
    usados = {r[0] for r in con.execute("SELECT bloque FROM tarjetas WHERE tec=? AND fecha=? AND estado IN "
                                        "('programada','realizada')", (tec, d.isoformat()))}
    for b in range(1, 12):
        if b not in usados:
            return b
    return bloque_extra(d)


def _reordenar_dia(con, tec, d, secuencia, fijos=None):
    """
    Ordena el día del técnico: las que dijiste con número van en ese número; las hechas que nombraste sin número,
    en el orden en que las dijiste; después las otras hechas y al final lo que quedaba pendiente.
    """
    fijos = dict(fijos or {})
    todas = con.execute("SELECT id, estado FROM tarjetas WHERE tec=? AND fecha=? AND estado IN ('programada','realizada') "
                        "ORDER BY bloque", (tec, d.isoformat())).fetchall()
    resto = [x for x in secuencia if x not in fijos]
    resto += [r["id"] for r in todas if r["estado"] == "realizada" and r["id"] not in fijos and r["id"] not in resto]
    resto += [r["id"] for r in todas if r["estado"] == "programada" and r["id"] not in fijos and r["id"] not in resto]
    final, usados, b = {}, set(fijos.values()), 1
    final.update(fijos)
    for tid in resto:
        while b in usados:
            b += 1
        final[tid] = b
        usados.add(b)
    for tid in final:
        con.execute("UPDATE tarjetas SET bloque=99 WHERE id=?", (tid,))      # 99 = en tránsito (no ensucia el historial)
    for tid, bl in final.items():
        con.execute("UPDATE tarjetas SET bloque=?, modificada=1 WHERE id=?", (bl, tid))


def _foto(con, ids_o_condicion=None):
    cols = "id, fecha, tec, bloque, estado, aplaz, modificada, hecho, hecho_por"
    return {r["id"]: dict(r) for r in con.execute(f"SELECT {cols} FROM tarjetas")}


# ---------------------------------------------------------------- aplicar un reporte
def aplicar(con, texto, autor="Manuel", base=None):
    """Procesa el mensaje completo. Devuelve el texto para ti."""
    import voz
    rep = interpretar(texto, base)
    d = rep["fecha"]
    if not rep["grupos"]:
        return ("no reconocí colegios en eso. escríbelo así: «rodrigo hizo hoy japón, suiza y lecaros» o "
                "«hoy se hicieron silvia salas y teresa prat».")
    if d > hoy():
        return f"el {d.strftime('%d-%m')} todavía no llega; para programar usa el plan o escríbeme el caso."
    antes = _foto(con)
    m0 = metas(con)
    motivo(con, f"Visitas realizadas informadas por {autor} ({d.strftime('%d-%m')})")
    resultado = []                                   # (tec, [res...])
    for g in rep["grupos"]:
        res_g = []
        if g["todas"]:
            filtro = "AND tec=?" if g["tec"] else ""
            for t in con.execute(f"SELECT * FROM tarjetas WHERE fecha=? AND estado='programada' {filtro} ORDER BY tec, bloque",
                                 (d.isoformat(), *([g["tec"]] if g["tec"] else []))).fetchall():
                res_g.append(marcar(con, t["rbd"], d, t["tec"], t["bloque"], fuente=f"reporte de {autor}"))
            resultado.append((g["tec"], res_g, False))
            continue
        con_orden = [it for it in g["items"] if it["orden"]]
        # el orden del día solo lo fijan los números (o decir "en ese orden"); si no, cada visita queda en su bloque
        todos_num = bool(g["tec"]) and con_orden and len(con_orden) == len(g["items"])
        reordenar = g["tec"] and (g["ordenado"] or todos_num)
        for it in g["items"]:
            bl = it["orden"] if (it["orden"] and not reordenar) else None    # número explícito → ese bloque
            res_g.append(marcar(con, it["rbd"], d, g["tec"], bl, fuente=f"reporte de {autor}"))
        if reordenar:
            fijos = {r["id"]: it["orden"] for it, r in zip(g["items"], res_g) if it["orden"]}
            secuencia = [r["id"] for r in res_g] if g["ordenado"] else []
            _reordenar_dia(con, g["tec"], d, secuencia, fijos)
            for r in res_g:
                r["bloque"] = con.execute("SELECT bloque FROM tarjetas WHERE id=?", (r["id"],)).fetchone()["bloque"]
        resultado.append((g["tec"], res_g, True))
    despues = _foto(con)
    cambios = {k: v for k, v in antes.items() if despues.get(k) != v}
    nuevas = [k for k in despues if k not in antes]
    tecs_dia = {r["tec"] for _, rs, _ in resultado for r in rs}
    _ultimo.update(fecha=d.isoformat(), tecs=sorted(tecs_dia), autor=autor)
    con.execute("INSERT OR REPLACE INTO meta VALUES('deshacer_realizados', ?)",
                (json.dumps({"antes": cambios, "nuevas": nuevas, "fecha": d.isoformat(), "tecs": sorted(tecs_dia)},
                            default=str),))
    con.commit()
    _publicar()
    return _texto(con, d, resultado, rep["no_reconocidos"], m0)


def _texto(con, d, resultado, no_rec, m0):
    import voz
    from conversacion import _dia
    E = datos()["E"]
    lin = [f"listo, quedó anotado {_dia(d)}{'' if _dia(d).startswith('el ') else ' ' + d.strftime('%d-%m')}:"]
    por_tec = {}
    notas = []
    for tec, rs, _ in resultado:
        for r in rs:
            por_tec.setdefault(r["tec"], []).append(r)
    for tec, rs in por_tec.items():
        rs = sorted(rs, key=lambda r: r["bloque"] or 99)
        partes = []
        for r in rs:
            p = f"{_ord(r['bloque'])} {voz.nombre(r['rbd'])}"
            if r["accion"] == "adelantada":
                p += f" (estaba para el {a_fecha(r['de_fecha']).strftime('%d-%m')}, la adelanté)"
            elif r["accion"] == "atrasada":
                p += f" (venía atrasada del {a_fecha(r['de_fecha']).strftime('%d-%m')})"
            elif r["accion"] == "nueva":
                p += " (no estaba en agenda, la sumé)"
            elif r["accion"] == "ya_estaba":
                p += " (ya estaba marcada)"
            if r.get("nota") and r["nota"] != "tenía la visita":
                otro = next((x for x in datos()["META"]["tecnicos"] if x != tec), tec)
                notas.append(f"{voz.nombre(r['rbd'])} lo dejé con {nombre_tec(tec).lower()} ({r['nota']}); si fue "
                             f"{nombre_tec(otro).lower()}, dime «{nombre_tec(otro).lower()} hizo "
                             f"{voz.nombre(r['rbd']).lower()}».")
            partes.append(p)
        lin.append(f"{nombre_tec(tec).lower()}: " + ", ".join(partes))
    lin += notas
    if no_rec:
        lin.append("no reconocí: " + ", ".join(f"«{x}»" for x in no_rec[:5]) + ". dime el nombre completo o el RBD.")
    pend = con.execute("SELECT * FROM tarjetas WHERE fecha=? AND estado='programada' ORDER BY tec, bloque",
                       (d.isoformat(),)).fetchall()
    if pend:
        dest = _destino_pendientes(d)
        lin.append("de ese día siguen pendientes: " + "; ".join(
            f"{nombre_tec(t['tec']).lower()} {_ord(t['bloque'])} {voz.nombre(t['rbd'])}" for t in pend)
            + f". si no se hicieron, dime «pásalas» y las corro {('al ' + _dia(dest)[3:]) if _dia(dest).startswith('el ') else 'a ' + _dia(dest)}.")
    m1 = metas(con)
    j0, j1 = m0["junaeb"][0], m1["junaeb"][0]
    g0, g1 = m0["jardines"][0], m1["jardines"][0]
    if (j1, g1) != (j0, g0):
        lin.append(f"metas: junaeb {j1} de {m1['junaeb'][1]}, jardines con preventiva {g1} de {m1['jardines'][1]}.")
    lin.append("el cronograma se actualiza solo en la planilla y en el panel.")
    return "\n".join(lin)


def _ord(b):
    from nucleo import ORDINAL
    return ORDINAL.get(int(b), f"{b}a") if b else "?"


def _destino_pendientes(d):
    """Lo que no se hizo ese día pasa al día hábil siguiente; si ese día ya pasó, al próximo hábil desde hoy."""
    nd = sumar_habiles(d, 1)
    if nd < hoy():
        nd = sig_habil(hoy())
    return nd


def pasalas(con, autor="Manuel", d=None, tecs=None):
    """Corre UN día hábil lo que quedó pendiente del día del último reporte (o de hoy)."""
    import voz
    from conversacion import _dia
    d = a_fecha(d or _ultimo.get("fecha")) or hoy()
    tecs = tecs if tecs is not None else (_ultimo.get("tecs") if _ultimo.get("fecha") == d.isoformat() else None)
    q = "SELECT * FROM tarjetas WHERE fecha=? AND estado='programada'"
    p = [d.isoformat()]
    if tecs:
        q += f" AND tec IN ({','.join('?' * len(tecs))})"
        p += list(tecs)
    pend = con.execute(q + " ORDER BY tec, bloque", p).fetchall()
    if not pend:
        return f"no queda nada pendiente {_dia(d)}."
    motivo(con, f"No alcanzadas el {d.strftime('%d-%m')} (avisó {autor}): pasan al día hábil siguiente")
    dest = _destino_pendientes(d)
    movidas = []
    for t in pend:
        r = postergar(con, dict(t), dest, destino=dest)
        if r:
            movidas.append(r)
    con.commit()
    _publicar()
    return ("listo, pasan " + (f"al {_dia(dest)[3:]}" if _dia(dest).startswith("el ") else f"a {_dia(dest)}") + ": "
            + "; ".join(f"{voz.nombre(m['rbd'])} ({nombre_tec(m['tec']).lower()}, {_ord(m['bloque'])}"
                        + (", va como extra" if m.get("extra") else "") + ")" for m in movidas) + ".")


def deshacer(con, autor="Manuel"):
    fila = con.execute("SELECT v FROM meta WHERE k='deshacer_realizados'").fetchone()
    if not fila:
        return "no tengo un reporte de hechos para deshacer."
    d = json.loads(fila["v"])
    motivo(con, f"Deshecho por {autor} (reporte de hechos del {d['fecha']})")
    for tid, v in d["antes"].items():
        con.execute("UPDATE tarjetas SET fecha=?, tec=?, bloque=?, estado=?, aplaz=?, modificada=?, hecho=?, "
                    "hecho_por=? WHERE id=?", (v["fecha"], v["tec"], v["bloque"], v["estado"], v["aplaz"],
                                               v["modificada"], v["hecho"], v["hecho_por"], tid))
    for tid in d["nuevas"]:
        con.execute("DELETE FROM tarjetas WHERE id=? AND origen='bot'", (tid,))
    con.execute("DELETE FROM meta WHERE k='deshacer_realizados'")
    con.commit()
    _publicar()
    return f"listo, deshice el reporte del {a_fecha(d['fecha']).strftime('%d-%m')}: la agenda quedó como estaba."


# ---------------------------------------------------------------- desde una bitácora
def desde_bitacora(con, rbd, fecha, tecnico_txt=""):
    """Una bitácora reciente de Datácora = esa visita se hizo. Solo marca si calza con algo de la agenda."""
    import lenguaje
    fecha = a_fecha(fecha)
    if not rbd or not fecha or not conf().get("desde_bitacoras", True):
        return None
    inicio = a_fecha(datos()["META"]["inicio"])
    if fecha < max(inicio, hoy() - timedelta(days=int(conf().get("bitacora_max_dias", 10)))) or fecha > hoy():
        return None                                  # bitácoras viejas no tocan la agenda
    ya = con.execute("SELECT 1 FROM tarjetas WHERE rbd=? AND fecha=? AND estado='realizada'",
                     (rbd, fecha.isoformat())).fetchone()
    if ya:
        return None
    t = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' AND fecha BETWEEN ? AND ? "
                    "ORDER BY ABS(julianday(fecha)-julianday(?)) LIMIT 1",
                    (rbd, (fecha - timedelta(days=7)).isoformat(), (fecha + timedelta(days=21)).isoformat(),
                     fecha.isoformat())).fetchone()
    if not t:
        return None
    tec = lenguaje.tec_de(tecnico_txt or "") or t["tec"]
    motivo(con, f"Bitácora de Datácora del {fecha.strftime('%d-%m')}")
    r = marcar(con, rbd, fecha, tec, None, fuente="bitácora Datácora")
    con.commit()
    _publicar()
    return r


# ---------------------------------------------------------------- planilla y panel al tiro
def _publicar():
    """Sube el cronograma a la planilla (el panel de GitHub lo lee de ahí) sin esperar el minuto del tick."""
    def tarea():
        try:
            import planilla
            planilla.sincronizar()
        except Exception as e:
            print("[realizados] planilla:", e)
        try:
            import servidor
            servidor.subir_github()
        except Exception as e:
            print("[realizados] github:", e)
    if conf().get("publicar_al_tiro", True):
        threading.Thread(target=tarea, daemon=True).start()


def texto_hoy(con, d=None):
    """!hechos — lo marcado como hecho hoy (o ese día), por técnico."""
    import voz
    d = a_fecha(d) or hoy()
    filas = con.execute("SELECT * FROM tarjetas WHERE fecha=? AND estado='realizada' ORDER BY tec, bloque",
                        (d.isoformat(),)).fetchall()
    pend = con.execute("SELECT * FROM tarjetas WHERE fecha=? AND estado='programada' ORDER BY tec, bloque",
                       (d.isoformat(),)).fetchall()
    if not filas and not pend:
        return f"el {d.strftime('%d-%m')} no tiene visitas en la agenda."
    lin = [f"{d.strftime('%d-%m')}:"]
    for tec in datos()["META"]["tecnicos"]:
        h = [f"{_ord(t['bloque'])} {voz.nombre(t['rbd'])}" for t in filas if t["tec"] == tec]
        p = [f"{_ord(t['bloque'])} {voz.nombre(t['rbd'])}" for t in pend if t["tec"] == tec]
        if h or p:
            lin.append(f"{nombre_tec(tec).lower()}: hechas {', '.join(h) or 'ninguna todavía'}"
                       + (f" · pendientes {', '.join(p)}" if p else ""))
    return "\n".join(lin)
