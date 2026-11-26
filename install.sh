#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.config/flipclock-screensaver"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== FlipClock Screensaver Installer ==="

# 1. Install pacman packages (skip if already installed)
PKGS=(python-gobject python-pillow python-cairo libadwaita sxhkd)
for pkg in "${PKGS[@]}"; do
  pacman -Qi "$pkg" &>/dev/null || sudo pacman -S --noconfirm "$pkg"
done

# 2. Install swaylock or i3lock based on session
if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
  pacman -Qi swaylock &>/dev/null || sudo pacman -S --noconfirm swaylock
else
  pacman -Qi i3lock &>/dev/null || sudo pacman -S --noconfirm i3lock
fi

# 3. Install Bebas Neue font if missing
if ! fc-list | grep -qi "bebas"; then
  FONT_DIR="$HOME/.local/share/fonts"
  mkdir -p "$FONT_DIR"
  echo "Downloading Bebas Neue..."
  curl -fL --retry 3 \
    "https://raw.githubusercontent.com/google/fonts/main/ofl/bebasneue/BebasNeue-Regular.ttf" \
    -o "$FONT_DIR/BebasNeue-Regular.ttf"
  fc-cache -f
  echo "Font installed."
fi

# 4. Create install dir and copy every project file
mkdir -p "$INSTALL_DIR"
for f in screensaver.py setup-app.py screensaver-daemon.sh flipclock-daemon.service config.ini README.md install.sh; do
  cp "$SCRIPT_DIR/$f" "$INSTALL_DIR/"
done
chmod +x "$INSTALL_DIR/screensaver.py" "$INSTALL_DIR/setup-app.py" "$INSTALL_DIR/screensaver-daemon.sh"

# 4b. Install desktop launcher entries and icon so Flip Clock appears in the
#     Ryoku app launcher (Super+Space) exactly like Notepad.
APPLICATIONS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$APPLICATIONS_DIR" "$ICON_DIR"
for desktop in flipclock.desktop flipclock-setup.desktop; do
  sed "s|@HOME@|$HOME|g" "$SCRIPT_DIR/$desktop" > "$APPLICATIONS_DIR/$desktop"
done
cp "$SCRIPT_DIR/flipclock.svg" "$ICON_DIR/flipclock.svg"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi

# 5. Install systemd service
SERVICE_DIR="$HOME/.config/systemd/user"
mkdir -p "$SERVICE_DIR"
cp "$INSTALL_DIR/flipclock-daemon.service" "$SERVICE_DIR/"
systemctl --user daemon-reload
if ! systemctl --user enable --now flipclock-daemon; then
  echo "Note: graphical-session.target is not active yet; the service will start at next login."
fi

# 6. Add Hyprland keybind if hyprland.conf exists and bind not already there
HYPR_CONF="$HOME/.config/hypr/hyprland.conf"
if [[ -f "$HYPR_CONF" ]]; then
  if ! grep -q "flipclock-screensaver/screensaver.py" "$HYPR_CONF"; then
    echo "" >> "$HYPR_CONF"
    echo "# FlipClock Screensaver" >> "$HYPR_CONF"
    echo "bind = CTRL, backslash, exec, python3 $INSTALL_DIR/screensaver.py" >> "$HYPR_CONF"
    echo "Hyprland keybind added to $HYPR_CONF"
  fi
fi

# 6b. Ryoku owns the live config through hyprland.lua + user.lua. A plain line
#     in hyprland.conf is ignored there, so register the bind with the Lua API
#     as well. The description makes `hyprctl binds | grep screensaver` work.
HYPR_LUA="$HOME/.config/hypr/hyprland.lua"
USER_LUA="$HOME/.config/hypr/user.lua"
if [[ -f "$HYPR_LUA" && -f "$USER_LUA" ]]; then
  if ! grep -q "flipclock-screensaver/screensaver.py" "$USER_LUA"; then
    echo "" >> "$USER_LUA"
    echo '-- FlipClock Screensaver: Ctrl + \ opens the fullscreen flip clock.' >> "$USER_LUA"
    printf 'hl.bind("CTRL + backslash", hl.dsp.exec_cmd("python3 %s/screensaver.py"), { description = "flipclock screensaver" })\n' \
      "$INSTALL_DIR" >> "$USER_LUA"
    echo "Hyprland Lua keybind added to $USER_LUA"
  fi
fi
if command -v hyprctl >/dev/null 2>&1; then
  hyprctl reload >/dev/null 2>&1 || true
fi

# 7. Add sxhkd hotkey if sxhkdrc exists
SXHKD_CONF="$HOME/.config/sxhkd/sxhkdrc"
if [[ -f "$SXHKD_CONF" ]] && ! grep -q "flipclock" "$SXHKD_CONF"; then
  echo "" >> "$SXHKD_CONF"
  echo "# FlipClock Screensaver" >> "$SXHKD_CONF"
  echo "ctrl + backslash" >> "$SXHKD_CONF"
  echo "    python3 $INSTALL_DIR/screensaver.py" >> "$SXHKD_CONF"
fi

# 8. Auto-detect wallpaper and update config if default path missing
WALLPAPER_PATH=$(grep "wallpaper" "$INSTALL_DIR/config.ini" | cut -d= -f2 | xargs)
WALLPAPER_PATH="${WALLPAPER_PATH/#\~/$HOME}"
if [[ ! -f "$WALLPAPER_PATH" ]]; then
  FOUND=$(find "$HOME/Pictures" -maxdepth 2 \( -name "*.jpg" -o -name "*.png" \) 2>/dev/null | head -1 || true)
  if [[ -n "$FOUND" ]]; then
    sed -i "s|wallpaper = .*|wallpaper = $FOUND|" "$INSTALL_DIR/config.ini"
    echo "Wallpaper auto-set to: $FOUND"
  fi
fi

echo ""
echo "=== Installation complete ==="
echo "Open setup app:  python3 $INSTALL_DIR/setup-app.py"
echo "Test screensaver: python3 $INSTALL_DIR/screensaver.py"
echo "App launcher:    Super+Space -> Flip Clock / Flip Clock Settings"
echo "Hotkey: Ctrl+\\"
