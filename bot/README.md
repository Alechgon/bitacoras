# Bot de WhatsApp — SOSER San Pablo

Lee el grupo de supervisoras, detecta de qué establecimiento hablan y qué falla
reportan, y empuja `bot-datos.json` a este repositorio. La página lo toma en la
siguiente carga: entras a la pestaña **WhatsApp** y tocas *Probar si hay datos del bot*.

Si no quieres montar el bot, la pestaña **WhatsApp** de la página hace lo mismo
pegando los mensajes a mano. El bot solo ahorra ese paso.

## Antes de empezar, dos advertencias

Esto usa **Baileys**, que se conecta como si fuera WhatsApp Web. No es una vía
oficial de WhatsApp y el número se puede bloquear. **Usa un chip aparte, no el de
la sucursal.** Para un grupo interno de cuatro personas el riesgo es bajo, pero
existe.

El **token de GitHub queda guardado en el teléfono**, en `config.json`. Ese archivo
está en `.gitignore` y no se sube. Dale solo permiso de `contents:write` sobre este
repositorio, nada más.

## Instalación en Termux

```bash
pkg update && pkg install nodejs-lts git -y
git clone https://github.com/Alechgon/bitacoras.git
cd bitacoras/bot
npm install
cp config.example.json config.json
nano config.json        # pon el nombre del grupo y tu token
npm start
```

La primera vez aparece un QR en la pantalla. Lo escaneas desde
**WhatsApp → Ajustes → Dispositivos vinculados → Vincular dispositivo**.
La sesión queda guardada en `sesion/`; no hay que escanear de nuevo.

## El token de GitHub

En github.com → Settings → Developer settings → Personal access tokens →
**Fine-grained tokens** → Generate new token:

- Repository access: **Only select repositories** → `Alechgon/bitacoras`
- Permissions → Repository permissions → **Contents: Read and write**
- Expiration: lo que prefieras; si vence hay que renovarlo en `config.json`

## Dejarlo corriendo siempre

Android mata los procesos en segundo plano. Para que aguante:

```bash
pkg install termux-services -y
termux-wake-lock                  # evita que el sistema lo suspenda
```

Además, en los ajustes de Android: **Batería → Optimización de batería → Termux →
No optimizar**. En Xiaomi, Huawei y Samsung hay que darle además *inicio automático*
y *permitir en segundo plano*.

Para que arranque solo al prender el teléfono, instala **Termux:Boot** desde F-Droid
y crea el archivo `~/.termux/boot/soser.sh`:

```sh
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
cd ~/bitacoras/bot && node bot.js >> ~/bot.log 2>&1
```

```bash
chmod +x ~/.termux/boot/soser.sh
```

Igual te digo la verdad: un VPS de cinco dólares al mes hace esto sin ninguno de
estos dolores de cabeza, y no depende de que el celular esté cargado. El mismo
`bot.js` corre ahí sin cambiarle una línea.

## Qué reconoce

- El establecimiento, por su nombre tal como lo escriben en el chat, o por el RBD
- La criticidad, por las palabras del mensaje: gas, frío, agua, eléctrico, equipo
- Ignora a quien listes en `ignorar` (por defecto, tus propios mensajes)
- No repite un hallazgo que ya tenía registrado
- Conserva los últimos 30 días, configurable en `diasMemoria`

## Si algo falla

| Qué pasa | Qué hacer |
|---|---|
| `Sesión cerrada desde el teléfono` | Borra la carpeta `sesion/` y vuelve a escanear el QR |
| `GitHub respondió 401` | El token venció o está mal copiado |
| `GitHub respondió 403` | Al token le falta el permiso *Contents: Read and write* |
| No detecta un establecimiento | Agrégalo al diccionario `ALIAS` en `datos.js` |
| El bot se cierra solo al rato | Falta `termux-wake-lock` o sacar Termux de la optimización de batería |

Los hallazgos quedan también en `bot/estado.json`, por si hay que revisarlos a mano.
