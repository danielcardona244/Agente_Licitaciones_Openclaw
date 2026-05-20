#!/bin/bash
# arrancar_claudio.sh — botón "Despertar a Claudio"
# Controla el LaunchAgent oficial de OpenClaw (ai.openclaw.gateway).
#   - Si el agent está cargado en launchd: kickstart (idempotente, no rompe sesiones vivas).
#   - Si el agent está descargado (caso post-bootout): bootstrap para recargarlo;
#     launchd lo arranca solo porque el plist tiene RunAtLoad=true.

set -u

LABEL="ai.openclaw.gateway"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
PUERTO=18789

# PATH explícito (Automator no hereda PATH completo; lsof vive en /usr/sbin).
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/usr/sbin:/bin:/sbin"

UID_USUARIO=$(id -u)
DOMINIO="gui/${UID_USUARIO}"
SERVICIO="${DOMINIO}/${LABEL}"

notificar() {
    osascript -e "display notification \"$1\" with title \"Claudio\""
}

# Si ya está escuchando en el puerto oficial, no hacemos nada.
if lsof -t -iTCP:${PUERTO} -sTCP:LISTEN >/dev/null 2>&1; then
    notificar "Claudio ya estaba despierto en el puerto ${PUERTO}."
    exit 0
fi

if [ ! -f "$PLIST" ]; then
    notificar "No se encontró el LaunchAgent de OpenClaw. ¿Está OpenClaw instalado?"
    exit 1
fi

notificar "Claudio está despertando y conectándose a Telegram..."

# ¿El agent está cargado actualmente en el dominio del usuario?
if launchctl print "$SERVICIO" >/dev/null 2>&1; then
    # Cargado pero no escuchando (raro pero posible): kickstart lo arranca.
    launchctl kickstart "$SERVICIO" >/dev/null 2>&1
else
    # No cargado: bootstrap lo registra; launchd lo arranca por RunAtLoad=true.
    launchctl bootstrap "$DOMINIO" "$PLIST" 2>/dev/null
fi

# Esperar hasta 10s a que el puerto entre en LISTEN.
for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    if lsof -t -iTCP:${PUERTO} -sTCP:LISTEN >/dev/null 2>&1; then
        notificar "Claudio está despierto en el puerto ${PUERTO}."
        exit 0
    fi
done

notificar "Claudio no respondió en 10s. Revisar ~/Library/Logs/openclaw/gateway.log."
exit 1
