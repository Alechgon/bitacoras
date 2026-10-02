"""
ajustes.py — toda la configuración del bot, editable y segura.

- config.json es TU copia (con llaves y números). Nunca se sube al repo.
- config.example.json es la plantilla con todos los valores por defecto.
- Perfiles (instancias): "prueba" y "produccion". El perfil activo pisa los
  valores generales. Cambiar de perfil no borra nada.

Desde Termux:
  python ajustes.py ver                       -> resumen
  python ajustes.py ver plazo_habiles.GAS     -> un valor
  python ajustes.py fijar plazo_habiles.GAS 1 -> cambia un valor
  python ajustes.py perfil produccion         -> cambia de instancia
  python ajustes.py restablecer borrador      -> vuelve al valor de fábrica
  python ajustes.py instalar --key K --admin 569.. --bot 569.. [--perfil prueba] [--token T]

Desde WhatsApp (admin, en privado con el bot): !config · !config clave valor · !perfil nombre
"""
import copy, json, os, re, sys

BASE = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(BASE, "config.json")
EJEMPLO = os.path.join(BASE, "config.example.json")
SECRETOS = {"gemini_api_key", "github_token"}


# ---------------------------------------------------------------- lectura / escritura
def _cargar(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def ejemplo():
    return _cargar(EJEMPLO)


def leer():
    """config.json tal cual (sin mezclar perfil). Si no existe, parte desde la plantilla."""
    if not os.path.exists(RUTA):
        guardar(ejemplo())
    return _cargar(RUTA)


def guardar(raw):
    """Escritura atómica: nunca deja un config.json a medio escribir."""
    tmp = RUTA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    os.replace(tmp, RUTA)


def migrar():
    """Agrega a config.json las claves nuevas de la plantilla, sin tocar las que ya tienes."""
    raw, ej = leer(), ejemplo()
    cambios = []

    def completar(dst, src, ruta=""):
        for k, v in src.items():
            if k not in dst:
                dst[k] = copy.deepcopy(v)
                cambios.append(ruta + k)
            elif isinstance(v, dict) and isinstance(dst[k], dict) and not k.startswith("_") and k != "perfiles":
                completar(dst[k], v, ruta + k + ".")
        return dst

    completar(raw, ej)
    # perfiles: agrega perfiles nuevos completos, sin pisar los tuyos
    for nombre, p in ej.get("perfiles", {}).items():
        raw.setdefault("perfiles", {})
        if nombre not in raw["perfiles"]:
            raw["perfiles"][nombre] = copy.deepcopy(p)
            cambios.append(f"perfiles.{nombre}")
    if cambios:
        guardar(raw)
    return cambios


def _mezclar(base, encima):
    out = copy.deepcopy(base)
    for k, v in encima.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _mezclar(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def efectiva(raw=None):
    """La configuración que usa el bot: general + perfil activo encima."""
    raw = raw if raw is not None else leer()
    perfil = raw.get("perfiles", {}).get(raw.get("perfil_activo", ""), {})
    return _mezclar(raw, perfil)


# ---------------------------------------------------------------- claves con puntos
def _partes(clave):
    return [p for p in clave.strip().split(".") if p]


def _get(d, partes):
    for p in partes:
        if not isinstance(d, dict) or p not in d:
            raise KeyError(".".join(partes))
        d = d[p]
    return d


def obtener(clave):
    return _get(efectiva(), _partes(clave))


def _coercer(texto, actual, clave):
    """Convierte el texto que escribes al tipo del valor actual, y valida."""
    t = str(texto).strip()
    if isinstance(actual, bool):
        if t.lower() in ("si", "sí", "true", "on", "1", "activo", "activa"):
            return True
        if t.lower() in ("no", "false", "off", "0", "inactivo", "inactiva"):
            return False
        raise ValueError("usa si / no")
    if isinstance(actual, int) and not isinstance(actual, bool):
        try:
            return int(t)
        except ValueError:
            raise ValueError("tiene que ser un número entero")
    if isinstance(actual, float):
        return float(t.replace(",", "."))
    if isinstance(actual, list):
        if t.startswith("["):
            return json.loads(t)
        items = [x.strip() for x in t.split(",") if x.strip()]
        if actual and all(isinstance(x, int) for x in actual):
            return [int(x) for x in items]
        return items
    if isinstance(actual, dict):
        v = json.loads(t)
        if not isinstance(v, dict):
            raise ValueError("tiene que ser un objeto JSON {…}")
        return v
    return t


def _validar(partes, valor):
    hoja = partes[-1]
    if hoja in ("hora", "gas_hoy_si_antes_de"):
        valor = str(valor).replace(".", ":")
        if re.fullmatch(r"\d:[0-5]\d", valor):
            valor = "0" + valor
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", valor):
            raise ValueError("hora en formato HH:MM, ej 07:30")
    if partes[0] == "plazo_habiles" and len(partes) == 2 and not (1 <= int(valor) <= 10):
        raise ValueError("el plazo va de 1 a 10 días hábiles")
    if hoja in ("delay_respuesta_seg", "delay_comando_seg"):
        if len(valor) != 2 or valor[0] > valor[1] or valor[0] < 0:
            raise ValueError("dos números: mínimo, máximo (ej 35,95)")
    if partes[0] == "identificacion" and not (0 <= int(valor) <= 100):
        raise ValueError("de 0 a 100")
    if hoja == "perfil_activo" and valor not in leer().get("perfiles", {}):
        raise ValueError("ese perfil no existe")
    if hoja == "admins":
        valor[:] = [re.sub(r"\D", "", str(x)) for x in valor]
    return valor


def fijar(clave, texto):
    """
    Cambia un valor. Si la clave vive en el perfil activo, se cambia ahí (así
    'grupo_nombre' cambia el grupo de la instancia en uso); si no, en lo general.
    Devuelve (valor_anterior, valor_nuevo, dónde).
    """
    raw = leer()
    partes = _partes(clave)
    if not partes or partes[0].startswith("_"):
        raise KeyError(clave)
    perfil_nombre = raw.get("perfil_activo", "")
    perfil = raw.get("perfiles", {}).get(perfil_nombre, {})
    en_perfil = partes[0] in perfil
    destino = perfil if en_perfil else raw
    try:
        actual = _get(efectiva(raw), partes)
    except KeyError:
        # clave nueva: solo se permite crear hijos de un diccionario existente
        padre = _get(efectiva(raw), partes[:-1]) if len(partes) > 1 else None
        if not isinstance(padre, dict):
            raise KeyError(clave)
        actual = ""
    nuevo = _validar(partes, _coercer(texto, actual, clave))
    d = destino
    for p in partes[:-1]:
        d = d.setdefault(p, {})
    d[partes[-1]] = nuevo
    guardar(raw)
    return actual, nuevo, (f"perfil {perfil_nombre}" if en_perfil else "general")


def restablecer(clave):
    partes = _partes(clave)
    valor = _get(ejemplo(), partes)
    raw = leer()
    d = raw
    for p in partes[:-1]:
        d = d.setdefault(p, {})
    d[partes[-1]] = copy.deepcopy(valor)
    guardar(raw)
    return valor


def cambiar_perfil(nombre):
    raw = leer()
    if nombre not in raw.get("perfiles", {}):
        raise KeyError(nombre)
    raw["perfil_activo"] = nombre
    guardar(raw)


def tapar(clave, valor):
    if clave.split(".")[-1] in SECRETOS and isinstance(valor, str) and valor and not valor.startswith("PEGA"):
        return valor[:4] + "…" + valor[-4:]
    return valor


def resumen():
    c = efectiva()
    b = c.get("borrador", {})
    ok_key = c.get("gemini_api_key", "")
    lin = [
        f"⚙️ *Configuración* · perfil *{c.get('perfil_activo')}* (hay: {', '.join(c.get('perfiles', {}))})",
        f"👥 Grupo: {c.get('grupo_id') or c.get('grupo_nombre')}",
        f"🙈 Ignora: {', '.join(c.get('ignorar', [])) or '(nadie)'}",
        f"👤 Admins: {', '.join(c.get('admins', []))} · 🤖 Bot: {c.get('numero_bot') or '—'}",
        f"🔑 Gemini: {tapar('gemini_api_key', ok_key) if ok_key and not ok_key.startswith('PEGA') else 'SIN CLAVE'} "
        f"({c.get('gemini_endpoint')})",
        f"📝 Modo: {'borrador (apruebas tú)' if c.get('modo_borrador') else 'directo'} · "
        f"recordatorio {b.get('recordatorio_min')} min · gas sale solo a los {b.get('auto_enviar_gas_min')} min",
        f"🗓️ Agenda solo con: {', '.join(c.get('agendar_palabras', [])[:4])}… "
        f"({'obligatorio' if c.get('agendar_requiere_palabra', True) else 'no obligatorio'}) · gas siempre: "
        f"{'sí' if c.get('gas_agenda_siempre', True) else 'no'}",
        f"❓ Preguntas: {'directo al grupo' if c.get('preguntas_sin_aprobacion') else 'pasan por ti'} · "
        f"📸 pedir foto: {'sí' if c.get('pedir_foto', True) else 'no'} · analizar fotos: "
        f"{'sí' if c.get('fotos', {}).get('analizar', True) else 'no'}",
        f"⏱️ Espera respuesta {c.get('delay_respuesta_seg')} s · comandos {c.get('delay_comando_seg')} s",
        f"📅 Agenda al grupo: {'sí' if c.get('agenda_matutina', {}).get('activa') else 'no'} "
        f"{c.get('agenda_matutina', {}).get('hora')} · Reporte: {c.get('reporte_diario', {}).get('hora')}",
        f"🗓️ Plazos: " + ", ".join(f"{k} {v}" for k, v in c.get("plazo_habiles", {}).items()),
        f"👷 Preferencia: " + ", ".join(f"{k}→{v}" for k, v in c.get("preferencia_tecnico", {}).items()),
        f"💾 Respaldo {c.get('respaldo', {}).get('hora')} · guarda {c.get('respaldo', {}).get('conservar_dias')} días",
        "",
        "Cambiar: *!config clave valor* · ej: !config plazo_habiles.GAS 1",
        "Ver uno: *!config ver clave* · Volver a fábrica: *!config reset clave*",
    ]
    return "\n".join(lin)


# ---------------------------------------------------------------- instalación
def instalar(key="", admin="", bot="", perfil="", token=""):
    raw = leer()
    migrar()
    raw = leer()
    if key.strip():
        raw["gemini_api_key"] = key.strip()
    if admin.strip():
        n = re.sub(r"\D", "", admin)
        raw["admins"] = [n]
        raw["chat_reportes"] = n + "@s.whatsapp.net"
    if bot.strip():
        raw["numero_bot"] = re.sub(r"\D", "", bot)
    if token.strip():
        raw["github_token"] = token.strip()
    if perfil.strip():
        if perfil not in raw.get("perfiles", {}):
            raise SystemExit(f"Perfil {perfil} no existe")
        raw["perfil_activo"] = perfil
    guardar(raw)
    return raw


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "ayuda"):
        print(__doc__)
    elif a[0] == "ver":
        if len(a) > 1:
            print(json.dumps(tapar(a[1], obtener(a[1])), ensure_ascii=False, indent=2))
        else:
            print(resumen())
    elif a[0] == "fijar" and len(a) >= 3:
        ant, nuevo, donde = fijar(a[1], " ".join(a[2:]))
        print(f"✅ {a[1]}: {tapar(a[1], ant)} → {tapar(a[1], nuevo)} ({donde})")
    elif a[0] == "perfil" and len(a) == 2:
        cambiar_perfil(a[1])
        print(f"✅ Perfil activo: {a[1]}")
    elif a[0] == "restablecer" and len(a) == 2:
        print("✅", a[1], "→", json.dumps(restablecer(a[1]), ensure_ascii=False))
    elif a[0] == "migrar":
        print("✅ Agregadas:", migrar() or "nada, ya estaba al día")
    elif a[0] == "instalar":
        opts = dict(zip(a[1::2], a[2::2]))
        instalar(opts.get("--key", ""), opts.get("--admin", ""), opts.get("--bot", ""),
                 opts.get("--perfil", ""), opts.get("--token", ""))
        print(resumen())
    else:
        print(__doc__)
