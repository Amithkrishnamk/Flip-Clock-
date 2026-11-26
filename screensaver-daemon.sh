#!/usr/bin/env bash
# FlipClock screensaver daemon: cleans up old instances, recovers the
# graphical environment when started by systemd --user, then execs the clock.

set -euo pipefail

INSTALL_DIR="$HOME/.config/flipclock-screensaver"
SCREENSHOT_LOG="/tmp/flipclock-daemon.log"

log() { printf '[flipclock] %s\n' "$*" | tee -a "$SCREENSHOT_LOG" >/dev/null; }

# 1. Kill any existing screensaver.py instance cleanly.
pkill -f '[s]creensaver.py' 2>/dev/null || true
sleep 0.3
pkill -9 -f '[s]creensaver.py' 2>/dev/null || true
log "previous screensaver instances cleared"

# 2. Discover DISPLAY from /tmp/.X11-unix or from a running X server's environ.
if [[ -z "${DISPLAY:-}" ]]; then
    for socket in /tmp/.X11-unix/X*; do
        [[ -e "$socket" ]] || continue
        export DISPLAY=":${socket##*/X}"
        break
    done
fi
if [[ -z "${DISPLAY:-}" ]]; then
    for pid in $(pgrep -u "$(id -u)" -f 'X(org|wayland)' 2>/dev/null || true); do
        value=$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep '^DISPLAY=' | head -1 || true)
        if [[ -n "$value" ]]; then
            export DISPLAY="${value#DISPLAY=}"
            break
        fi
    done
fi
[[ -n "${DISPLAY:-}" ]] && log "DISPLAY=$DISPLAY"

# 3. Discover DBUS_SESSION_BUS_ADDRESS from the user bus or a session process.
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    if [[ -S "$runtime/bus" ]]; then
        export DBUS_SESSION_BUS_ADDRESS="unix:path=$runtime/bus"
    else
        for pid in $(pgrep -u "$(id -u)" -f 'systemd --user|dbus-daemon' 2>/dev/null || true); do
            value=$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep '^DBUS_SESSION_BUS_ADDRESS=' | head -1 || true)
            if [[ -n "$value" ]]; then
                export DBUS_SESSION_BUS_ADDRESS="${value#DBUS_SESSION_BUS_ADDRESS=}"
                break
            fi
        done
    fi
fi
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]] && command -v loginctl >/dev/null 2>&1; then
    display=$(loginctl show-user "$USER" -p Display --value 2>/dev/null || true)
    if [[ -n "$display" && "$display" != "n/a" ]]; then
        session_pid=$(loginctl show-session "$display" -p Leader --value 2>/dev/null || true)
        if [[ -n "$session_pid" ]]; then
            value=$(tr '\0' '\n' < "/proc/$session_pid/environ" 2>/dev/null | grep '^DBUS_SESSION_BUS_ADDRESS=' | head -1 || true)
            [[ -n "$value" ]] && export DBUS_SESSION_BUS_ADDRESS="${value#DBUS_SESSION_BUS_ADDRESS=}"
        fi
    fi
fi
[[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]] && log "DBUS_SESSION_BUS_ADDRESS discovered"

# 4. Hand over to the screensaver.
log "launching $INSTALL_DIR/screensaver.py"
exec python3 "$INSTALL_DIR/screensaver.py"
