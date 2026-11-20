#!/data/data/com.termux/files/usr/bin/bash
# Instala todo lo de IA del bot SOSER en Termux (se puede correr las veces que quieras):
#   Ollama + Qwen 2.5 1.5B + modelo "soser"   -> entender y clasificar texto
#   whisper.cpp (modelo base, español)        -> audios de WhatsApp a texto
#   ffmpeg                                    -> convertir los audios de WhatsApp
#   tesseract + español                       -> leer texto de fotos de documentos
#   poppler (pdftotext)                       -> sacar texto de PDF
#   openpyxl                                  -> registro de trabajos en Excel
#   carpeta Descargas/SOSER                   -> donde queda todo ordenado
cd "$(dirname "$0")"
AQUI=$(pwd)
ok() { echo "   ✅ $1"; }
mal() { echo "   ❌ $1"; FALLAS="$FALLAS\n - $1"; }
FALLAS=""

echo "1/7 📦 Paquetes de Termux…"
pkg update -y >/dev/null 2>&1
pkg install -y ollama ffmpeg tesseract poppler git cmake clang make python curl >/dev/null 2>&1 \
  && ok "paquetes" || mal "paquetes (corre: pkg install -y ollama ffmpeg tesseract poppler git cmake clang make)"
pip install -q openpyxl 2>/dev/null && ok "openpyxl" || mal "openpyxl (corre: pip install openpyxl)"

echo "2/7 📁 Carpeta SOSER en Descargas…"
if [ ! -d ~/storage/downloads ]; then
  echo "   Android te va a pedir permiso de archivos: dale PERMITIR."
  termux-setup-storage; sleep 8
fi
if [ -d ~/storage/downloads ]; then
  mkdir -p ~/storage/downloads/SOSER/{Colegios,Supervisoras,Trabajos,Bandeja}
  ok "Descargas/SOSER"
else
  mkdir -p ~/SOSER/{Colegios,Supervisoras,Trabajos,Bandeja}
  mal "sin permiso de archivos: quedó en ~/SOSER (corre termux-setup-storage y repite)"
fi

echo "3/7 🔤 Lectura de fotos en español (tesseract)…"
TD="$PREFIX/share/tessdata"
if [ ! -f "$TD/spa.traineddata" ]; then
  curl -sL -o "$TD/spa.traineddata" https://github.com/tesseract-ocr/tessdata_fast/raw/main/spa.traineddata
fi
tesseract --list-langs 2>/dev/null | grep -q spa && ok "tesseract español" || mal "tesseract español"

echo "4/7 🎤 whisper.cpp (audios a texto). La primera vez compila: 5 a 15 minutos, no cierres Termux…"
W=~/whisper.cpp
if [ ! -x "$W/build/bin/whisper-cli" ]; then
  [ -d "$W" ] || git clone -q --depth 1 https://github.com/ggml-org/whisper.cpp "$W"
  cmake -S "$W" -B "$W/build" -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=ON >/dev/null 2>&1
  cmake --build "$W/build" -j4 --config Release --target whisper-cli >/dev/null 2>&1
fi
[ -f "$W/models/ggml-base.bin" ] || bash "$W/models/download-ggml-model.sh" base >/dev/null 2>&1
if [ -x "$W/build/bin/whisper-cli" ] && [ -f "$W/models/ggml-base.bin" ]; then ok "whisper.cpp + modelo base"
else mal "whisper.cpp (mándame: ls ~/whisper.cpp/build/bin ~/whisper.cpp/models)"; fi

echo "5/7 🧠 Ollama + Qwen + modelo soser…"
pkill -f "ollama serve" 2>/dev/null; sleep 1
mkdir -p logs
nohup ollama serve >> logs/ollama.log 2>&1 &
for i in $(seq 1 20); do curl -s http://127.0.0.1:11434 >/dev/null && break; sleep 1; done
ollama pull qwen2.5:1.5b >/dev/null 2>&1 && ok "qwen2.5:1.5b" || mal "bajar qwen2.5:1.5b"
ollama create soser -f ia/Modelfile >/dev/null 2>&1 && ok "modelo soser (reglas del bot)" || mal "crear modelo soser"

echo "6/7 🧪 Pruebas…"
for frase in 'oye dónde anda el Rodrigo' 'pásame los verificadores del lunes' 'qué ruta tienen mañana' 'compraste pan?'; do
  t0=$(date +%s)
  r=$(ollama run soser "$frase" 2>/dev/null | tr -d '\r' | head -n 1)
  echo "   🧠 «$frase» → $r   ($(( $(date +%s) - t0 )) s)"
done
if [ -x "$W/build/bin/whisper-cli" ] && [ -f "$W/samples/jfk.wav" ]; then
  t0=$(date +%s)
  r=$("$W/build/bin/whisper-cli" -m "$W/models/ggml-base.bin" -f "$W/samples/jfk.wav" -nt -t 4 2>/dev/null | tr -s ' \n' ' ' | cut -c1-70)
  echo "   🎤 audio de prueba (11 s, inglés) → «$r» ($(( $(date +%s) - t0 )) s)"
fi
pdftotext -v >/dev/null 2>&1 && ok "pdftotext" || mal "pdftotext"
ffmpeg -version >/dev/null 2>&1 && ok "ffmpeg" || mal "ffmpeg"

echo "7/7 📋 Resumen"
if [ -z "$FALLAS" ]; then
  echo "🎉 Todo instalado. Mándale una captura de esta pantalla a Claude."
else
  echo -e "⚠️ Falló:$FALLAS\nMándale una captura de esta pantalla a Claude."
fi
echo "Ollama queda prendido; desde ahora también arranca solo con: bash ~/bitacoras/bot-ia/iniciar.sh"
