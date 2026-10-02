#!/data/data/com.termux/files/usr/bin/bash
# Levanta el cerebro (Python) y el cartero (WhatsApp). Si alguno se cae, lo revive.
cd "$(dirname "$0")"
mkdir -p logs
command -v termux-wake-lock >/dev/null && termux-wake-lock
pkill -f "python servidor.py" 2>/dev/null; pkill -f "node bot.mjs" 2>/dev/null

# trae el datos.js más nuevo del panel cada 30 min (si regeneras el plan, el bot se entera solo)
( while true; do git -C .. pull -q 2>>logs/git.log; sleep 1800; done ) &

( while true; do python servidor.py >> logs/servidor.log 2>&1; echo "$(date) servidor se cayó, reinicio" >> logs/servidor.log; sleep 5; done ) &
sleep 3
( while true; do node bot.mjs >> logs/bot.log 2>&1; echo "$(date) bot se cayó, reinicio" >> logs/bot.log; sleep 10; done ) &

echo "🤖 Bot SOSER corriendo. Para ver qué pasa:  tail -f logs/bot.log logs/servidor.log"
echo "   Para detenerlo:  bash detener.sh"
