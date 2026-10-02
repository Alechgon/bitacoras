#!/data/data/com.termux/files/usr/bin/bash
# Instalación del bot IA en Termux. Hace todo y te pregunta solo 3 datos.
#
# Comando único (copiar y pegar en Termux):
#   pkg install -y git && { [ -d ~/bitacoras ] || git clone https://github.com/Alechgon/bitacoras ~/bitacoras; } && bash ~/bitacoras/bot-ia/instalar.sh
set -e
cd "$(dirname "$0")"
git -C .. pull -q || true

echo ""
echo "📦 1/5 Instalando paquetes de Termux (tarda unos minutos)..."
pkg update -y
pkg upgrade -y -o Dpkg::Options::="--force-confnew" || true
pkg install -y nodejs-lts python git termux-api

echo "🐍 2/5 Librería de Excel para Python..."
pip install --upgrade openpyxl

echo "🟢 3/5 Librerías de WhatsApp..."
npm install --omit=optional --no-audit --no-fund

echo ""
echo "✍️  4/5 Tus datos (se guardan solo en este celular, en config.json)"
[ -f config.json ] || cp config.example.json config.json
read -r -p "   API key de Gemini (de aistudio.google.com/apikey): " KEY < /dev/tty
read -r -p "   TU número de WhatsApp, para comandos de admin y reportes (ej 56912345678): " ADMIN < /dev/tty
read -r -p "   Número del chip del BOT (ej 56987654321): " BOTNUM < /dev/tty
read -r -p "   Token de GitHub para que el panel reciba los hallazgos (Enter para omitir): " TOKEN < /dev/tty
KEY="$KEY" ADMIN="${ADMIN//[^0-9]/}" TOKEN="$TOKEN" python - <<'PY'
import json, os
c = json.load(open("config.json", encoding="utf-8"))
if os.environ["KEY"].strip():
    c["gemini_api_key"] = os.environ["KEY"].strip()
if os.environ["ADMIN"]:
    c["admins"] = [os.environ["ADMIN"]]
    c["chat_reportes"] = os.environ["ADMIN"] + "@s.whatsapp.net"
if os.environ["TOKEN"].strip():
    c["github_token"] = os.environ["TOKEN"].strip()
json.dump(c, open("config.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("   ✅ config.json guardado")
PY

mkdir -p logs ~/.termux/boot
cat > ~/.termux/boot/soser-bot.sh <<BOOT
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
cd $(pwd) && bash iniciar.sh >> logs/boot.log 2>&1
BOOT
chmod +x ~/.termux/boot/soser-bot.sh iniciar.sh detener.sh

echo ""
echo "🔗 5/5 Vincular el WhatsApp del bot"
if [ -f auth/creds.json ] && grep -q '"registered":true' auth/creds.json; then
  echo "   Ya estaba vinculado, sigo."
else
  echo "   En unos segundos aparece un CÓDIGO de 8 letras."
  echo "   En el WhatsApp del chip del bot: ⋮ > Dispositivos vinculados > Vincular dispositivo"
  echo "   > 'Vincular con número de teléfono' y escribe el código."
  node bot.mjs --codigo "${BOTNUM//[^0-9]/}"
fi

bash iniciar.sh
echo ""
echo "🎉 Listo. El bot ya está leyendo el grupo."
echo "   Prueba escribiendo !ayuda en el grupo de supervisoras."
echo "   Ver qué hace:   tail -f ~/bitacoras/bot-ia/logs/bot.log"
echo "   Detenerlo:      bash ~/bitacoras/bot-ia/detener.sh"
echo "   Falta solo en Android: Ajustes > Batería > Termux > Sin restricciones"
