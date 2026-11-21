#!/data/data/com.termux/files/usr/bin/bash
# IA DE PRUEBA (modo sombra). Corre aparte del bot real: solo lee ~/soser-espejo (lo que el bot copia del grupo
# "Mantención - operaciones") y escribe en Descargas/SOSER-prueba. No manda nada a WhatsApp ni toca Datácora.
cd "$(dirname "$0")"
mkdir -p ../logs
pkill -f "soserprueba-" 2>/dev/null
( exec -a soserprueba-sombra bash -c '
  n=0
  while true; do
    [ $((n % 60)) -eq 0 ] && git -C ../.. pull -q 2>>../logs/prueba.log
    python sombra.py >> ../logs/prueba.log 2>&1
    n=$((n+1))
    for i in 1 2 3 4 5 6; do            # lo que le escribes en el grupo Prueba se contesta en segundos
      { [ -s ~/soser-espejo/comandos.jsonl ] || [ -e ~/soser-espejo/.buffer_prueba.json ]; } && python sombra.py chat >> ../logs/prueba.log 2>&1
      sleep 5
    done
  done' ) &
echo "🧪 IA de prueba corriendo en modo sombra (no responde nada, solo aprende y anota)."
echo "   En el grupo Prueba escribe como una supervisora (texto, foto o audio)."
echo "   Comandos sin !: pendientes · ruta de hoy · emular bitácora <colegio> hoy · resuelto <n> · nueva"
echo "   Planilla:         Descargas/SOSER-prueba/solicitudes.xlsx"
echo "   Log en vivo:      tail -f ~/soser-prueba/bot-ia/logs/prueba.log"
echo "   Detener:          pkill -f soserprueba-"
