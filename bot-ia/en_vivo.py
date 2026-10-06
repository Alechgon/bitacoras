"""
en_vivo.py — dónde anda cada técnico, reportado por ti desde tu WhatsApp (privado con el bot).

  Camilo 1                -> Camilo llegó a su 1ra visita (la que tenía en la agenda)
  Camilo 1                -> (segunda vez) salió de la 1ra visita: queda HECHA en la agenda
  Camilo 2                -> llegó a la 2da (si la 1ra seguía abierta, se cierra sola)
  Camilo 2 silvia salas   -> llegó a la 2da, pero fue al Silvia Salas (la agenda se reordena)
  Camilo 1 a las 8        -> con la hora que tú dices
  Camilo salió / terminó  -> cierra la visita abierta · Camilo llegó -> abre la siguiente

Con eso el bot sabe en qué colegio está cada uno (o, sin reporte, dónde debería estar según la agenda),
en qué comuna, a cuántos km queda una emergencia y cuánto se demora en promedio cada visita.
"""
import math
import re
from datetime import datetime, timedelta

from nucleo import (a_fecha, agenda, bloques, buscar, cfg, datos, en_texto, inicio_bloque, log, motivo, n_bloques,
                    nombre_tec, norm)


def conf():
    return cfg().get("en_vivo", {})


# ---------------------------------------------------------------- entender
def _tecs_rx():
    alias = {}
    for clave, info in datos()["META"]["tecnicos"].items():
        nombres = {norm(clave), norm(info.get("nombre", "")).split()[0]}
        for n in list(nombres):
            if len(n) > 4:
                nombres.add(n[:4])               # "cami", "rodr"
        for n in nombres:
            if n:
                alias[n] = clave
    for k, v in (conf().get("alias") or {}).items():
        alias[norm(k)] = v.upper()
    return alias


ACC_SALIO = r"(salio|salio de|termino|terminó|se fue|se retiro|listo|lista|ya salio|va saliendo|desocupado|libre)"


def es_reporte(texto):
    """'Camilo 1' / 'rodrigo 2 silvia salas' / 'Camilo salió'. Devuelve dict o None (no es un reporte en vivo)."""
    if not conf().get("activa", True):
        return None
    t = norm(texto)
    if not t or len(t.split()) > 10 or "?" in texto:
        return None
    alias = _tecs_rx()
    suave = _suave(texto)                         # sin tildes pero con ":" y "." (para la hora)
    m = re.match(r"^(\w+)\s*[:,.-]?\s*(\d)(?:ra|da|ta|era|er|a|o|°)?(?!\w)\s*(.*)$", suave)
    if m and m.group(1) in alias and 1 <= int(m.group(2)) <= 8:
        resto = m.group(3).strip(" .,;:-")
        if re.match(r"^(hizo|hicieron|se hizo|visitas|colegios)\b", resto) or re.search(r"\b[1-8]\s+[a-z]{3}", resto):
            return None                          # "camilo 3 colegios hizo hoy" / "camilo 1 x 2 y": reporte de lo hecho
        return {"tec": alias[m.group(1)], "bloque": int(m.group(2)), "resto": resto, "accion": "auto"}
    m = re.match(rf"^(\w+)\s+{ACC_SALIO}\b\s*(.*)$", t)
    if m and m.group(1) in alias:
        return {"tec": alias[m.group(1)], "bloque": None, "resto": m.group(3).strip(), "accion": "salida"}
    m = re.match(r"^(\w+)\s+(llego|ya llego|entro|esta en)\b\s*(.*)$", t)
    if m and m.group(1) in alias:
        return {"tec": alias[m.group(1)], "bloque": None, "resto": m.group(3).strip(), "accion": "llegada"}
    return None


def _suave(texto):
    import unicodedata
    s = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _hora_dicha(resto, ahora):
    """'a las 8', '8:05', '08.30 hrs' dentro del reporte -> datetime de hoy; si no, None."""
    m = re.search(r"\ba las (\d{1,2})(?:[:.h ](\d{2}))?\b|\b(\d{1,2})[:.h](\d{2})\b", resto)
    if not m:
        return None, resto
    h = int(m.group(1) or m.group(3))
    mi = int(m.group(2) or m.group(4) or 0)
    if h < 7:
        h += 12                                  # "a las 3" = 15:00
    if h > 23 or mi > 59:
        return None, resto
    return ahora.replace(hour=h, minute=mi, second=0, microsecond=0), (resto[:m.start()] + resto[m.end():]).strip()


def _rbd_de(resto):
    if not resto:
        return None
    resto = re.sub(r"\b(am|pm|hrs?|horas|en el|en la|al|a la|del|de la|llego|salio)\b", " ", resto).strip()
    if not resto:
        return None
    hits = en_texto(resto)
    if hits:
        return hits[0]
    top = buscar(resto)
    if top and top[0][0] >= 80 and (len(top) == 1 or top[0][0] - top[1][0] >= 5):
        return top[0][1]
    return None


# ---------------------------------------------------------------- registrar
def _tarjeta(con, tec, d, bloque):
    return con.execute("SELECT * FROM tarjetas WHERE tec=? AND fecha=? AND bloque=? AND estado IN "
                       "('programada','realizada') ORDER BY estado='programada' DESC LIMIT 1",
                       (tec, d.isoformat(), bloque)).fetchone()


def _abierta(con, tec, d):
    return con.execute("SELECT * FROM en_vivo WHERE tec=? AND fecha=? AND llegada IS NOT NULL AND salida IS NULL "
                       "ORDER BY bloque DESC LIMIT 1", (tec, d.isoformat())).fetchone()


def _cerrar(con, fila, cuando, autor):
    con.execute("UPDATE en_vivo SET salida=? WHERE id=?", (cuando.strftime("%Y-%m-%d %H:%M:%S"), fila["id"]))
    if fila["rbd"]:
        import realizados
        realizados.marcar(con, fila["rbd"], a_fecha(fila["fecha"]), fila["tec"], fila["bloque"],
                          fuente=f"en vivo ({autor})", bloque_fijo=True)


def _dur(fila, salida=None):
    try:
        a = datetime.strptime(fila["llegada"], "%Y-%m-%d %H:%M:%S")
        b = salida or datetime.strptime(fila["salida"], "%Y-%m-%d %H:%M:%S")
        return int((b - a).total_seconds() // 60)
    except (TypeError, ValueError):
        return None


def _min(m):
    if m is None:
        return ""
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min" if m % 60 else f"{m // 60} h"


def registrar(con, rep, autor="Manuel", ahora=None):
    """Aplica un reporte en vivo. Devuelve el texto de confirmación para ti."""
    import voz
    ahora = ahora or datetime.now()
    cuando, resto = _hora_dicha(rep.get("resto", ""), ahora)
    cuando = cuando or ahora
    d = ahora.date()
    tec = rep["tec"]
    quien = nombre_tec(tec)
    abierta = _abierta(con, tec, d)
    motivo(con, f"Reporte en vivo de {autor}: {quien} {rep.get('bloque') or rep['accion']}")

    if rep["accion"] == "salida" or (rep["accion"] == "auto" and abierta and abierta["bloque"] == rep["bloque"]):
        if not abierta:
            return f"no tenía ninguna visita abierta de {quien.lower()} hoy. si llegó a alguna, mándame «{quien} N»."
        _cerrar(con, abierta, cuando, autor)
        con.commit()
        dur = _dur(abierta, cuando)
        sig = _siguiente(con, tec, d, abierta["bloque"])
        txt = (f"anotado, {quien.lower()} salió {voz.del_(abierta['rbd']) if abierta['rbd'] else 'de la visita'} "
               f"({_ord(abierta['bloque'])} visita" + (f", {_min(dur)}" if dur is not None else "") + "). quedó hecha.")
        if sig:
            txt += f" sigue con {voz.nombre(sig['rbd'])} ({_ord(sig['bloque'])})."
        else:
            txt += " no le queda nada más hoy en la agenda."
        return txt

    # llegada
    bloque = rep.get("bloque")
    if rep["accion"] == "llegada" or not bloque:
        ult = con.execute("SELECT MAX(bloque) FROM en_vivo WHERE tec=? AND fecha=?", (tec, d.isoformat())).fetchone()[0]
        bloque = (ult or 0) + 1
    ya = con.execute("SELECT * FROM en_vivo WHERE tec=? AND fecha=? AND bloque=?", (tec, d.isoformat(), bloque)).fetchone()
    if ya and ya["salida"]:
        return (f"la {_ord(bloque)} de {quien.lower()} ya la tenía cerrada (llegó {ya['llegada'][11:16]}, salió "
                f"{ya['salida'][11:16]}). si es otra, mándame «{quien} {bloque + 1}».")
    cerrada_txt = ""
    if abierta and abierta["bloque"] != bloque:      # se le olvidó avisar la salida de la anterior
        _cerrar(con, abierta, cuando, autor)
        cerrada_txt = f" cerré la {_ord(abierta['bloque'])} ({voz.nombre(abierta['rbd']) if abierta['rbd'] else 'sin colegio'})."
    rbd_dicho = _rbd_de(resto)
    t = _tarjeta(con, tec, d, bloque)
    rbd = rbd_dicho or (t["rbd"] if t else None)
    cambio = ""
    if rbd_dicho and t and t["rbd"] != rbd_dicho:
        cambio = _reordenar(con, tec, d, bloque, rbd_dicho, t)
    tarjeta_id = None
    t2 = con.execute("SELECT id FROM tarjetas WHERE tec=? AND fecha=? AND rbd=? AND estado IN ('programada','realizada')",
                     (tec, d.isoformat(), rbd)).fetchone() if rbd else None
    if t2:
        tarjeta_id = t2["id"]
    if ya:
        con.execute("UPDATE en_vivo SET llegada=?, rbd=?, tarjeta_id=? WHERE id=?",
                    (cuando.strftime("%Y-%m-%d %H:%M:%S"), rbd, tarjeta_id, ya["id"]))
    else:
        con.execute("INSERT INTO en_vivo(fecha,tec,bloque,rbd,tarjeta_id,llegada,nota) VALUES(?,?,?,?,?,?,?)",
                    (d.isoformat(), tec, bloque, rbd, tarjeta_id, cuando.strftime("%Y-%m-%d %H:%M:%S"),
                     f"reportado por {autor}"))
    log(con, f"En vivo: {quien} llegó a la {_ord(bloque)} ({rbd}) {cuando:%H:%M}")
    con.commit()
    if not rbd:
        return (f"anotado, {quien.lower()} en su {_ord(bloque)} visita ({cuando:%H:%M}), pero no tengo colegio para "
                f"ese bloque. dime cuál: «{quien} {bloque} nombre del colegio».{cerrada_txt}")
    return (f"anotado, {quien.lower()} llegó {voz.al(rbd)} ({_ord(bloque)} visita, {cuando:%H:%M})."
            + cambio + cerrada_txt + f" cuando salga, mándame «{quien} {bloque}» de nuevo.")


def _ord(b):
    from nucleo import ORDINAL
    return ORDINAL.get(int(b), f"{b}a")


def _siguiente(con, tec, d, bloque):
    return con.execute("SELECT * FROM tarjetas WHERE tec=? AND fecha=? AND bloque>? AND estado='programada' "
                       "ORDER BY bloque LIMIT 1", (tec, d.isoformat(), bloque)).fetchone()


def _reordenar(con, tec, d, bloque, rbd, t_plan):
    """Fue a otro colegio en ese bloque: si ese colegio estaba más tarde hoy, se intercambian; si no, se agrega."""
    import voz
    otra = con.execute("SELECT * FROM tarjetas WHERE tec=? AND fecha=? AND rbd=? AND estado='programada'",
                       (tec, d.isoformat(), rbd)).fetchone()
    if otra:
        con.execute("UPDATE tarjetas SET bloque=99 WHERE id=?", (t_plan["id"],))
        con.execute("UPDATE tarjetas SET bloque=?, modificada=1 WHERE id=?", (bloque, otra["id"]))
        con.execute("UPDATE tarjetas SET bloque=?, modificada=1 WHERE id=?", (otra["bloque"], t_plan["id"]))
        return f" ojo, en ese bloque tenía {voz.el(t_plan['rbd'])}; lo cambié a la {_ord(otra['bloque'])}."
    otro_tec = con.execute("SELECT * FROM tarjetas WHERE fecha=? AND rbd=? AND estado='programada' AND tec<>?",
                           (d.isoformat(), rbd, tec)).fetchone()
    if otro_tec:
        con.execute("UPDATE tarjetas SET tec=?, bloque=?, modificada=1 WHERE id=?", (tec, bloque, otro_tec["id"]))
        libre = sorted(set(bloques(d)) - {r[0] for r in con.execute(
            "SELECT bloque FROM tarjetas WHERE tec=? AND fecha=? AND estado='programada' AND id<>?",
            (tec, d.isoformat(), t_plan["id"]))})
        nb = next((b for b in libre if b > bloque), n_bloques(d) + 1)
        con.execute("UPDATE tarjetas SET bloque=?, modificada=1 WHERE id=?", (nb, t_plan["id"]))
        return (f" {voz.el(rbd)} lo tenía {nombre_tec(otro_tec['tec']).lower()}; se lo pasé a {nombre_tec(tec).lower()}. "
                f"{voz.el(t_plan['rbd'])} quedó en su {_ord(nb)}.")
    return f" no estaba en su agenda de hoy; lo anoto igual. {voz.el(t_plan['rbd'])} sigue pendiente."


# ---------------------------------------------------------------- dónde está cada uno
def _latlon(rbd):
    e = datos()["E"].get(rbd) or {}
    return (e.get("lat"), e.get("lon")) if e.get("lat") else (None, None)


def km(a, b):
    """Km aproximados entre dos colegios (línea recta, corregida por calles x1.3)."""
    (la, lo), (lb, lob) = _latlon(a), _latlon(b)
    if la is None or lb is None:
        return None
    return round(math.hypot((la - lb) * 111, (lo - lob) * 92) * 1.3, 1)


def misma_comuna(a, b):
    E = datos()["E"]
    return bool(a and b and norm(E.get(a, {}).get("comuna")) == norm(E.get(b, {}).get("comuna")))


def donde(con, tec, ahora=None):
    """
    {tec, estado, rbd, bloque, desde, siguiente, fuente} — estado: 'en visita' | 'entre visitas' | 'por partir' |
    'terminó' ; fuente: 'en vivo' (lo reportaste) o 'agenda' (estimado por la hora).
    """
    ahora = ahora or datetime.now()
    d = ahora.date()
    filas = con.execute("SELECT * FROM en_vivo WHERE tec=? AND fecha=? ORDER BY bloque", (tec, d.isoformat())).fetchall()
    ag = [t for t in con.execute("SELECT * FROM tarjetas WHERE tec=? AND fecha=? AND estado IN ('programada','realizada') "
                                 "ORDER BY bloque", (tec, d.isoformat())).fetchall()]
    if filas:
        ab = [f for f in filas if f["llegada"] and not f["salida"]]
        if ab:
            f = ab[-1]
            sig = next((t for t in ag if t["bloque"] > f["bloque"] and t["estado"] == "programada"), None)
            return {"tec": tec, "estado": "en visita", "rbd": f["rbd"], "bloque": f["bloque"],
                    "desde": f["llegada"][11:16], "siguiente": dict(sig) if sig else None, "fuente": "en vivo"}
        f = filas[-1]
        sig = next((t for t in ag if t["bloque"] > f["bloque"] and t["estado"] == "programada"), None)
        return {"tec": tec, "estado": "entre visitas" if sig else "terminó", "rbd": f["rbd"], "bloque": f["bloque"],
                "desde": (f["salida"] or "")[11:16], "siguiente": dict(sig) if sig else None, "fuente": "en vivo"}
    if not ag:
        return {"tec": tec, "estado": "sin agenda", "rbd": None, "bloque": 0, "desde": "", "siguiente": None,
                "fuente": "agenda"}
    actual = None
    for t in ag:
        try:
            if inicio_bloque(d, t["bloque"]) <= ahora.time():
                actual = t
        except Exception:
            pass
    if not actual:
        return {"tec": tec, "estado": "por partir", "rbd": ag[0]["rbd"], "bloque": 0, "desde": "",
                "siguiente": dict(ag[0]), "fuente": "agenda"}
    sig = next((t for t in ag if t["bloque"] > actual["bloque"] and t["estado"] == "programada"), None)
    return {"tec": tec, "estado": "en visita", "rbd": actual["rbd"], "bloque": actual["bloque"], "desde": "",
            "siguiente": dict(sig) if sig else None, "fuente": "agenda"}


def equipo(con, ahora=None):
    return [donde(con, t, ahora) for t in datos()["META"]["tecnicos"]]


def mas_cerca(con, rbd, ahora=None, preferido=None):
    """
    ¿Quién está más cerca de ese colegio ahora? Primero el que está en la misma comuna; si los dos lo están (o
    ninguno), el más cerca en km; si empatan, uno y uno (se alterna) o el preferido para ese tipo de falla.
    Devuelve (donde_del_elegido, motivo).
    """
    eq = equipo(con, ahora)
    for x in eq:
        x["km"] = km(x["rbd"], rbd) if x["rbd"] else None
        x["misma"] = misma_comuna(x["rbd"], rbd) if x["rbd"] else False
    misma = [x for x in eq if x["misma"]]
    grupo = misma or eq
    con_km = [x for x in grupo if x["km"] is not None]
    if len(grupo) > 1 and con_km and len(con_km) == len(grupo):
        grupo.sort(key=lambda x: x["km"])
        if abs(grupo[0]["km"] - grupo[1]["km"]) >= float(conf().get("empate_km", 1.5)):
            return grupo[0], ("misma comuna" if misma else "más cerca")
    if preferido and any(x["tec"] == preferido for x in grupo):
        return next(x for x in grupo if x["tec"] == preferido), "preferido"
    if len(grupo) > 1:                                   # empate: uno y uno
        fila = con.execute("SELECT v FROM meta WHERE k='turno_tec'").fetchone()
        ultimo = fila["v"] if fila else ""
        orden = [x for x in grupo if x["tec"] != ultimo] + [x for x in grupo if x["tec"] == ultimo]
        elegido = orden[0]
        con.execute("INSERT OR REPLACE INTO meta VALUES('turno_tec', ?)", (elegido["tec"],))
        return elegido, "turno"
    return grupo[0], ("misma comuna" if misma else "único")


# ---------------------------------------------------------------- tiempos
def duraciones(con, tec=None):
    """Minutos promedio (mediana) de una visita, aprendidos de tus reportes en vivo."""
    q = "SELECT llegada, salida FROM en_vivo WHERE salida IS NOT NULL AND llegada IS NOT NULL"
    p = []
    if tec:
        q += " AND tec=?"
        p.append(tec)
    ms = sorted(m for m in (_dur(f) for f in con.execute(q, p).fetchall()) if m and 10 <= m <= 360)
    if not ms:
        return int(conf().get("minutos_visita", 100))
    return ms[len(ms) // 2]


def eta(con, tec, bloque, ahora=None):
    """Hora estimada en que llega a ese bloque hoy (según dónde va y lo que se demora normalmente)."""
    ahora = ahora or datetime.now()
    x = donde(con, tec, ahora)
    dur = duraciones(con, tec)
    viaje = int(conf().get("minutos_traslado", 25))
    actual = x["bloque"] or 0
    if bloque <= actual:
        return None
    if x["estado"] == "en visita" and x["fuente"] == "en vivo" and x["desde"]:
        base = datetime.combine(ahora.date(), datetime.strptime(x["desde"], "%H:%M").time()) + timedelta(minutes=dur)
        base = max(base, ahora)
    elif x["estado"] == "por partir":
        base = datetime.combine(ahora.date(), inicio_bloque(ahora.date(), 1)) - timedelta(minutes=viaje)
        actual = 0
    else:
        base = ahora
    return base + timedelta(minutes=(bloque - actual - 1) * (dur + viaje) + viaje)


# ---------------------------------------------------------------- textos
def texto_ahora(con, ahora=None):
    import voz
    lin = []
    for x in equipo(con, ahora):
        q = nombre_tec(x["tec"]).lower()
        est = " (según la agenda)" if x["fuente"] == "agenda" else ""
        if x["estado"] == "en visita" and x["rbd"]:
            lin.append(f"{q} está en {voz.nombre(x['rbd'])} ({voz.comuna(x['rbd'])})"
                       + (f", desde las {x['desde']}" if x["desde"] else "") + f"{est}.")
        elif x["estado"] == "entre visitas":
            s = x["siguiente"]
            lin.append(f"{q} salió {voz.del_(x['rbd'])} a las {x['desde']} y va {voz.al(s['rbd'])}.")
        elif x["estado"] == "por partir":
            lin.append(f"{q} todavía no parte; su 1ra visita es {voz.nombre(x['rbd'])}.")
        elif x["estado"] == "terminó":
            lin.append(f"{q} ya terminó por hoy (salió de {voz.el(x['rbd'])} a las {x['desde']}).")
        else:
            lin.append(f"{q} no tiene visitas hoy.")
    return "\n".join(lin)


def texto_reporte_hoy(con, d=None):
    import voz
    d = d or datetime.now().date()
    lin = []
    for tec in datos()["META"]["tecnicos"]:
        filas = con.execute("SELECT * FROM en_vivo WHERE tec=? AND fecha=? ORDER BY bloque", (tec, d.isoformat())).fetchall()
        if not filas:
            continue
        lin.append(nombre_tec(tec).lower() + ":")
        for f in filas:
            dur = _dur(f) if f["salida"] else None
            lin.append(f"{_ord(f['bloque'])} {voz.nombre(f['rbd']) if f['rbd'] else '¿?'}: llegó {f['llegada'][11:16]}"
                       + (f", salió {f['salida'][11:16]} ({_min(dur)})" if f["salida"] else ", sigue ahí"))
    return "\n".join(lin) or "hoy no me has reportado llegadas ni salidas."


def cierre_dia(con, d=None):
    """Lo que quedó sin marcar como hecho al final del día (para preguntarte)."""
    import voz
    d = d or datetime.now().date()
    pend = con.execute("SELECT * FROM tarjetas WHERE fecha=? AND estado='programada' ORDER BY tec, bloque",
                       (d.isoformat(),)).fetchall()
    if not pend:
        return None
    por = {}
    for t in pend:
        por.setdefault(nombre_tec(t["tec"]).lower(), []).append(f"{_ord(t['bloque'])} {voz.nombre(t['rbd'])}")
    cuerpo = "\n".join(f"{k}: {', '.join(v)}" for k, v in por.items())
    return (f"hoy quedaron sin marcar como hechas:\n{cuerpo}\n\n¿cómo les fue? dime por ejemplo "
            f"«rodrigo hizo japón y suiza», «se hicieron todas» o «pásalas» (las corro al día hábil siguiente).")
