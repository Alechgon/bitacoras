#!/data/data/com.termux/files/usr/bin/bash
# IA DE PRUEBA (modo sombra). Corre aparte del bot real: solo lee ~/soser-espejo (lo que el bot copia del grupo
# "Mantención - operaciones") y escribe en Descargas/SOSER-prueba. No manda nada a WhatsApp ni toca Datácora.
cd "$(dirname "$0")"
mkdir -p ../logs
pkill -f "soserprueba-" 2>/dev/null
( exec -a soserprueba-sombra bash -c '
  n=0
  while true; do
    [ $((n % 15)) -eq 0 ] && git -C ../.. pull -q 2>>../logs/prueba.log
    python sombra.py >> ../logs/prueba.log 2>&1
    n=$((n+1)); sleep 120
  done' ) &
echo "🧪 IA de prueba corriendo en modo sombra (no responde nada, solo aprende y anota)."
echo "   Lo que entendió:  python ~/soser-prueba/bot-ia/prueba/sombra.py ver"
echo "   Planilla:         Descargas/SOSER-prueba/solicitudes.xlsx"
echo "   Log en vivo:      tail -f ~/soser-prueba/bot-ia/logs/prueba.log"
echo "   Detener:          pkill -f soserprueba-"
