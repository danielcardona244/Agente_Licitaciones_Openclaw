#!/bin/bash
# apagar_claudio.sh — botón "Apagar a Claudio"
# Descarga el LaunchAgent oficial (ai.openclaw.gateway):
#   - launchctl bootout: detiene el proceso y lo desregistra de launchd,
#     evitando que KeepAlive=true lo resucite.
#   - macOS recarga el agent automáticamente en el próximo login, o lo recarga
#     manualmente el botón "Despertar a Claudio".

set -u

LABEL="ai.openclaw.gateway"
PUERTO=18789

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin"

UID_USUARIO=$(id -u)
DOMINIO="gui/${UID_USUARIO}"
SERVICIO="${DOMINIO}/${LABEL}"

notificar() {
    osascript -e "display notification \"$1\" with title \"Claudio\""
}

puerto_libre() {
    ! lsof -t -iTCP:${PUERTO} -sTCP:LISTEN >/dev/null 2>&1
}

notificar "Cerrando conexiones y liberando puertos..."

# ¿Hay algo que apagar?
if ! launchctl print "$SERVICIO" >/dev/null 2>&1 && puerto_libre; then
    notificar "Claudio ya estaba apagado."
    exit 0
fi

# bootout descarga el agent (detiene el proceso y bloquea el restart automático).
# Requiere que la carpeta del plist esté legible; el dominio gui/UID corresponde
# al usuario actual sin sudo.
launchctl bootout "$SERVICIO" 2>/dev/null || true

# bootout puede tardar unos segundos (ExitTimeOut=20 en el plist).
# Esperamos hasta 12s a que el puerto realmente se libere.
for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
    sleep 1
    if puerto_libre; then
        notificar "Claudio se ha dormido correctamente. Puerto ${PUERTO} libre."
        exit 0
    fi
done

# Fallback: si bootout no logró cerrarlo en 12s, matar manualmente los PIDs del puerto.
PIDS_RESTANTES=$(lsof -t -iTCP:${PUERTO} -sTCP:LISTEN 2>/dev/null || true)
if [ -n "$PIDS_RESTANTES" ]; then
    echo "$PIDS_RESTANTES" | xargs kill -9 2>/dev/null || true
    sleep 1
fi

if puerto_libre; then
    notificar "Claudio se ha dormido (cierre forzado). Puerto ${PUERTO} libre."
    exit 0
fi

notificar "No se pudo liberar el puerto ${PUERTO}. Revisar manualmente."
exit 1
