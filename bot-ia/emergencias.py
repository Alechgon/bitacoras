"""
emergencias.py — la respuesta natural a una urgencia en el grupo (sin cuadros, minúscula, sin iconos).

Arranca siempre igual:
    "ok [nombre], entiendo hay que [lo que hay que hacer]."

GAS (criterio SEC: el gas no espera):
    - se agenda al tiro con el instalador de gas certificado (Camilo).
    - calcula comuna y distancia: dice qué técnico está en esa comuna y que va en estos momentos.
      "camilo está en estación central (en el silvia salas), le queda cerca, va para allá altiro."
      si nadie anda cerca: "camilo va saliendo para allá."

NO GAS (frío, agua, luz, equipo…):
    - dice qué se está atendiendo AHORA (según tus reportes en vivo o la agenda):
      "ahora se están atendiendo el república de haití y el santiago de chile."
    - ofrece coordinar la visita al bloque siguiente con el técnico de la misma comuna
      (si los dos están en la comuna, uno y uno / al azar), avisando que tenía otra visita:
      "lo puedo sumar al siguiente bloque con rodrigo, que anda por ahí; tenía el carolina vergara,
       que lo correría al día hábil siguiente. ¿lo coordino? si dicen que sí, les aviso a las tías."
    - si dicen que sí ("sí porfa", "ya", "ya les digo a las tías"): posterga esa visita UN día hábil y agenda.

A ti te llega cada paso para que digas ya / ok / dile esto mejor.
"""
import re
from datetime import datetime

from nucleo import (a_fecha, agendar, bloques, cfg, colocar_forzado, datos, es_habil, es_prioridad, hoy, log, motivo,
                    n_bloques, nombre_tec, sig_habil, sumar_habiles)


def conf():
    return cfg().get("emergencias", {})


def es_emergencia(crit, texto):
    """Gas siempre; lo demás solo si suena urgente (palabras de prioridad) y la config lo incluye."""
    if not conf().get("activa", True):
        return False
    if crit == "GAS":
        return True
    tipos = conf().get("tipos", ["GAS", "FRIO", "AGUA"])
    return crit in tipos and es_prioridad(texto)


# ---------------------------------------------------------------- gas
def responder_gas(con, rbd, problema, crit, autor, hid=None):
    """Agenda el gas al tiro (SEC) y arma la respuesta diciendo qué técnico va ahora. Devuelve (texto, res)."""
    import en_vivo
    import voz
    D = datos()
    n = voz.vocativo(autor)
    pref = cfg().get("preferencia_tecnico", {}).get("GAS", "CAMILO")
    motivo(con, f"Gas en {D['E'][rbd]['nombre']} ({autor}): SEC, se atiende de inmediato")
    res = agendar(con, rbd, "GAS", problema, True, autor, hid)
    donde = en_vivo.mas_cerca(con, rbd, preferido=pref)
    x, por_que = donde if donde else (None, "")
    tec = x["tec"] if x else res["tec"]
    quien = nombre_tec(tec).lower()
    hacer = voz.hay_que(problema, "GAS")
    cab = f"ok {n}, entiendo hay que {hacer}." if n else f"ok, entiendo hay que {hacer}."
    com = voz.comuna(rbd).lower()
    if x and x["estado"] == "en visita" and x["rbd"] and en_vivo.misma_comuna(x["rbd"], rbd):
        detalle = (f"{quien} está en {com} (en {voz.el(x['rbd'])}), le queda cerca. como es gas, lo mandamos para allá "
                   f"altiro.")
    elif x and x["rbd"] and en_vivo.misma_comuna(x["rbd"], rbd):
        detalle = f"{quien} anda por {com}, va para allá altiro."
    elif x and x["estado"] == "en visita" and x["rbd"]:
        km = en_vivo.km(x["rbd"], rbd)
        detalle = (f"{quien} está en {voz.comuna(x['rbd']).lower()}" + (f", a unos {km} km" if km else "") +
                   f"; como es gas sale para {com} apenas termine.")
    else:
        detalle = f"{quien} sale para {com} ({voz.al(rbd)}) en estos momentos."
    texto = f"{cab} {detalle}"
    return texto, res, tec


# ---------------------------------------------------------------- no gas
def _atendiendo_ahora(con, ahora=None):
    import en_vivo
    import voz
    nombres = []
    for x in en_vivo.equipo(con, ahora):
        if x["estado"] == "en visita" and x["rbd"]:
            nombres.append(voz.el(x["rbd"]))
    return nombres


def abrir(con, rbd, problema, crit, autor, hid, ahora=None):
    """
    Urgencia que no es gas: arma la oferta (qué se atiende ahora + coordinar al bloque siguiente).
    Devuelve dict(texto, opcion) donde opcion tiene lo necesario para, si dicen que sí, agendar y postergar.
    """
    import en_vivo
    import voz
    ahora = ahora or datetime.now()
    n = voz.vocativo(autor)
    hacer = voz.hay_que(problema, crit)
    cab = f"ok {n}, entiendo hay que {hacer}." if n else f"ok, entiendo hay que {hacer}."
    atend = _atendiendo_ahora(con, ahora)
    if atend:
        cab += " ahora se " + ("están atendiendo " + voz.lista(atend) if len(atend) > 1
                               else "está atendiendo " + atend[0]) + "."
    # ¿quién puede pasar al bloque siguiente? el de la misma comuna; si empatan, uno y uno
    donde, por_que = en_vivo.mas_cerca(con, rbd, ahora,
                                       preferido=cfg().get("preferencia_tecnico", {}).get(crit))
    tec = donde["tec"]
    quien = nombre_tec(tec).lower()
    d, bloque, desplazada = _hueco_siguiente(con, tec, ahora)
    com = voz.comuna(rbd).lower()
    cerca = "que anda por " + com if (donde.get("rbd") and en_vivo.misma_comuna(donde["rbd"], rbd)) else \
        "que es el que queda más a mano"
    cola = f" lo puedo sumar al siguiente bloque con {quien}, {cerca}."
    if desplazada:
        cola += (f" {quien} tenía {voz.el(desplazada['rbd'])}; ese lo correría al día hábil siguiente.")
    cola += " ¿lo coordino? si me dicen que sí, les aviso a las tías."
    opcion = {"rbd": rbd, "crit": crit, "tec": tec, "fecha": d.isoformat(), "bloque": bloque,
              "desplazada": desplazada["id"] if desplazada else None, "hid": hid, "autor": autor, "problema": problema}
    return {"texto": cab + cola, "opcion": opcion}


def _hueco_siguiente(con, tec, ahora):
    """El próximo bloque de ese técnico: hoy si queda, si no mañana. Devuelve (día, bloque, tarjeta_que_desplaza)."""
    import en_vivo
    d = ahora.date()
    x = en_vivo.donde(con, tec, ahora)
    actual = x["bloque"] or 0
    if es_habil(d) and actual < n_bloques(d):
        b = actual + 1
        ocup = con.execute("SELECT * FROM tarjetas WHERE tec=? AND fecha=? AND bloque=? AND estado='programada'",
                           (tec, d.isoformat(), b)).fetchone()
        return d, b, (dict(ocup) if ocup else None)
    nd = sig_habil(sumar_habiles(d, 1) if es_habil(d) else d)
    ocup = con.execute("SELECT * FROM tarjetas WHERE tec=? AND fecha=? AND estado='programada' ORDER BY bloque LIMIT 1",
                       (tec, nd.isoformat())).fetchone()
    return nd, (ocup["bloque"] if ocup else 1), (dict(ocup) if ocup else None)


def aceptar(con, opcion, autor="supervisora"):
    """Dijeron que sí: posterga la visita desplazada un día hábil y pone la urgencia en ese bloque."""
    import servidor as S
    import voz
    d = a_fecha(opcion["fecha"])
    motivo(con, f"Emergencia coordinada en el grupo ({autor}): {voz.nombre(opcion['rbd'])}")
    res = colocar_forzado(con, opcion["rbd"], opcion["crit"], opcion["problema"], True, opcion["autor"],
                          opcion["hid"], tec=opcion["tec"], d=d, b=opcion["bloque"])
    resp = _texto_hecho(con, opcion, res)
    con.execute("UPDATE hallazgos SET estado='agendado', pts=?, tarjeta_id=?, respuesta=? WHERE id=?",
                (res["pts"], res["tarjeta"], resp, opcion["hid"]))
    log(con, f"Emergencia {opcion['rbd']} coordinada → {opcion['tec']} {d} b{opcion['bloque']}")
    con.commit()
    return resp, res


def _texto_hecho(con, opcion, res):
    import voz
    from conversacion import _dia, _entre
    d = a_fecha(res["fecha"])
    quien = nombre_tec(res["tec"]).lower()
    partes = [f"listo, {quien} pasa {voz.al(opcion['rbd'])} {_dia(d)} {_entre(d, res['bloque'])}."]
    for p in res.get("postergadas") or ([res["movida"]] if res.get("movida") else []):
        a = a_fecha(p["a"])
        from conversacion import pasa_a
        partes.append(f"el {voz.nombre(p['nombre'])} pasa {pasa_a(a)}.")
    partes.append("les aviso a las tías.")
    return " ".join(partes)
