#!/data/data/com.termux/files/usr/bin/bash
# Instalación / actualización del bot en Termux. Se puede correr las veces que quieras.
#
# Todo en un comando (tus datos van como variables y quedan SOLO en este celular):
#   GEMINI_KEY='...' ADMIN=569XXXXXXXX BOT=569XXXXXXXX PERFIL=prueba bash ~/bitacoras/bot-ia/instalar.sh
# Sin variables, te pregunta lo que falte.
set -e
cd "$(dirname "$0")"
git -C .. pull -q || true

echo ""
echo "📦 1/5 Paquetes de Termux (la primera vez tarda unos minutos)..."
pkg update -y >/dev/null 2>&1 || true
pkg install -y nodejs-lts python git termux-api >/dev/null

echo "🐍 2/5 Librerías de Python (Excel y PDF)..."
# Pillow y cryptography vienen precompilados en Termux; pdfplumber se instala sin
# pypdfium2 (no tiene versión para Android y no se usa: solo leemos texto y tablas).
pkg install -y python-pillow python-cryptography >/dev/null 2>&1 || true
pip install -q --upgrade openpyxl charset-normalizer
pip install -q --upgrade --no-deps pdfplumber pdfminer.six || echo "   ⚠️ No pude instalar el lector de PDF: el bot funciona igual, sin archivo de bitácoras."

echo "🟢 3/5 Librerías de WhatsApp..."
npm install --omit=optional --no-audit --no-fund --silent

echo "⚙️  4/5 Configuración"
python ajustes.py migrar >/dev/null
KEY="${GEMINI_KEY:-}"; ADM="${ADMIN:-}"; BOTN="${BOT:-}"; TOK="${GITHUB_TOKEN:-}"; PERF="${PERFIL:-}"
ACTUAL_KEY=$(python -c "import ajustes;print(ajustes.leer().get('gemini_api_key',''))")
ACTUAL_ADM=$(python -c "import ajustes;print((ajustes.leer().get('admins') or [''])[0])")
if [ -z "$KEY" ] && { [ -z "$ACTUAL_KEY" ] || [[ "$ACTUAL_KEY" == PEGA* ]]; }; then
  read -r -p "   Clave de Gemini: " KEY < /dev/tty
fi
if [ -z "$ADM" ] && { [ -z "$ACTUAL_ADM" ] || [[ "$ACTUAL_ADM" == *X* ]]; }; then
  read -r -p "   TU número (admin, ej 56912345678): " ADM < /dev/tty
fi
if [ -z "$BOTN" ] && [ ! -f auth/creds.json ]; then
  read -r -p "   Número del chip del BOT (ej 56987654321): " BOTN < /dev/tty
fi
python ajustes.py instalar --key "$KEY" --admin "$ADM" --bot "$BOTN" --perfil "$PERF" --token "$TOK"

mkdir -p logs ~/.termux/boot
cat > ~/.termux/boot/soser-bot.sh <<BOOT
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
cd $(pwd) && bash iniciar.sh >> logs/boot.log 2>&1
BOOT
chmod +x ~/.termux/boot/soser-bot.sh iniciar.sh detener.sh

echo ""
echo "🔗 5/5 WhatsApp del bot"
if [ -f auth/creds.json ] && grep -q '"registered":true' auth/creds.json; then
  echo "   Ya estaba vinculado, sigo."
else
  BOTN=${BOTN:-$(python -c "import ajustes;print(ajustes.leer().get('numero_bot',''))")}
  rm -rf auth          # una vinculación a medias impide vincular de nuevo
  bash detener.sh >/dev/null 2>&1 || true
  echo "   Aparecerá un CÓDIGO de 8 caracteres."
  echo "   En el WhatsApp del número del BOT: ⋮ > Dispositivos vinculados > Vincular dispositivo"
  echo "   > 'Vincular con número de teléfono' y escribe el código."
  node bot.mjs --codigo "${BOTN//[^0-9]/}"
fi

bash iniciar.sh
echo ""
echo "🎉 Listo. Prueba desde TU WhatsApp, en el chat con el bot:"
echo "   !diagnostico   → revisa que todo esté verde"
echo "   !simular en guillermo matta olor a gas   → te llega un borrador, responde ok"
echo "   Falta en Android: Ajustes > Batería > Termux > Sin restricciones"
