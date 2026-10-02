#!/data/data/com.termux/files/usr/bin/bash
# Levanta el cerebro (Python) y el cartero (WhatsApp). Si alguno se cae, lo revive.
# Se puede correr las veces que quieras: siempre deja UNA sola copia de cada cosa.
cd "$(dirname "$0")"
mkdir -p logs
command -v termux-wake-lock >/dev/null && termux-wake-lock

# 1) apagar todo lo anterior (también los "revividores" de versiones viejas de este script)
for p in $(pgrep -f "iniciar.sh" 2>/dev/null); do [ "$p" != "$$" ] && kill "$p" 2>/dev/null; done
pkill -f "botsoser-" 2>/dev/null; pkill -f "soser-sync" 2>/dev/null
pkill -f "python servidor.py" 2>/dev/null
pkill -f "node bot.mjs" 2>/dev/null
sleep 2

# 2) cada 30 min trae lo nuevo del repo: datos.js del panel y, si hay código nuevo del bot, lo reinicia solo
( exec -a botsoser-sync bash -c '
  while true; do
    a=$(git -C .. rev-parse HEAD 2>/dev/null)
    git -C .. pull -q 2>>logs/git.log
    b=$(git -C .. rev-parse HEAD 2>/dev/null)
    if [ -n "$a" ] && [ "$a" != "$b" ] && git -C .. diff --name-only "$a" "$b" | grep -qE "^bot-ia/.*\.(py|mjs)$"; then
      echo "$(date) código nuevo ($b), reinicio el bot" >> logs/git.log
      pkill -f "python servidor.py"; sleep 4; pkill -f "node bot.mjs"
    fi
    sleep 1800
  done' ) &

# 3) revividores con nombre propio (así el próximo iniciar.sh / detener.sh los encuentra)
MAX_MB=$(python -c "import ajustes;print(ajustes.efectiva().get('logs_max_mb',5))" 2>/dev/null || echo 5)
( exec -a botsoser-servidor bash -c '
  while true; do
    [ -f logs/servidor.log ] && [ "$(stat -c%s logs/servidor.log)" -gt $(('"$MAX_MB"' * 1048576)) ] && mv -f logs/servidor.log logs/servidor.log.1
    python servidor.py >> logs/servidor.log 2>&1
    echo "$(date) servidor se cayó, reinicio" >> logs/servidor.log; sleep 5
  done' ) &
sleep 3
( exec -a botsoser-bot bash -c '
  while true; do
    [ -f logs/bot.log ] && [ "$(stat -c%s logs/bot.log)" -gt $(('"$MAX_MB"' * 1048576)) ] && mv -f logs/bot.log logs/bot.log.1
    node bot.mjs >> logs/bot.log 2>&1
    echo "$(date) bot se cayó, reinicio" >> logs/bot.log; sleep 10
  done' ) &

echo "🤖 Bot SOSER corriendo (una sola copia)."
echo "   Ver en vivo:  tail -f ~/bitacoras/bot-ia/logs/bot.log"
echo "   Detener:      bash ~/bitacoras/bot-ia/detener.sh"
