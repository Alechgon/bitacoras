#!/data/data/com.termux/files/usr/bin/bash
for p in $(pgrep -f "iniciar.sh" 2>/dev/null); do kill "$p" 2>/dev/null; done
pkill -f "botsoser-" 2>/dev/null; pkill -f "soser-sync" 2>/dev/null
pkill -f "python servidor.py" 2>/dev/null
pkill -f "node bot.mjs" 2>/dev/null
echo "🛑 Bot detenido"
