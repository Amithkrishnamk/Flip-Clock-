# FlipClock Screensaver — Arch Linux / Hyprland

A fullscreen flip-clock: three rounded Cairo tiles (HH / MM / SS) over a
Gaussian-blurred wallpaper. `Ctrl + \` opens it; `SPACE` closes it and starts
the lock screen using the exact same blurred image.

## Requirements

- Arch Linux with GTK4 4.10+, libadwaita 1.x, Python 3.11+
- Packages: `python-gobject`, `python-pillow`, `python-cairo`, `libadwaita`, `sxhkd`
- Lock binary: `swaylock` on Wayland (installed automatically), `i3lock` on X11
- Font: Bebas Neue (installed automatically); Archivo Black is the fallback
- A graphical session: Hyprland/Wayland is the primary target, X11 works too

## Install

```bash
git clone https://github.com/Amithkrishnamk/Flip-Clock-.git ~/flipclock-screensaver
cd ~/flipclock-screensaver
chmod +x install.sh
./install.sh
```

The installer installs missing pacman packages, installs the correct lock
binary for `$XDG_SESSION_TYPE`, downloads Bebas Neue into
`~/.local/share/fonts/` and refreshes the font cache, copies all project files
to `~/.config/flipclock-screensaver/`, installs two launcher entries and an
icon so the apps appear in the Ryoku/Hyprland application menu, installs and
enables the systemd user service, adds a Hyprland keybind (native bind or
Ryoku Lua override), adds an sxhkd binding when `sxhkdrc` exists, and
auto-detects a wallpaper from `~/Pictures` when the default path is missing.

## File locations

| Source file | Installed path | Purpose |
| --- | --- | --- |
| `screensaver.py` | `~/.config/flipclock-screensaver/screensaver.py` | Fullscreen clock, SPACE → lock |
| `setup-app.py` | `~/.config/flipclock-screensaver/setup-app.py` | GTK4 settings app |
| `screensaver-daemon.sh` | `~/.config/flipclock-screensaver/screensaver-daemon.sh` | Cleans up old instances, restores display/DBus env, execs the clock |
| `flipclock-daemon.service` | `~/.config/systemd/user/flipclock-daemon.service` | systemd user unit |
| `config.ini` | `~/.config/flipclock-screensaver/config.ini` | Configuration |
| `install.sh` | `~/.config/flipclock-screensaver/install.sh` | Installer copy |
| `README.md` | `~/.config/flipclock-screensaver/README.md` | This document |
| `flipclock.desktop` | `~/.local/share/applications/flipclock.desktop` | Launcher entry for the clock |
| `flipclock-setup.desktop` | `~/.local/share/applications/flipclock-setup.desktop` | Launcher entry for settings |
| `flipclock.svg` | `~/.local/share/icons/hicolor/scalable/apps/flipclock.svg` | Launcher icon |

Runtime files: `/tmp/flipclock-bg.png` (clock background),
`/tmp/lockbg.png` (lock background), `/tmp/flipclock-setup-preview.png`
(setup preview), `/tmp/flipclock-daemon.log` (daemon log).

## Usage

### As a launcher app

Two XDG desktop entries are installed, so Flip Clock behaves like Notepad in
the Ryoku app launcher (`Super+Space`):

- **Flip Clock** — opens the fullscreen clock; its launcher action **Open Settings** opens the setup app.
- **Flip Clock Settings** — opens the setup app directly.

The icon is `~/.local/share/icons/hicolor/scalable/apps/flipclock.svg`, and the
entries live in `~/.local/share/applications/flipclock.desktop` and
`flipclock-setup.desktop`. To pin one to the dock:
`ryoku-shell dock pin flipclock` (show the dock first with `ryoku-shell dock show`).

```bash
# Open the setup app
python3 ~/.config/flipclock-screensaver/setup-app.py

# Show the clock without a hotkey
python3 ~/.config/flipclock-screensaver/screensaver.py

# Hotkey
Ctrl + \
```

The **Preview** button applies the current on-screen selections immediately,
even if you have not pressed **Save & Apply** yet. **Save & Apply** writes
`config.ini`, closes any running clock, and restarts the daemon so the next
launch uses the new settings.

In the clock: `SPACE` writes `/tmp/lockbg.png` at full monitor resolution,
closes the window and execs `swaylock -i /tmp/lockbg.png --scaling fill`
(Wayland) or `i3lock -i /tmp/lockbg.png` (X11). Every other key and mouse
movement is ignored — the clock keeps running.

## Config reference

`~/.config/flipclock-screensaver/config.ini`:

```ini
[screensaver]
wallpaper = ~/Pictures/wallpaper.jpg
blur_sigma = 20
clock_color = #ffffff
tile_color = #1a1a1a
tile_radius = 18
lock_command = swaylock

[hotkey]
trigger = ctrl+backslash
```

Use `;` (not `#`) for inline comments so hex colors such as `#ffffff` parse
correctly. Values are read on the next launch; use **Save & Apply** in the
setup app to write the file and restart the daemon immediately.

| Key | Meaning | Default |
| --- | --- | --- |
| `wallpaper` | Path to the background image (`~` is expanded) | `~/Pictures/wallpaper.jpg` |
| `blur_sigma` | Pillow Gaussian blur radius, 0–60 | `20` |
| `clock_color` | Digit colour, `#rrggbb` | `#ffffff` |
| `tile_color` | Tile colour, `#rrggbb` | `#1a1a1a` |
| `tile_radius` | Rounded corner radius, 0–40 | `18` |
| `lock_command` | `swaylock` or `i3lock` | `swaylock` |
| `trigger` | Documentation of the sxhkd trigger | `ctrl+backslash` |

Tile geometry is fixed by design: width = 22% of screen width, height = 75%
of tile width, gap = 15% of tile width, font size = 40% of tile height, seam
at the exact vertical centre.

## Hyprland keybind

On a plain Hyprland setup the installer appends this to
`~/.config/hypr/hyprland.conf` when the file exists and the binding is not
already present:

```conf
bind = CTRL, backslash, exec, python3 /home/YOU/.config/flipclock-screensaver/screensaver.py
```

Ryoku-managed desktops load `~/.config/hypr/hyprland.lua` instead, so a plain
line in `hyprland.conf` is ignored. When `hyprland.lua` and the user-owned
`~/.config/hypr/user.lua` are present, the installer also registers the live
bind through Ryoku's Lua API:

```lua
hl.bind("CTRL + backslash", hl.dsp.exec_cmd("python3 /home/YOU/.config/flipclock-screensaver/screensaver.py"), { description = "flipclock screensaver" })
```

Reload Hyprland (`hyprctl reload`) if the binding does not respond immediately.
Verify it with `hyprctl binds | grep screensaver` — on Ryoku the description
is what appears, since Lua `exec_cmd` binds show a numeric dispatcher arg.

## sxhkd alternative

For X11 sessions, or when the compositor does not forward the key to
Hyprland, the installer adds this to `~/.config/sxhkd/sxhkdrc`:

```
ctrl + backslash
    python3 /home/YOU/.config/flipclock-screensaver/screensaver.py
```

Start or reload sxhkd with `sxhkd -c ~/.config/sxhkd/sxhkdrc &` or
`pkill -HUP -x sxhkd`. The `flipclock-daemon.service` unit launches
`screensaver-daemon.sh`, which terminates stale screensaver processes and
reconstructs `DISPLAY` and `DBUS_SESSION_BUS_ADDRESS` when systemd does not
pass them through.

## Troubleshooting

**Font not found.** Run `fc-list | grep -i bebas`. If empty, copy
`BebasNeue-Regular.ttf` into `~/.local/share/fonts/` and run `fc-cache -f`.
The renderer falls back to Archivo Black, then Sans Bold.

**Blur is slow.** Very large wallpapers are resized to monitor resolution
before blurring. Lower `blur_sigma` or use a smaller source image. The setup
app computes its preview in a background thread so the UI stays responsive.

**swaylock shows a blank or stretched screen.** Ensure `/tmp/lockbg.png`
exists and is a valid PNG (`file /tmp/lockbg.png`). The clock writes it with
the `--scaling fill` flag at full resolution. Some swaylock builds require
`swaylock -i /tmp/lockbg.png --scaling fill` to be run inside the compositor
session; check `journalctl --user -u flipclock-daemon -b`.

**Wayland vs X11.** Session choice comes from `$XDG_SESSION_TYPE`: Wayland
selects swaylock, X11 selects i3lock. If the variable is unset, Wayland is
assumed when `WAYLAND_DISPLAY` is present. Export the correct value in your
session environment if the wrong locker starts.

**Hotkey does nothing.** Check that the `bind` line is present in
`hyprland.conf` and run `hyprctl reload`. For sxhkd, confirm
`pgrep -a sxhkd` and that the `ctrl + backslash` block exists in `sxhkdrc`.

**Service not running.** `systemctl --user status flipclock-daemon`. The unit
is wanted by `graphical-session.target`; if that target is not active in your
session, start the screensaver directly or with the hotkey.

## License

MIT — see [LICENSE](LICENSE). Contributions and forks are welcome.
