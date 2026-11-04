#!/usr/bin/env python3
"""
datacora.py — el bot lee Datácora EN VIVO (solo lectura) y contesta en WhatsApp.

Frases que entiende (en el grupo o en tu privado; el "!" puede ir al final o al principio):
  donde esta camilo!        donde esta rodrigo!        donde estan los tecnicos!
  ruta para hoy!            ruta para mañana!          ruta para la semana!
      = por técnico, máx 4 al día: lo cerrado, lo pendiente en Datácora (emergencias primero,
        lo atrasado entra hoy) y, si queda espacio, lo del cronograma.
  verificadores de hoy!     verificadores de ayer!     verificadores de la semana!
      + nombre de la supervisora (annahi / stephania / carla). Si no lo pones y lo pide una
        supervisora, se usan los de ella. "de hoy" manda los PDF sueltos; "de la semana" (o
        "...con fotos!") manda un ZIP con los PDF y las fotos, una carpeta por establecimiento.

Si la frase no calza y tienes Ollama corriendo en el celular, Ollama decide cuál de esas
consultas es (nada más: el modelo no inventa datos, solo elige la consulta).

No escribe NADA en Datácora: login + lecturas. Lo único que escribe es la respuesta en WhatsApp.

Credenciales: quedan SOLO en el celular, en ~/.datacora.json (fuera del repo, permiso 600).
  python datacora.py configurar        -> te pide correo y clave y las guarda
  python datacora.py probar            -> login + cuántas tareas ve
  python datacora.py pendientes        -> lista lo pendiente con sus fechas (para revisar la ruta)
  python datacora.py "donde esta camilo!"   -> prueba una consulta en la terminal
También sirven variables de entorno: DATACORA_API_BASE, DATACORA_EMAIL, DATACORA_PASSWORD, DATACORA_TOKEN.

Cómo habla con el backend: lo mismo que la app oficial Datácora JM 2.0 (POST /auth/login,
GET /api/tasks, /api/users, /api/submissions/{id}/detail y la función upload-onedrive-pdf con
download-pdf / submission-photos / download-photo para bajar lo que está en OneDrive).
"""
import base64
import getpass
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
CRED = os.path.expanduser("~/.datacora.json")
BASE_DEF = "http://190.151.96.148:8081"
SALIDA = os.path.join(AQUI, "verificadores_dc")
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("America/Santiago")
except Exception:                                   # Termux sin tzdata: Chile en horario de verano
    TZ = timezone(timedelta(hours=-3))

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


# ============================================================ configuración y sesión
def credenciales():
    c = {}
    if os.path.exists(CRED):
        try:
            c = json.load(open(CRED, encoding="utf-8"))
        except Exception:
            c = {}
    return {
        "base": os.environ.get("DATACORA_API_BASE") or c.get("base") or BASE_DEF,
        "email": os.environ.get("DATACORA_EMAIL") or c.get("email") or "",
        "password": os.environ.get("DATACORA_PASSWORD") or c.get("password") or "",
        "token": os.environ.get("DATACORA_TOKEN") or c.get("token") or "",
        "ollama": c.get("ollama", "http://127.0.0.1:11434"),
        "ollama_modelo": c.get("ollama_modelo", "qwen2.5:1.5b"),
        "ollama_activo": bool(c.get("ollama_activo", False)),
        "minutos_en_sitio": int(c.get("minutos_en_sitio", 60)),
        "max_por_dia": int(c.get("max_por_dia", 4)),
    }


def configurado():
    c = credenciales()
    return bool(c["token"] or (c["email"] and c["password"]))


_SES = {"token": None, "ts": 0}
_CACHE = {}


class ErrorDatacora(Exception):
    pass


def _http(method, ruta, cuerpo=None, token=None, timeout=45):
    c = credenciales()
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(c["base"].rstrip("/") + ruta, data=datos, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read()
            return json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read() or b"{}")
            msg = msg.get("error") or msg.get("message") or ""
        except Exception:
            msg = ""
        err = ErrorDatacora(f"HTTP {e.code} {msg}".strip())
        err.status = e.code
        raise err
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErrorDatacora(f"no llego al servidor de Datácora ({getattr(e, 'reason', e)})")


def _token(renovar=False):
    c = credenciales()
    if c["token"] and not renovar:
        return c["token"]
    if _SES["token"] and not renovar and time.time() - _SES["ts"] < 6 * 3600:
        return _SES["token"]
    if not (c["email"] and c["password"]):
        raise ErrorDatacora("faltan las credenciales: corre  python datacora.py configurar")
    r = _http("POST", "/auth/login", {"email": c["email"], "password": c["password"]})
    tok = r.get("access_token") or r.get("token")
    if not tok:
        raise ErrorDatacora("el login no devolvió token (revisa correo y clave)")
    _SES.update(token=tok, ts=time.time())
    return tok


def api(method, ruta, cuerpo=None, timeout=45):
    """Llama al backend con la sesión; si el token venció, entra de nuevo una vez."""
    try:
        return _http(method, ruta, cuerpo, _token(), timeout)
    except ErrorDatacora as e:
        if getattr(e, "status", 0) == 401:
            return _http(method, ruta, cuerpo, _token(renovar=True), timeout)
        raise


def _cache(clave, seg, fn):
    v = _CACHE.get(clave)
    if v and time.time() - v[0] < seg:
        return v[1]
    r = fn()
    _CACHE[clave] = (time.time(), r)
    return r


def tareas():
    """Tareas de la sucursal (los RBD de datos.js); si no hay datos.js, todas las que ve el usuario."""
    def cargar():
        ts = api("GET", "/api/tasks", timeout=90) or []
        mapa = _sup_de_rbd()
        if not mapa:
            return ts
        nuestros = _tecs_sucursal()
        return [t for t in ts if establecimiento(t)[1] in mapa or clave_tec(tecnico(t)) in nuestros]
    return _cache("tasks", 60, cargar)


def usuarios():
    return _cache("users", 600, lambda: api("GET", "/api/users") or [])


# ============================================================ ayudas sobre una tarea
def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def _fecha(v):
    """ISO del backend -> datetime con hora de Chile (o None)."""
    if not v:
        return None
    s = str(v)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.fromisoformat(s).replace(tzinfo=TZ)
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(TZ)
    except ValueError:
        return None


def ahora():
    return datetime.now(TZ)


def hecha(t):
    return norm(t.get("status")) in ("completada", "completed")


def cuando_hecha(t):
    return _fecha(t.get("submitted_at") or t.get("completed_at") or (t.get("updated_at") if hecha(t) else None))


def dia_tarea(t):
    d = _fecha(t.get("due_date") or t.get("scheduled_date") or t.get("assigned_at") or t.get("created_at"))
    return d.date() if d else None


def tecnico(t):
    nom = t.get("assigned_to_full_name") or t.get("assignedToFullName")
    if not nom:
        tid = str(t.get("assigned_to") or t.get("assignedTo") or "")
        u = next((u for u in usuarios() if str(u.get("id")) == tid), None) if tid else None
        nom = (u or {}).get("full_name") or (u or {}).get("fullName") or ""
    if not nom:
        nom = _tec_del_colegio(establecimiento(t)[1])
    return nom or "Sin técnico"


def _tec_del_colegio(rbd):
    """Técnico que atiende ese colegio según el cronograma (la última visita programada o hecha)."""
    def cargar():
        try:
            sys.path.insert(0, AQUI)
            import nucleo
            D = nucleo.datos()
            m = {}
            for p in sorted(D["PLAN"], key=lambda p: p.get("fecha", "")):
                if p.get("tec"):
                    m[str(p["rbd"])] = D["META"]["tecnicos"].get(p["tec"], {}).get("nombre") or p["tec"].title()
            return m
        except Exception:
            return {}
    return _cache("tec_colegio", 3600, cargar).get(str(rbd), "")


def establecimiento(t):
    e = t.get("establishments") or {}
    nombre = e.get("name") or t.get("establishment_name") or t.get("establishmentName") or ""
    rbd = str(e.get("rbd") or t.get("rbd") or t.get("establishment_rbd") or "")
    return (nombre.strip() or f"RBD {rbd}"), rbd


def institucion(t):
    e = t.get("establishments") or {}
    return t.get("institution_type") or e.get("institution_type") or ""


def tipo(t):
    return t.get("task_type") or t.get("type") or ""


def envio_id(t):
    return t.get("submissionId") or t.get("submission_id") or ""


def es_jardin(t):
    txt = norm(" ".join(str(x) for x in (tipo(t), institucion(t), establecimiento(t)[0])))
    return "junji" in txt or "integra" in txt or "jardin" in txt or "sala cuna" in txt


def cancelada(t):
    return norm(t.get("status")) in ("cancelada", "cancelado", "anulada", "anulado", "cancelled", "canceled",
                                     "eliminada", "eliminado", "deleted")


def pendiente(t):
    return not hecha(t) and not cancelada(t)


def subida(t):
    """Cuándo la subieron o asignaron."""
    return _fecha(t.get("assigned_at") or t.get("created_at") or t.get("assignedAt") or t.get("createdAt"))


def fecha_tarea(t):
    """La fecha que le pones al agregar la tarea (programada / fecha de la tarea). Si no trae, el día en que se subió."""
    d = _fecha(t.get("scheduled_date") or t.get("scheduledDate") or t.get("due_date") or t.get("dueDate")) or subida(t)
    return d.date() if d else None


def dia_objetivo(t):
    """Día en que le toca una tarea pendiente (= su fecha)."""
    return fecha_tarea(t) or ahora().date()


def prioridad(t):
    """0 = emergencia/urgente, 1 = correctiva, 2 = preventiva, 3 = otra."""
    txt = norm(f"{tipo(t)} {t.get('priority') or ''} {t.get('prioridad') or ''}")
    if "emerg" in txt or "urgent" in txt or re.search(r"\balta\b", txt):
        return 0
    if "correct" in txt:
        return 1
    if "prevent" in txt:
        return 2
    return 3


def tipo_corto(t):
    tp = norm(tipo(t))
    for k, v in (("emerg", "Emergencia"), ("correct", "Correctiva"), ("prevent", "Preventiva"), ("visita", "Visita")):
        if k in tp:
            return v
    return _corto(tipo(t), 22)


def clave_tec(nombre):
    """'Camilo Santis Mora' -> 'CAMILO' (así se llaman en el cronograma)."""
    n = norm(nombre).split()
    return n[0].upper() if n and nombre != "Sin técnico" else "SIN TECNICO"


def _tecs_sucursal():
    try:
        sys.path.insert(0, AQUI)
        import nucleo
        return {clave_tec(k) for k in nucleo.datos()["META"]["tecnicos"]}
    except Exception:
        return set()


def _hhmm(d):
    return d.strftime("%H:%M") if d else ""


def _dm(d):
    return f"{DIAS[d.weekday()]} {d.strftime('%d-%m')}"


def _corto(nombre, n=34):
    return nombre if len(nombre) <= n else nombre[:n - 1] + "…"


def _primer_nombre(nom):
    return (nom or "").split()[0].title() if nom else ""


# ============================================================ supervisoras (desde datos.js)
def _sup_de_rbd():
    try:
        sys.path.insert(0, AQUI)
        import nucleo
        return {str(e["rbd"]): e.get("sup", "") for e in nucleo.datos()["ESTAB"]}
    except Exception:
        ruta = os.path.join(AQUI, "..", "datos.js")
        try:
            t = open(ruta, encoding="utf-8").read()
            d = json.loads(t[t.index("{"): t.rindex("}") + 1])
            return {str(e["rbd"]): e.get("sup", "") for e in d["ESTAB"]}
        except Exception:
            return {}


SUPS = {"anahi": "Anahi Uribe", "annahi": "Anahi Uribe", "anahí": "Anahi Uribe", "nangii": "Anahi Uribe",
        "stephania": "Stephania Fernandez", "stefania": "Stephania Fernandez", "estefania": "Stephania Fernandez",
        "carla": "Carla Espinoza"}


def sup_en_texto(texto):
    t = norm(texto)
    for k, v in SUPS.items():
        if re.search(rf"\b{norm(k)}\b", t):
            return v
    return None


# ============================================================ consultas
def donde_esta(quien):
    """
    Lo que pediste: si cerró una bitácora hace menos de 1 hora, está (o recién salió) de ahí;
    si no, el último colegio asignado o autoasignado para hoy; si no hay nada hoy, su última bitácora.
    """
    q = norm(quien)
    mias = [t for t in tareas() if q and q in norm(tecnico(t))]
    if not mias:
        return f"🤷 No encuentro tareas de *{quien.title()}* en Datácora."
    nombre = _primer_nombre(tecnico(mias[0]))
    ya = ahora()
    hoy = ya.date()
    cerradas = sorted((t for t in mias if hecha(t) and cuando_hecha(t)), key=cuando_hecha, reverse=True)
    ult = cerradas[0] if cerradas else None
    lim = credenciales()["minutos_en_sitio"]
    lineas = []
    if ult and (ya - cuando_hecha(ult)) <= timedelta(minutes=lim):
        n, rbd = establecimiento(ult)
        mins = int((ya - cuando_hecha(ult)).total_seconds() // 60)
        lineas.append(f"📍 *{nombre}* está en *{n}* (RBD {rbd}): cerró la bitácora hace {mins} min "
                      f"({_hhmm(cuando_hecha(ult))}){_geo(ult)}.")
    pend_hoy = [t for t in mias if pendiente(t) and dia_objetivo(t) == hoy]
    # primero lo último que le asignaron/autoasignó hoy; después emergencias y lo más antiguo
    pend_hoy.sort(key=lambda t: (not (subida(t) and subida(t).date() == hoy), prioridad(t),
                                 -(subida(t) or ya).timestamp() if subida(t) and subida(t).date() == hoy
                                 else (subida(t) or ya).timestamp()))
    if pend_hoy:
        n, rbd = establecimiento(pend_hoy[0])
        auto = str(pend_hoy[0].get("created_by") or "") and str(pend_hoy[0].get("created_by")) == str(
            pend_hoy[0].get("assigned_to") or "")
        if not lineas:
            lineas.append(f"📍 *{nombre}* tiene {'autoasignado' if auto else 'asignado'} hoy *{n}* (RBD {rbd})"
                          f"{' · ' + tipo_corto(pend_hoy[0]) if tipo(pend_hoy[0]) else ''}.")
        else:
            lineas.append(f"➡️ Después le queda *{n}*.")
        if len(pend_hoy) > 1:
            lineas.append("También le quedan hoy: " + ", ".join(_corto(establecimiento(t)[0], 26) for t in pend_hoy[1:5])
                          + (" y más" if len(pend_hoy) > 5 else "") + ".")
    if not lineas:
        plan = [c for c in cronograma(hoy, hoy) if c["tec"] == clave_tec(tecnico(mias[0]))]
        if plan:
            lineas.append(f"📍 *{nombre}* no tiene tareas subidas hoy en Datácora. En el cronograma le toca "
                          + ", ".join(f"*{_corto(c['nombre'], 30)}* ({c['rbd']})" for c in plan) + ".")
    if not lineas:
        if ult:
            n, rbd = establecimiento(ult)
            d = cuando_hecha(ult)
            cuando = f"hoy a las {_hhmm(d)}" if d.date() == hoy else f"el {_dm(d)} a las {_hhmm(d)}"
            lineas.append(f"📍 *{nombre}* no tiene nada asignado hoy en Datácora. Su última bitácora fue en "
                          f"*{n}* (RBD {rbd}), {cuando}{_geo(ult)}.")
        else:
            lineas.append(f"📍 *{nombre}* no tiene tareas hoy ni bitácoras cerradas en Datácora.")
    hechas_hoy = [t for t in cerradas if cuando_hecha(t).date() == hoy]
    if hechas_hoy:
        lineas.append(f"✅ Hoy lleva {len(hechas_hoy)}: " + ", ".join(
            f"{_corto(establecimiento(t)[0], 24)} {_hhmm(cuando_hecha(t))}" for t in reversed(hechas_hoy)) + ".")
    lineas.append("_(no es GPS en vivo: sale de lo asignado y de las bitácoras de Datácora)_")
    return "\n".join(lineas)


def _geo(t):
    """' · la envió a 40 m del colegio' si Datácora guardó la ubicación al enviar."""
    sid = envio_id(t)
    if not sid:
        return ""
    try:
        det = _cache(f"det:{sid}", 900, lambda: api("GET", f"/api/submissions/{sid}/detail", timeout=25))
    except Exception:
        return ""
    geo = {}
    for a in (det.get("singleAnswerRows") or []) + (det.get("answerRows") or []):
        k = norm(a.get("question_code") or (a.get("form_questions") or {}).get("code") or "").replace(" ", "")
        v = a.get("answer_number") if a.get("answer_number") is not None else a.get("answer_text")
        if k:
            geo[k] = v
    m = geo.get("submitdistancemeters") or geo.get("startdistancemeters")
    try:
        m = float(m)
    except (TypeError, ValueError):
        return ""
    return f" · la envió a {int(m)} m del colegio" if m < 1000 else f" · la envió a {m / 1000:.1f} km del colegio"


def donde_estan():
    hoy = ahora().date()
    tecs = sorted({_primer_nombre(tecnico(t)) for t in tareas()
                   if ((pendiente(t) and dia_objetivo(t) == hoy) or (cuando_hecha(t) and cuando_hecha(t).date() == hoy))
                   and tecnico(t) != "Sin técnico"})
    if not tecs:
        return "Hoy nadie tiene tareas en Datácora."
    return "\n\n".join(donde_esta(t) for t in tecs)


def cronograma(desde, hasta):
    """Lo programado en el cronograma del bot (agenda.db, que se mueve con las emergencias); si no hay, datos.js."""
    filas = []
    try:
        sys.path.insert(0, AQUI)
        import nucleo
        D = nucleo.datos()
        try:
            con = nucleo.db()
            try:
                if con.execute("SELECT COUNT(*) FROM tarjetas").fetchone()[0]:
                    filas = [dict(r) for r in nucleo.agenda(con, desde, hasta)]
                else:
                    filas = None
            finally:
                con.close()
        except Exception:
            filas = None
        if filas is None:
            filas = [p for p in D["PLAN"] if p.get("estado") == "programada"
                     and desde.isoformat() <= p["fecha"] <= hasta.isoformat()]
        out = []
        for c in filas:
            e = D["E"].get(int(c["rbd"])) or {}
            out.append({"fecha": date.fromisoformat(str(c["fecha"])[:10]), "tec": str(c["tec"]).upper(),
                        "bloque": int(c.get("bloque") or 9), "rbd": str(c["rbd"]),
                        "nombre": e.get("nombre") or f"RBD {c['rbd']}", "clase": str(c.get("clase") or "").title()})
        return sorted(out, key=lambda c: (c["fecha"], c["tec"], c["bloque"]))
    except Exception:
        return []


def _linea(marca, nombre, rbd, extra):
    return f"   {marca} {_corto(nombre)} ({rbd}){' · ' + extra if extra else ''}"


def _nombre_tec(k, nombre_dc):
    """'CAMILO' -> 'Camilo Santis' (nombre y primer apellido)."""
    try:
        sys.path.insert(0, AQUI)
        import nucleo
        n = nucleo.datos()["META"]["tecnicos"].get(k, {}).get("nombre")
        if n:
            return " ".join(n.split()[:2])
    except Exception:
        pass
    return " ".join((nombre_dc or k.title()).split()[:2])


def ruta(desde, hasta, titulo):
    """
    Por técnico y día, máximo 4 colegios (solo lectura de Datácora):
      1) los que cerró ese día -> "(finalizado HH:MM)"
      2) las tareas pendientes de Datácora con la fecha de ese día (emergencias primero) -> sin nada al lado
      3) si no llega a 4, lo que sigue en el cronograma (si el día no tiene, se adelanta lo próximo)
    Lo atrasado de otros días no se muestra (se va moviendo en el cronograma).
    """
    hoy = ahora().date()
    cupo = credenciales()["max_por_dia"]
    hechas, pend, nombres = {}, {}, {}
    for t in tareas():
        if cancelada(t):
            continue
        k = clave_tec(tecnico(t))
        nombres.setdefault(k, tecnico(t))
        if hecha(t):
            d = cuando_hecha(t).date() if cuando_hecha(t) else fecha_tarea(t)
            if d and desde <= d <= hasta:
                hechas.setdefault((d, k), []).append(t)
        else:
            f = fecha_tarea(t)
            if f and desde <= f <= hasta and f >= hoy:
                pend.setdefault((f, k), []).append(t)
    # cronograma por técnico, en orden: si un día queda con cupo, se adelanta lo que viene
    plan = {}
    for c in (cronograma(max(desde, hoy), hasta + timedelta(days=30)) if hasta >= hoy else []):
        plan.setdefault(c["tec"], []).append(c)
        nombres.setdefault(c["tec"], "")
    usados = set()

    dias, d = [], desde
    while d <= hasta:
        if d.weekday() < 5 or any(k[0] == d for k in list(hechas) + list(pend)):
            dias.append(d)
        d += timedelta(days=1)
    orden = sorted(nombres, key=lambda k: (k == "SIN TECNICO", k))
    out = [f"🗓️ *{titulo}*"]
    algo = False
    for d in dias:
        bloque = []
        for k in orden:
            lineas, rbds = [], set()
            for t in sorted(hechas.get((d, k), []), key=lambda t: cuando_hecha(t) or ahora()):
                n, rbd = establecimiento(t)
                rbds.add(rbd)
                lineas.append(f"- {n} (finalizado {_hhmm(cuando_hecha(t))})")
            for t in sorted(pend.get((d, k), []), key=lambda t: (prioridad(t), (subida(t) or ahora()).timestamp())):
                n, rbd = establecimiento(t)
                if rbd in rbds or len(lineas) >= cupo:
                    continue
                rbds.add(rbd)
                lineas.append(f"- {n}")
            if d >= hoy:
                for c in plan.get(k, []):
                    if len(lineas) >= cupo:
                        break
                    if id(c) in usados or c["rbd"] in rbds:
                        continue
                    usados.add(id(c))
                    rbds.add(c["rbd"])
                    lineas.append(f"- {c['nombre']}")
            if lineas:
                bloque.append(f"👷 *{_nombre_tec(k, nombres[k])}*")
                bloque += lineas
        if bloque:
            algo = True
            if desde != hasta:
                out.append(f"\n*{_dm(d).capitalize()}*")
            out += bloque
    if not algo:
        return f"🗓️ *{titulo}*\nNo hay nada en Datácora ni en el cronograma para esos días."
    return "\n".join(out)


def _semana(base):
    lun = base - timedelta(days=base.weekday())
    return lun, lun + timedelta(days=4)


# ---------------------------------------------------------------- verificadores
def _nombre_archivo(txt):
    t = re.sub(r'[\\/:*?"<>|]+', " ", str(txt))
    return re.sub(r"\s+", " ", t).strip()[:90] or "archivo"


def _bajar_pdf(t, det):
    filas = det.get("attachmentRows") or []
    filas = sorted(filas, key=lambda r: (str(r.get("file_kind") or "") != "onedrive_bitacora_pdf",
                                         -(_fecha(r.get("created_at")) or datetime.min.replace(tzinfo=TZ)).timestamp()))
    adj = next((r for r in filas if ("pdf" in str(r.get("file_kind") or "") and "photo" not in str(r.get("file_kind") or ""))
                or "pdf" in str(r.get("mime_type") or "").lower()
                or str(r.get("file_name") or "").lower().endswith(".pdf")), {})
    jardin = es_jardin(t)
    r = api("POST", "/functions/upload-onedrive-pdf", {
        "action": "download-pdf", "submissionId": envio_id(t), "attachmentId": adj.get("id"),
        "externalId": adj.get("external_id") or adj.get("externalId") or ("" if jardin else t.get("pdfExternalId") or ""),
        "preferredFileKind": "onedrive_bitacora_pdf" if jardin else ""}, timeout=120)
    url = r.get("dataUrl") or r.get("data_url") or ""
    if not url.startswith("data:application/pdf"):
        raise ErrorDatacora("sin PDF respaldado en OneDrive")
    return base64.b64decode(url.split(",", 1)[1])


def _bajar_fotos(t, det):
    fotos = [r for r in (det.get("attachmentRows") or []) if r.get("file_kind") == "onedrive_photo"]
    try:
        extra = api("POST", "/functions/upload-onedrive-pdf",
                    {"action": "submission-photos", "submissionId": envio_id(t)}, timeout=90).get("photos") or []
    except Exception:
        extra = []
    vistos, out = set(), []
    for f in fotos + extra:
        k = f.get("external_id") or f.get("id") or f.get("file_name")
        if not k or k in vistos:
            continue
        vistos.add(k)
        try:
            r = api("POST", "/functions/upload-onedrive-pdf", {
                "action": "download-photo", "submissionId": envio_id(t), "attachmentId": f.get("id"),
                "externalId": f.get("external_id") or f.get("externalId")}, timeout=120)
            url = r.get("dataUrl") or r.get("data_url") or ""
            if url.startswith("data:image/"):
                ext = "png" if "png" in url[:30] else "webp" if "webp" in url[:30] else "jpg"
                out.append((ext, base64.b64decode(url.split(",", 1)[1])))
        except Exception:
            continue
    return out


def _rbds_en(texto):
    """RBD o nombre de establecimiento dentro de la frase (mismo diccionario del panel)."""
    try:
        sys.path.insert(0, AQUI)
        import nucleo
        limpio = re.sub(r"\b(" + "|".join(list(SUPS) + list(DIAS_RX)) + r")\b", " ", norm(texto))
        return [str(r) for r in nucleo.en_texto(limpio)]
    except Exception:
        return []


def verificador_ultimo(rbds, con_fotos=False):
    """La última bitácora cerrada de ese colegio (o colegios)."""
    hechas = [t for t in tareas() if hecha(t) and cuando_hecha(t) and envio_id(t) and establecimiento(t)[1] in rbds]
    if not hechas:
        return "📭 No encuentro bitácoras cerradas de ese establecimiento en Datácora.", []
    d = max(cuando_hecha(t) for t in hechas).date()
    return verificadores(d, d, None, con_fotos=con_fotos, etiqueta=_dm(d), rbds=rbds)


def verificadores(desde, hasta, sup=None, con_fotos=False, etiqueta="hoy", rbds=None):
    """
    Bitácoras cerradas entre desde y hasta (si hay supervisora, solo sus establecimientos), con el
    PDF renombrado 'Establecimiento dd-mm-aaaa.pdf'. Con fotos (o si son muchos) va todo en un ZIP.
    Devuelve (texto, [ {ruta, nombre}, ... ]).
    """
    mapa = _sup_de_rbd()
    sel = []
    for t in tareas():
        d = cuando_hecha(t)
        if not hecha(t) or not d or not (desde <= d.date() <= hasta) or not envio_id(t):
            continue
        n, rbd = establecimiento(t)
        s = mapa.get(rbd, "")
        if mapa and rbd not in mapa:
            continue                                    # fuera de la sucursal
        if sup and s != sup:
            continue
        if rbds and rbd not in rbds:
            continue
        sel.append(t)
    quien = f" de {sup.split()[0]}" if sup else ""
    if rbds and sel:
        quien += f" · {_corto(establecimiento(sel[0])[0], 30)}"
    rango = (_dm(desde) if desde == hasta else f"{desde.strftime('%d-%m')} al {hasta.strftime('%d-%m')}")
    if not sel:
        return f"📭 No hay bitácoras cerradas{quien} ({rango}) en Datácora.", []
    sel.sort(key=cuando_hecha)
    carpeta = os.path.join(SALIDA, f"{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(carpeta, exist_ok=True)
    _limpiar_viejos()
    archivos, malos, usados, lineas = [], [], set(), []
    zip_todo = con_fotos or len(sel) > 8
    for t in sel:
        n, rbd = establecimiento(t)
        d = cuando_hecha(t)
        base = _nombre_archivo(f"{n} {d.strftime('%d-%m-%Y')}")
        nom, k = base, 2
        while nom in usados:
            nom, k = f"{base} ({k})", k + 1
        usados.add(nom)
        lineas.append(f"• {d.strftime('%d-%m')} {_corto(n, 30)} — {_primer_nombre(tecnico(t))}")
        try:
            det = api("GET", f"/api/submissions/{envio_id(t)}/detail", timeout=60)
            pdf = _bajar_pdf(t, det)
        except Exception as e:
            malos.append(f"{_corto(n, 30)} ({e})")
            continue
        sub = os.path.join(carpeta, nom) if zip_todo else carpeta
        os.makedirs(sub, exist_ok=True)
        ruta_pdf = os.path.join(sub, nom + ".pdf")
        open(ruta_pdf, "wb").write(pdf)
        if con_fotos:
            for i, (ext, b) in enumerate(_bajar_fotos(t, det), 1):
                open(os.path.join(sub, f"foto {i:02d}.{ext}"), "wb").write(b)
        if not zip_todo:
            archivos.append({"ruta": ruta_pdf, "nombre": nom + ".pdf"})
    if zip_todo:
        nombre_zip = _nombre_archivo(f"Verificadores{quien} {rango}{' con fotos' if con_fotos else ''}") + ".zip"
        ruta_zip = os.path.join(SALIDA, nombre_zip)
        with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for raiz, _, fs in os.walk(carpeta):
                for f in fs:
                    p = os.path.join(raiz, f)
                    z.write(p, os.path.relpath(p, carpeta))
        if os.path.getsize(ruta_zip) > 22:
            archivos.append({"ruta": ruta_zip, "nombre": nombre_zip})
    ok = len(sel) - len(malos)
    txt = [f"📄 *Verificadores{quien} · {rango}*: {ok} de {len(sel)}"
           + (" (en un ZIP" + (" con fotos" if con_fotos else "") + ")" if zip_todo and ok else "")]
    txt += lineas[:40]
    if len(lineas) > 40:
        txt.append(f"… y {len(lineas) - 40} más")
    if malos:
        txt.append("⚠️ Sin PDF: " + "; ".join(malos[:10]))
    return "\n".join(txt), archivos


def _limpiar_viejos(dias=3):
    if not os.path.isdir(SALIDA):
        return
    lim = time.time() - dias * 86400
    for f in os.listdir(SALIDA):
        p = os.path.join(SALIDA, f)
        try:
            if os.path.getmtime(p) < lim:
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        except OSError:
            pass


# ============================================================ entender la frase
PATRON = re.compile(r"(donde\s+(esta|anda|estan|andan)|ruta|verificador)")


DIAS_RX = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
MESES = {"enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3, "abril": 4, "abr": 4, "mayo": 5,
         "may": 5, "junio": 6, "jun": 6, "julio": 7, "jul": 7, "agosto": 8, "ago": 8, "septiembre": 9,
         "setiembre": 9, "sep": 9, "sept": 9, "octubre": 10, "oct": 10, "noviembre": 11, "nov": 11,
         "diciembre": 12, "dic": 12}
_RX_DMA = r"\b(\d{1,2})\s*[-/.]\s*(\d{1,2})(?:\s*[-/.]\s*(\d{2,4}))?\b"
_RX_DE = r"\b(\d{1,2})\s+de\s+(" + "|".join(sorted(MESES, key=len, reverse=True)) + r")\b(?:\s+(?:de\s+)?(\d{4}))?"
FECHA_RX = (r"\b(hoy|ayer|antier|anteayer|manana|semana|" + "|".join(DIAS_RX) + r")\b|" + _RX_DMA + "|" + _RX_DE)


def tiene_fecha(texto):
    return bool(re.search(FECHA_RX, norm(texto)))


def es_consulta(texto):
    t = norm(texto)
    return "!" in t and bool(PATRON.search(t))


def _armar(dd, mm, aa, hoy):
    try:
        if aa:
            aa = int(aa)
            aa = aa + 2000 if aa < 100 else aa
            return date(aa, mm, dd)
        d = date(hoy.year, mm, dd)
        return d.replace(year=hoy.year - 1) if d > hoy + timedelta(days=7) else d   # "28-12" en enero = el año pasado
    except ValueError:
        return None


def _fechas_exactas(t, hoy):
    out = []
    for m in re.finditer(_RX_DMA, t):
        d = _armar(int(m.group(1)), int(m.group(2)), m.group(3), hoy)
        if d:
            out.append((m.start(), d))
    for m in re.finditer(_RX_DE, t):
        d = _armar(int(m.group(1)), MESES[m.group(2)], m.group(3), hoy)
        if d:
            out.append((m.start(), d))
    return [d for _, d in sorted(out)]


def _dia_semana(nombre, hoy, pasado=False):
    """'lunes' = el lunes de la semana en curso; si ese día todavía no llega (o dicen 'pasado'), el anterior."""
    d = hoy - timedelta(days=hoy.weekday()) + timedelta(days=DIAS_RX[nombre])
    if pasado or d > hoy:
        d -= timedelta(days=7)
    return d


def _etq(d, hoy):
    if d == hoy:
        return "hoy"
    if d == hoy - timedelta(days=1):
        return "ayer"
    return _dm(d)


def _rango(t, hoy, futuro=False):
    """
    (desde, hasta, etiqueta). Entiende: hoy, ayer, antier, mañana, lunes…domingo (de la semana en curso;
    'el lunes pasado' = el de la semana anterior), esta semana, la semana pasada, 04-11, 4/11/2026,
    4 de noviembre, y rangos 'del 02-11 al 04-11' o 'del lunes al miércoles'.
    """
    if re.search(r"\b(desde|adelante|a la fecha|hasta hoy)\b", t) and not re.search(r"\bhasta\s+(el\s+)?(?!hoy)", t):
        d, _, lbl = _rango(re.sub(r"\b(desde|adelante|en|a la fecha|hasta hoy)\b", " ", t), hoy, futuro=False)
        if d < hoy:
            return d, hoy, f"{_dm(d)} a hoy"
    exactas = _fechas_exactas(t, hoy)
    if len(exactas) >= 2:
        a, b = min(exactas[:2]), max(exactas[:2])
        return a, b, f"{a.strftime('%d-%m')} al {b.strftime('%d-%m')}"
    if exactas:
        return exactas[0], exactas[0], _etq(exactas[0], hoy)
    dias = [(m.start(), m.group(1)) for m in re.finditer(r"\b(" + "|".join(DIAS_RX) + r")\b", t)]
    pasado = bool(re.search(r"\b(pasado|anterior)\b", t)) and "semana pasada" not in t
    if len(dias) >= 2:
        a = _dia_semana(dias[0][1], hoy, pasado)
        b = a + timedelta(days=(DIAS_RX[dias[1][1]] - DIAS_RX[dias[0][1]]) % 7)
        return a, b, f"{_dm(a)} al {_dm(b)}"
    if dias:
        d = _dia_semana(dias[0][1], hoy, pasado)
        if futuro and not pasado:
            d2 = hoy - timedelta(days=hoy.weekday()) + timedelta(days=DIAS_RX[dias[0][1]])
            d = d2 if d2 >= hoy else d2 + timedelta(days=7)
        return d, d, _dm(d)
    if re.search(r"\bsemana pasada\b", t):
        return (*_semana(hoy - timedelta(days=7)), "la semana pasada")
    if "semana" in t:
        return (*_semana(hoy), "la semana")
    if re.search(r"\b(antier|anteayer)\b", t):
        d = hoy - timedelta(days=2)
        return d, d, _dm(d)
    if re.search(r"\bmanana\b", t):
        d = hoy + timedelta(days=1)
        return d, d, "mañana"
    if re.search(r"\bayer\b", t):
        d = hoy - timedelta(days=1)
        return d, d, "ayer"
    return hoy, hoy, "hoy"


def responder(texto, autor="", sup_autor=None):
    """
    Devuelve {"texto": str, "archivos": [{ruta, nombre}]} o None si la frase no es de Datácora.
    sup_autor = nombre de la supervisora que escribió (si es supervisora): sus verificadores por defecto.
    """
    if "!" not in texto:
        return None                                      # solo frases con "!"
    t = norm(texto).replace("!", " ").strip()
    if not PATRON.search(t):
        if not credenciales()["ollama_activo"]:
            return None
        t = _ollama_elegir(texto) or t
        if not PATRON.search(t):
            return None
    if not configurado():
        return {"texto": "⚙️ Falta conectar Datácora en el celular: en Termux corre "
                         "`python ~/bitacoras/bot-ia/datacora.py configurar`", "archivos": []}
    hoy = ahora().date()
    try:
        if re.search(r"donde\s+(esta|anda)\b", t):
            m = re.search(r"donde\s+(?:esta|anda)\s+(?:el\s+|la\s+)?([a-z]+)", t)
            quien = m.group(1) if m else ""
            if quien in ("", "el", "la", "los", "todos", "tecnico", "tecnicos"):
                return {"texto": donde_estan(), "archivos": []}
            return {"texto": donde_esta(quien), "archivos": []}
        if re.search(r"donde\s+(estan|andan)", t):
            return {"texto": donde_estan(), "archivos": []}
        if "verificador" in t:
            rbds = _rbds_en(texto)
            if rbds and not tiene_fecha(t):              # "verificador de falabella!" -> el último de ese colegio
                txt, arch = verificador_ultimo(rbds, con_fotos="foto" in t or "zip" in t)
                return {"texto": txt, "archivos": arch}
            desde, hasta, lbl = _rango(t, hoy)
            sup = sup_en_texto(t) or (None if rbds else sup_autor)
            fotos = "foto" in t or "semana" in t or "zip" in t
            txt, arch = verificadores(desde, hasta, sup, con_fotos=fotos, etiqueta=lbl, rbds=rbds)
            return {"texto": txt, "archivos": arch}
        if "ruta" in t:
            desde, hasta, lbl = _rango(t, hoy, futuro=True)
            if desde == hasta:
                titulo = f"Ruta de {lbl} · {_dm(desde)}" if lbl in ("hoy", "mañana", "ayer") else f"Ruta del {_dm(desde)}"
            else:
                titulo = (f"Ruta de {lbl} · " if "semana" in lbl else "Ruta del ") + \
                    f"{desde.strftime('%d-%m')} al {hasta.strftime('%d-%m')}"
            return {"texto": ruta(desde, hasta, titulo), "archivos": []}
    except ErrorDatacora as e:
        return {"texto": f"❌ Datácora: {e}", "archivos": []}
    return None


def _ollama_elegir(texto):
    """Si hay Ollama, que solo ELIJA la consulta (nunca inventa datos). Si no hay, None."""
    c = credenciales()
    prompt = ("Clasifica el mensaje en UNA de estas consultas y responde solo con ella, en minúsculas, sin nada más:\n"
              "donde esta <nombre> | donde estan | ruta hoy | ruta manana | ruta semana | "
              "verificadores hoy <supervisora> | verificadores ayer <supervisora> | "
              "verificadores semana <supervisora> | ninguna\n"
              "Supervisoras: annahi, stephania, carla. Técnicos: camilo, rodrigo.\n"
              f"Mensaje: {texto}\nConsulta:")
    try:
        req = urllib.request.Request(c["ollama"].rstrip("/") + "/api/generate",
                                     data=json.dumps({"model": c["ollama_modelo"], "prompt": prompt, "stream": False,
                                                      "options": {"temperature": 0}}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            out = norm(json.loads(r.read()).get("response", "")).splitlines()[0:1]
        out = out[0] if out else ""
        return "" if "ninguna" in out else out
    except Exception:
        return None


# ============================================================ terminal
def _configurar():
    print("Credenciales de Datácora (quedan solo en este celular, en ~/.datacora.json).")
    print("Recomendado: un usuario aparte para el bot, con permiso de ver tareas de la sucursal.")
    c = {}
    if os.path.exists(CRED):
        try:
            c = json.load(open(CRED, encoding="utf-8"))
        except Exception:
            c = {}
    base = input(f"Servidor [{c.get('base', BASE_DEF)}]: ").strip() or c.get("base", BASE_DEF)
    email = input(f"Correo [{c.get('email', '')}]: ").strip() or c.get("email", "")
    pw = getpass.getpass("Clave (no se ve al escribir): ").strip() or c.get("password", "")
    c.update(base=base, email=email, password=pw)
    c.pop("token", None)
    _guardar(c)
    print("Guardado. Probando…")
    _probar()


def _guardar(c):
    fd = os.open(CRED, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    os.chmod(CRED, 0o600)


def _ollama(args):
    c = json.load(open(CRED, encoding="utf-8")) if os.path.exists(CRED) else {}
    if not args or args[0] not in ("on", "off"):
        print("Uso: python datacora.py ollama on [modelo]   |   python datacora.py ollama off")
        return
    c["ollama_activo"] = args[0] == "on"
    if len(args) > 1:
        c["ollama_modelo"] = args[1]
    _guardar(c)
    print(f"Ollama {'activado' if c['ollama_activo'] else 'apagado'} ({c.get('ollama_modelo', 'qwen2.5:1.5b')}).")


def _pendientes():
    """Muestra cada tarea pendiente con sus fechas tal como vienen de Datácora (para revisar)."""
    ts = [t for t in tareas() if pendiente(t)]
    print(f"{len(ts)} pendientes (fecha = la que le pusiste al agregarla):")
    for t in sorted(ts, key=lambda t: (clave_tec(tecnico(t)), dia_objetivo(t))):
        n, rbd = establecimiento(t)
        f = {k: t.get(k) for k in ("status", "task_type", "due_date", "scheduled_date", "assigned_at", "created_at")
             if t.get(k)}
        print(f"- {_primer_nombre(tecnico(t)):8} {_dm(dia_objetivo(t))}  {_corto(n, 30)} ({rbd})  {f}")


def _probar():
    try:
        ts = tareas()
        us = usuarios()
        hoy = ahora().date()
        print(f"✅ Conectado a {credenciales()['base']}: {len(ts)} tareas, {len(us)} usuarios.")
        print(f"   Hoy ({hoy}): {sum(1 for t in ts if pendiente(t) and dia_objetivo(t) == hoy)} pendientes, "
              f"{sum(1 for t in ts if hecha(t) and cuando_hecha(t) and cuando_hecha(t).date() == hoy)} cerradas.")
    except ErrorDatacora as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "configurar":
        _configurar()
    elif len(sys.argv) > 1 and sys.argv[1] == "probar":
        _probar()
    elif len(sys.argv) > 1 and sys.argv[1] == "pendientes":
        _pendientes()
    elif len(sys.argv) > 1 and sys.argv[1] == "ollama":
        _ollama(sys.argv[2:])
    elif len(sys.argv) > 1:
        r = responder(" ".join(sys.argv[1:]))
        if not r:
            print("(no es una consulta de Datácora)")
        else:
            print(r["texto"])
            for a in r["archivos"]:
                print("📎", a["ruta"])
    else:
        print(__doc__)
