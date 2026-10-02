#!/data/data/com.termux/files/usr/bin/bash
# Levanta el cerebro (Python) y el cartero (WhatsApp). Si alguno se cae, lo revive.
# Los logs se rotan solos al pasar el tamaño de logs_max_mb (config.json).
cd "$(dirname "$0")"
mkdir -p logs
command -v termux-wake-lock >/dev/null && termux-wake-lock
pkill -f "python servidor.py" 2>/dev/null; pkill -f "node bot.mjs" 2>/dev/null; pkill -f "soser-sync" 2>/dev/null
sleep 1

MAX_MB=$(python -c "import ajustes;print(ajustes.efectiva().get('logs_max_mb',5))" 2>/dev/null || echo 5)
rotar () {   # si el log pasa el tamaño, se guarda como .1 y parte uno nuevo
  [ -f "$1" ] && [ "$(stat -c%s "$1" 2>/dev/null || echo 0)" -gt $((MAX_MB * 1048576)) ] && mv -f "$1" "$1.1"
}

# trae el datos.js más nuevo del panel cada 30 min (si regeneras el plan, el bot se entera solo)
( exec -a soser-sync bash -c 'while true; do git -C .. pull -q 2>>logs/git.log; sleep 1800; done' ) &

( while true; do rotar logs/servidor.log; python servidor.py >> logs/servidor.log 2>&1
    echo "$(date) servidor se cayó, reinicio" >> logs/servidor.log; sleep 5; done ) &
sleep 3
( while true; do rotar logs/bot.log; node bot.mjs >> logs/bot.log 2>&1
    echo "$(date) bot se cayó, reinicio" >> logs/bot.log; sleep 10; done ) &

echo "🤖 Bot SOSER corriendo."
echo "   Ver en vivo:  tail -f ~/bitacoras/bot-ia/logs/bot.log"
echo "   Detener:      bash ~/bitacoras/bot-ia/detener.sh"
