#!/data/data/com.termux/files/usr/bin/bash
# Muestra en una pantalla todo lo necesario para ver por qué el bot no contesta.
cd "$(dirname "$0")"
echo "=== Versión: $(git -C .. log --oneline -1)"
echo "=== Copias corriendo (debe haber 1 de cada una)"
echo "  servidor python: $(pgrep -fc '^python servidor.py')   bot node: $(pgrep -fc '^node bot.mjs')   revividores: $(pgrep -fc '^botsoser-') (deben ser 3)"
echo "=== Python responde?"
curl -s -m 8 http://127.0.0.1:8765/salud || echo "  ❌ Python NO responde"
echo
echo "=== Datácora directo"
timeout 120 python datacora.py "ruta para hoy!" 2>&1 | head -6
echo "=== Últimas líneas del bot"
tail -n 35 logs/bot.log 2>/dev/null
echo "=== Caídas y reconexiones del bot"
grep -E "se cayó|Reconectando|Conectado a|440|🐕|❌|Killed|heap" logs/bot.log 2>/dev/null | tail -n 12
echo "=== Errores del servidor"
grep -E "Error|Traceback|cayó" logs/servidor.log 2>/dev/null | tail -n 8
echo "=== Actualizaciones"
tail -n 3 logs/git.log 2>/dev/null
