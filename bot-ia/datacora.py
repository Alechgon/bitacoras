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

# ---- ritmo suave con Datácora (para no cargar el servidor)
import threading
UNA_A_LA_VEZ = threading.Lock()      # una sola consulta a Datácora a la vez
SEG_TAREAS = 300                     # la lista de tareas se pide como mucho cada 5 min
PAUSA_DESCARGA = 3                   # segundos entre un PDF y el siguiente
ZIP_DESDE = 5                        # de 5 verificadores para arriba van en un ZIP


def carpeta_guardados():
    """Donde quedan guardados los verificadores ya bajados (se reusan si los piden de nuevo).
    Si Termux tiene acceso al almacenamiento: Descargas/Verificadores SOSER (se ven en el celular)."""
    for base in (os.path.expanduser("~/storage/downloads"), os.path.expanduser("~/storage/shared/Download")):
        if os.path.isdir(base):
            return os.path.join(base, "Verificadores SOSER")
    return os.path.expanduser("~/verificadores_soser")


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
    """Llama al backend con la sesión; si el token venció, entra de nuevo una vez.
    Si Datácora está lento (500/502/503/504), espera 10 s y prueba solo una vez más."""
    try:
        return _http(method, ruta, cuerpo, _token(), timeout)
    except ErrorDatacora as e:
        st = getattr(e, "status", 0)
        if st == 401:
            return _http(method, ruta, cuerpo, _token(renovar=True), timeout)
        if st in (500, 502, 503, 504):
            time.sleep(10)
            try:
                return _http(method, ruta, cuerpo, _token(), timeout)
            except ErrorDatacora as e2:
                if getattr(e2, "status", 0) in (500, 502, 503, 504):
                    raise ErrorDatacora("Datácora está lento ahora (no respondió a tiempo). Prueba en unos minutos.")
                raise
        raise


def _cache(clave, seg, fn, viejo_ok=1800):
    v = _CACHE.get(clave)
    if v and time.time() - v[0] < seg:
        return v[1]
    try:
        r = fn()
    except ErrorDatacora:
        if v and time.time() - v[0] < viejo_ok:   # Datácora lento: se usa lo último que se bajó
            return v[1]
        raise
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
    return _cache("tasks", SEG_TAREAS, cargar)


def usuarios():
    return _cache("users", 3600, lambda: api("GET", "/api/users") or [])


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


CAMPOS_FECHA = ("scheduled_date", "scheduledDate", "due_date", "dueDate", "task_date", "taskDate", "fecha",
                "fecha_programada", "planned_date", "plannedDate", "visit_date", "visitDate", "start_date", "startDate",
                "date")


def _dia(v):
    """
    Fecha de calendario de un campo 'fecha' de la tarea. '2026-11-04' o '2026-11-04T00:00:00Z' es el 04-11 tal cual
    (si se convirtiera a hora de Chile quedaría 03-11 21:00 = el día anterior: ese era el error).
    """
    if not v:
        return None
    s = str(v)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?", s)
    if not m:
        return None
    if m.group(4) is None or (m.group(4), m.group(5)) in (("00", "00"), ("03", "00")):
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    d = _fecha(s)
    return d.date() if d else None


def fecha_tarea(t):
    """La fecha que le pones al agregar la tarea. Si no trae ninguna, el día en que se subió."""
    for k in CAMPOS_FECHA:
        d = _dia(t.get(k))
        if d:
            return d
    d = subida(t)
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


def _colegios():
    """{rbd: {nombre, lat, lon, tec}} de los establecimientos de la sucursal (datos.js)."""
    try:
        sys.path.insert(0, AQUI)
        import nucleo
        out = {}
        for e in nucleo.datos()["ESTAB"]:
            r = str(e["rbd"])
            out[r] = {"nombre": e.get("nombre") or f"RBD {r}", "lat": e.get("lat"), "lon": e.get("lon"),
                      "tec": clave_tec(_tec_del_colegio(r) or "")}
        return out
    except Exception:
        return {}


def _km(a, b):
    try:
        return ((a["lat"] - b["lat"]) * 111) ** 2 + ((a["lon"] - b["lon"]) * 93) ** 2
    except (TypeError, KeyError):
        return 9e9


def visitas():
    """{rbd: (cantidad de bitácoras cerradas en Datácora, fecha de la última)}."""
    v = {}
    for t in tareas():
        if hecha(t) and cuando_hecha(t):
            rbd = establecimiento(t)[1]
            n, ult = v.get(rbd, (0, None))
            d = cuando_hecha(t).date()
            v[rbd] = (n + 1, max(ult, d) if ult else d)
    return v


def ruta(desde, hasta, titulo):
    """
    Por técnico y día (máx 4), solo lectura de Datácora:
      1) lo que cerró ese día -> "(finalizado HH:MM)"
      2) las tareas que TÚ le asignaste con la fecha de ese día -> sin nada al lado
      3) desde mañana, si queda cupo: sugeridos = los colegios de ese técnico con MENOS visitas en Datácora (y entre ellos los
         más cercanos al primero), para que todos vayan quedando con la misma cantidad de visitas.
    """
    hoy = ahora().date()
    cupo = credenciales()["max_por_dia"]
    hechas, pend, nombres = {}, {}, {}
    ocupados = set()                                  # colegios que ya tienen algo esta semana: no se sugieren
    for t in tareas():
        if cancelada(t):
            continue
        k = clave_tec(tecnico(t))
        nombres.setdefault(k, tecnico(t))
        if hecha(t):
            d = cuando_hecha(t).date() if cuando_hecha(t) else fecha_tarea(t)
            if d and desde <= d <= hasta:
                hechas.setdefault((d, k), []).append(t)
                ocupados.add(establecimiento(t)[1])
        else:
            f = fecha_tarea(t)
            if f and desde <= f <= hasta:
                pend.setdefault((f, k), []).append(t)
                ocupados.add(establecimiento(t)[1])
    col = _colegios()
    vis = visitas()
    cand = {}                                         # técnico -> colegios ordenados de menos a más visitas
    for rbd, c in col.items():
        if c["tec"] and c["tec"] != "SIN TECNICO":
            cand.setdefault(c["tec"], []).append(rbd)
            nombres.setdefault(c["tec"], "")
    for k in cand:
        cand[k].sort(key=lambda r: (vis.get(r, (0, None))[0], vis.get(r, (0, None))[1] or date(2000, 1, 1)))

    def sugerir(k, n):
        """n colegios de k con menos visitas; el primero manda y los demás, los más cercanos a él."""
        libres = [r for r in cand.get(k, []) if r not in ocupados]
        if not libres or n <= 0:
            return []
        minimo = vis.get(libres[0], (0, None))[0]
        tanda = [r for r in libres if vis.get(r, (0, None))[0] <= minimo + 1][:12] or libres[:12]
        elegidos = [tanda[0]]
        resto = [r for r in tanda[1:]]
        while len(elegidos) < n and resto:
            r = min(resto, key=lambda x: (vis.get(x, (0, None))[0], _km(col[elegidos[0]], col[x])))
            elegidos.append(r)
            resto.remove(r)
        for r in elegidos:
            ocupados.add(r)
        return elegidos

    dias, d = [], desde
    while d <= hasta:
        if d.weekday() < 5 or any(k[0] == d for k in list(hechas) + list(pend)):
            dias.append(d)
        d += timedelta(days=1)
    orden = sorted(nombres, key=lambda k: (k == "SIN TECNICO", k))
    out = [f"🗓️ *{titulo}*"]
    algo = hubo_sug = False
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
                if rbd in rbds:
                    continue
                rbds.add(rbd)
                lineas.append(f"- {n}" + (" (no se cerró)" if d < hoy else ""))
            if d > hoy and k != "SIN TECNICO":           # hoy = solo lo que asignaste; sugeridos desde mañana
                for r in sugerir(k, cupo - len(lineas)):
                    lineas.append(f"- {col[r]['nombre']}")
                    hubo_sug = True
            if lineas:
                bloque.append(f"👷 *{_nombre_tec(k, nombres[k])}*")
                bloque += lineas
        if bloque:
            algo = True
            if desde != hasta:
                out.append(f"\n*{_dm(d).capitalize()}*")
            out += bloque
    if not algo:
        return f"🗓️ *{titulo}*\nNo hay tareas en Datácora para esos días."
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


MENUS = {}          # quien -> {"ts", "ids": [task_id...], "fotos": bool}
ORDINALES = {"primero": 1, "primer": 1, "primera": 1, "segundo": 2, "segunda": 2, "tercero": 3, "tercera": 3,
             "tercer": 3, "cuarto": 4, "cuarta": 4, "quinto": 5, "quinta": 5, "sexto": 6, "sexta": 6,
             "septimo": 7, "septima": 7, "octavo": 8, "octava": 8, "noveno": 9, "novena": 9, "decimo": 10, "decima": 10}


def verificadores_menu(rbds, quien, con_fotos=False):
    """'verificadores falabella!' -> lista numerada de las fechas que hay; después se elige con '2!' o '1 3!'."""
    hechas = [t for t in tareas() if hecha(t) and cuando_hecha(t) and envio_id(t) and establecimiento(t)[1] in rbds]
    if not hechas:
        return "📭 No encuentro bitácoras cerradas de ese establecimiento en Datácora.", []
    hechas.sort(key=cuando_hecha, reverse=True)
    hechas = hechas[:15]
    if len(hechas) == 1:
        d = cuando_hecha(hechas[0]).date()
        return verificadores(d, d, None, con_fotos=con_fotos, etiqueta=_dm(d), ids={str(hechas[0].get("id"))})
    MENUS[quien] = {"ts": time.time(), "ids": [str(t.get("id")) for t in hechas], "fotos": con_fotos}
    varios = len({establecimiento(t)[1] for t in hechas}) > 1
    txt = [f"📄 *{'Verificadores' if varios else _corto(establecimiento(hechas[0])[0], 40)}* — tengo estos:"]
    for i, t in enumerate(hechas, 1):
        d = cuando_hecha(t)
        extra = f" · {_corto(establecimiento(t)[0], 24)}" if varios else ""
        txt.append(f"{i}. {d.strftime('%d/%m/%Y')} · {tipo_corto(t)} · {_primer_nombre(tecnico(t))}{extra}")
    txt.append("\n¿Cuál te mando? Responde con el número y *!*: *1!* · varios: *1 3!* · *1-3!* · *todos!*")
    return "\n".join(txt), []


def _eleccion(t, n_max):
    """'2' / '1 3' / '1-3' / 'primero y tercero' / 'todos' -> [índices base 1] o None si no es una elección."""
    t = re.sub(r"\b(el|la|los|las|y|e|verificador(es)?|mandame|manda|dame|quiero|numero|nro|n)\b", " ", t)
    t = re.sub(r"[,.;]", " ", t).strip()
    if not t:
        return None
    if re.fullmatch(r"(todos|todas|todo)", t):
        return list(range(1, n_max + 1))
    out = []
    for p in t.split():
        if p in ORDINALES:
            out.append(ORDINALES[p])
        elif p in ("ultimo", "ultima"):
            out.append(1)
        elif re.fullmatch(r"\d{1,2}", p):
            out.append(int(p))
        elif re.fullmatch(r"\d{1,2}-\d{1,2}", p):
            a, b = map(int, p.split("-"))
            out += list(range(min(a, b), max(a, b) + 1))
        else:
            return None
    return [x for x in dict.fromkeys(out) if 1 <= x <= n_max] or None


def verificadores_elegidos(quien, idx):
    m = MENUS.get(quien)
    ids = {m["ids"][i - 1] for i in idx}
    sel = [t for t in tareas() if str(t.get("id")) in ids]
    if not sel:
        return "📭 Ya no encuentro esas bitácoras en Datácora.", []
    ds = [cuando_hecha(t).date() for t in sel]
    a, b = min(ds), max(ds)
    return verificadores(a, b, None, con_fotos=m["fotos"], etiqueta=_dm(a), ids=ids)


def verificador_ultimo(rbds, con_fotos=False):
    """La última bitácora cerrada de ese colegio (o colegios)."""
    hechas = [t for t in tareas() if hecha(t) and cuando_hecha(t) and envio_id(t) and establecimiento(t)[1] in rbds]
    if not hechas:
        return "📭 No encuentro bitácoras cerradas de ese establecimiento en Datácora.", []
    d = max(cuando_hecha(t) for t in hechas).date()
    return verificadores(d, d, None, con_fotos=con_fotos, etiqueta=_dm(d), rbds=rbds)


def verificadores(desde, hasta, sup=None, con_fotos=False, etiqueta="hoy", rbds=None, ids=None):
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
        if ids and str(t.get("id")) not in ids:
            continue
        sel.append(t)
    quien = f" de {sup.split()[0]}" if sup else ""
    if (rbds or ids) and sel and len({establecimiento(x)[1] for x in sel}) == 1:
        quien += f" · {_corto(establecimiento(sel[0])[0], 30)}"
    rango = (_dm(desde) if desde == hasta else f"{desde.strftime('%d-%m')} al {hasta.strftime('%d-%m')}")
    if not sel:
        return f"📭 No hay bitácoras cerradas{quien} ({rango}) en Datácora.", []
    sel.sort(key=cuando_hecha)
    total = len(sel)
    os.makedirs(SALIDA, exist_ok=True)
    _limpiar_viejos()
    G = carpeta_guardados()
    os.makedirs(G, exist_ok=True)
    ruta_idx = os.path.join(G, "indice.json")
    try:
        idx = json.load(open(ruta_idx, encoding="utf-8"))
    except Exception:
        idx = {}

    def guardar_idx():
        tmp = ruta_idx + ".tmp"
        json.dump(idx, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        os.replace(tmp, ruta_idx)

    archivos, malos, usados, lineas = [], [], set(), []
    zip_todo = con_fotos or len(sel) >= ZIP_DESDE
    # 1) la lista con el nombre final de cada PDF: "Colegio dd-mm-aaaa.pdf"
    items = []
    for t in sel:
        n, rbd = establecimiento(t)
        d = cuando_hecha(t)
        base = _nombre_archivo(f"{n} {d.strftime('%d-%m-%Y')}")
        nom, k = base, 2
        while nom in usados:
            nom, k = f"{base} ({k})", k + 1
        usados.add(nom)
        lineas.append(f"• {d.strftime('%d-%m')} {_corto(n, 30)} — {_primer_nombre(tecnico(t))}")
        items.append({"t": t, "n": n, "nom": nom, "sid": str(envio_id(t)), "mes": d.strftime("%Y-%m"),
                      "pdf": None, "fotos": [], "ok": False, "err": "", "bajado": False})

    def ya_guardado(it):
        e = idx.get(it["sid"]) or {}
        p = os.path.join(G, e.get("pdf", "")) if e.get("pdf") else ""
        if not (p and os.path.isfile(p) and os.path.getsize(p) > 500):
            return False
        fotos = [os.path.join(G, f) for f in e.get("fotos", []) if os.path.isfile(os.path.join(G, f))]
        if con_fotos and not e.get("fotos_listas"):
            return False
        it.update(pdf=p, fotos=fotos, ok=True)
        return True

    def bajar(it):
        """Baja UN verificador completo y lo deja guardado; recién ahí se pasa al siguiente."""
        try:
            det = api("GET", f"/api/submissions/{it['sid']}/detail", timeout=60)
            e = idx.get(it["sid"]) or {}
            p = os.path.join(G, e["pdf"]) if e.get("pdf") and os.path.isfile(os.path.join(G, e["pdf"])) else ""
            if not p:
                pdf = _bajar_pdf(it["t"], det)
                if not pdf.startswith(b"%PDF") or len(pdf) < 500:
                    raise ErrorDatacora("el PDF llegó incompleto")
                os.makedirs(os.path.join(G, it["mes"]), exist_ok=True)
                rel, k = os.path.join(it["mes"], it["nom"] + ".pdf"), 2
                while os.path.exists(os.path.join(G, rel)):
                    rel, k = os.path.join(it["mes"], f"{it['nom']} ({k}).pdf"), k + 1
                p = os.path.join(G, rel)
                with open(p + ".parcial", "wb") as f:
                    f.write(pdf)
                os.replace(p + ".parcial", p)             # queda guardado solo si llegó entero
                e["pdf"] = rel
            fotos = []
            if con_fotos:
                dir_f = os.path.join(it["mes"], os.path.splitext(os.path.basename(e["pdf"]))[0] + " fotos")
                os.makedirs(os.path.join(G, dir_f), exist_ok=True)
                rels = []
                for j, (ext, b2) in enumerate(_bajar_fotos(it["t"], det), 1):
                    rel = os.path.join(dir_f, f"foto {j:02d}.{ext}")
                    open(os.path.join(G, rel), "wb").write(b2)
                    rels.append(rel)
                e["fotos"], e["fotos_listas"] = rels, True
                fotos = [os.path.join(G, r) for r in rels]
            idx[it["sid"]] = e
            guardar_idx()
            it.update(pdf=p, fotos=fotos, ok=True, bajado=True)
        except Exception as ex:
            it["err"] = str(ex)

    # 2) primero se busca en lo guardado; lo que falta se baja de a uno (termina uno, pausa, sigue el otro)
    guardados = sum(1 for it in items if ya_guardado(it))
    seguidos_malos, cortado, primero = 0, [], True
    for i, it in enumerate(items):
        if it["ok"]:
            continue
        if not primero:
            time.sleep(PAUSA_DESCARGA)
        primero = False
        if seguidos_malos >= 3:                          # Datácora caída: no se insiste
            cortado = [x for x in items[i:] if not x["ok"]]
            break
        bajar(it)
        seguidos_malos = 0 if it["ok"] else seguidos_malos + 1
    # 3) los que fallaron se reintentan una vez más, con calma
    faltan = [it for it in items if not it["ok"] and it not in cortado]
    if faltan and not cortado:
        time.sleep(30)
        for it in faltan:
            bajar(it)
            time.sleep(PAUSA_DESCARGA)
    for it in items:
        if not it["ok"] and it not in cortado:
            malos.append(f"{_corto(it['n'], 30)} ({it['err']})")
    # 4) se juntan todos y recién ahí se mandan (en orden de fecha)
    listos = [it for it in items if it["ok"]]
    if listos and not zip_todo:
        archivos += [{"ruta": it["pdf"], "nombre": it["nom"] + ".pdf"} for it in listos]
    if listos and zip_todo:
        nombre_zip = _nombre_archivo(f"Verificadores{quien} {rango}{' con fotos' if con_fotos else ''}") + ".zip"
        ruta_zip = os.path.join(SALIDA, f"{datetime.now().strftime('%H%M%S')} {nombre_zip}")
        with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for it in listos:
                if con_fotos:
                    z.write(it["pdf"], f"{it['nom']}/{it['nom']}.pdf")
                    for f in it["fotos"]:
                        z.write(f, f"{it['nom']}/{os.path.basename(f)}")
                else:
                    z.write(it["pdf"], f"{it['nom']}.pdf")
        archivos.append({"ruta": ruta_zip, "nombre": nombre_zip})
    ok = len(listos)
    txt = [f"📄 *Verificadores{quien} · {rango}*: {ok} de {total}"
           + (" (en un ZIP" + (" con fotos" if con_fotos else "") + ")" if zip_todo and ok else "")]
    txt += lineas[:60]
    if len(lineas) > 60:
        txt.append(f"… y {len(lineas) - 60} más")
    if malos:
        txt.append("⚠️ Sin PDF: " + "; ".join(malos[:10]))
    if cortado:
        txt.append(f"⏸️ Datácora no estaba respondiendo y paré para no cargarla; faltaron {len(cortado)}. "
                   "Pídelos de nuevo en unos minutos (los que ya bajé quedan guardados).")
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


def responder(texto, autor="", sup_autor=None, quien=None):
    """
    Devuelve {"texto": str, "archivos": [{ruta, nombre}]} o None si la frase no es de Datácora.
    sup_autor = nombre de la supervisora que escribió (si es supervisora): sus verificadores por defecto.
    quien = número de quien escribe (para recordar el menú de fechas que se le mostró).
    """
    if "!" not in texto:
        return None                                      # solo frases con "!"
    t = norm(texto).replace("!", " ").strip()
    quien = quien or autor or "?"
    menu = MENUS.get(quien)
    if menu and time.time() - menu["ts"] > 1800:
        MENUS.pop(quien, None)
        menu = None
    if menu:
        idx = _eleccion(t, len(menu["ids"]))
        if idx:
            if not UNA_A_LA_VEZ.acquire(blocking=False):
                return {"texto": "⏳ Estoy terminando otra consulta de Datácora; voy de a una para no cargarla. "
                                 "Pídemelo de nuevo en un par de minutos.", "archivos": []}
            try:
                txt, arch = verificadores_elegidos(quien, idx)
                return {"texto": txt, "archivos": arch}
            except ErrorDatacora as e:
                return {"texto": f"❌ Datácora: {e}", "archivos": []}
            finally:
                UNA_A_LA_VEZ.release()
    if not PATRON.search(t):
        if not credenciales()["ollama_activo"]:
            return None
        t = _ollama_elegir(texto) or t
        if not PATRON.search(t):
            return None
    if not configurado():
        return {"texto": "⚙️ Falta conectar Datácora en el celular: en Termux corre "
                         "`python ~/bitacoras/bot-ia/datacora.py configurar`", "archivos": []}
    if not UNA_A_LA_VEZ.acquire(blocking=False):
        return {"texto": "⏳ Estoy terminando otra consulta de Datácora; voy de a una para no cargarla. "
                         "Pídemelo de nuevo en un par de minutos.", "archivos": []}
    try:
        return _responder(t, texto, sup_autor, quien)
    finally:
        UNA_A_LA_VEZ.release()


def _responder(t, texto, sup_autor, quien="?"):
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
            if rbds and not tiene_fecha(t):              # "verificadores falabella!" -> menú con las fechas que hay
                txt, arch = verificadores_menu(rbds, quien, con_fotos="foto" in t or "zip" in t)
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
        f = {k: v for k, v in t.items() if v and (k in ("status", "task_type") or "date" in k.lower()
                                                   or "fecha" in k.lower() or k.endswith("_at"))}
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
