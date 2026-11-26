#!/usr/bin/env python3
"""Fullscreen flip-clock screensaver (GTK4 + Cairo + Pillow).

CTRL+\\ (Hyprland or sxhkd) launches this file.  SPACE renders the same blurred
wallpaper to /tmp/lockbg.png and replaces this process with the lock binary.
"""

from __future__ import annotations

import configparser
import math
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

import cairo  # noqa: E402
from PIL import Image, ImageFilter, ImageOps  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_PATH = Path.home() / ".config" / "flipclock-screensaver" / "config.ini"
CACHE_BG = Path("/tmp/flipclock-bg.png")
LOCK_BG = Path("/tmp/lockbg.png")
FALLBACK_BG = Path("/tmp/flipclock-fallback.png")
PID_FILE = Path("/tmp/flipclock-screensaver.pid")
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif"}

DEFAULTS = {
    "wallpaper": str(Path.home() / "Pictures" / "wallpaper.jpg"),
    "blur_sigma": "20",
    "clock_color": "#ffffff",
    "tile_color": "#1a1a1a",
    "tile_radius": "18",
    "lock_command": "swaylock",
}


def load_config() -> dict[str, str]:
    """Read config.ini (with ';' inline comments) over the safe defaults.

    FLIPCLOCK_CONFIG lets the setup app preview unsaved settings.
    """
    path = Path(os.environ.get("FLIPCLOCK_CONFIG", str(CONFIG_PATH)))
    parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
    parser.read_dict({"screensaver": DEFAULTS})
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error) as exc:
        print(f"flipclock: using defaults ({exc})", file=sys.stderr)
    result = dict(DEFAULTS)
    for key in DEFAULTS:
        if parser.has_option("screensaver", key):
            # Older config files put ';' directly after long values; Python's
            # ConfigParser only strips spaced comments, so strip here as well.
            result[key] = parser.get("screensaver", key).split(";", 1)[0].strip()
    return result


def claim_instance() -> bool:
    """Prevent several fullscreen instances from stacking on top of each other."""
    try:
        if PID_FILE.is_file():
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "ignore")
            if pid != os.getpid() and "screensaver.py" in cmdline:
                return False
    except (OSError, ValueError):
        ...
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_instance() -> None:
    try:
        if PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            PID_FILE.unlink(missing_ok=True)
    except OSError:
        ...


# ---------------------------------------------------------------------------
# Wallpaper / blur
# ---------------------------------------------------------------------------


def discover_wallpaper() -> Path | None:
    """Read Hyprland config, then gsettings, then common image folders."""
    for name in ("hypr/hyprland.conf", "hypr/hyprpaper.conf"):
        conf = Path.home() / ".config" / name
        if not conf.is_file():
            continue
        for line in conf.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "wallpaper" not in line.lower() or "=" not in line:
                continue
            for chunk in line.split("=", 1)[1].split(","):
                candidate = Path(os.path.expanduser(chunk.strip().strip("\"'")))
                if candidate.suffix.lower() in IMAGE_SUFFIXES and candidate.is_file():
                    return candidate

    gsettings = shutil.which("gsettings")
    if gsettings:
        import subprocess

        try:
            uri = subprocess.check_output(
                [gsettings, "get", "org.gnome.desktop.background", "picture-uri"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
            ).strip()
            if uri.startswith("file://"):
                candidate = Path(uri[7:].strip("'"))
                if candidate.is_file():
                    return candidate
        except (OSError, subprocess.SubprocessError):
            ...

    for folder in (Path.home() / "Pictures", Path.home() / ".local/share/wallpapers", Path("/usr/share/backgrounds")):
        if not folder.is_dir():
            continue
        try:
            images = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
        except OSError:
            continue
        if images:
            return images[0]
    return None


def generated_fallback() -> Path:
    small = Image.new("RGB", (64, 36))
    for y in range(36):
        for x in range(64):
            small.putpixel((x, y), (int(10 + 28 * x / 63), int(8 + 16 * y / 35), int(30 + 56 * (x + y) / 126)))
    resampling = getattr(Image, "Resampling", Image).BICUBIC
    small.resize((1920, 1080), resampling).save(FALLBACK_BG, format="PNG")
    return FALLBACK_BG


def resolve_wallpaper(cfg: dict[str, str]) -> Path:
    configured = Path(os.path.expanduser(os.path.expandvars(cfg["wallpaper"])))
    if configured.is_file():
        return configured
    return discover_wallpaper() or generated_fallback()


def screen_size() -> tuple[int, int]:
    display = Gdk.Display.get_default()
    monitors = display.get_monitors() if display is not None else None
    monitor = monitors.get_item(0) if monitors is not None else None
    if monitor is not None:
        geometry = monitor.get_geometry()
        return max(1, geometry.width), max(1, geometry.height)
    return 1920, 1080


def blurred_image(source: Path, sigma: float, width: int, height: int, target: Path) -> Image.Image:
    """Fit the wallpaper to the screen, Gaussian-blur it, write a PNG."""
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    with Image.open(source) as raw:
        image = ImageOps.fit(raw.convert("RGB"), (width, height), method=resampling)
    if sigma > 0:
        image = image.filter(ImageFilter.GaussianBlur(radius=sigma))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG")
    return image


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------


def font_family() -> str:
    """Bebas Neue, then Archivo Black, then Sans Bold."""
    try:
        families = {f.get_name().lower() for f in Pango.FontMap.get_default().list_families()}
        if "bebas neue" in families:
            return "Bebas Neue"
        if "archivo black" in families:
            return "Archivo Black"
    except Exception:
        ...
    return "Sans"


def hex_rgb(value: str, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    color = Gdk.RGBA()
    if color.parse(value.strip()):
        return color.red, color.green, color.blue
    return fallback


def rounded_path(cr: cairo.Context, x: float, y: float, w: float, h: float, radius: float) -> None:
    r = max(0.0, min(radius, w / 2, h / 2))
    cr.new_path()
    cr.move_to(x + r, y)
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def lock_command(cfg: dict[str, str]) -> list[str]:
    """Select swaylock on Wayland, i3lock on X11, with a sane fallback."""
    configured = cfg.get("lock_command", "swaylock")
    if os.environ.get("XDG_SESSION_TYPE", "").strip().lower() == "x11":
        preferred = ["i3lock", configured]
    else:
        preferred = ["swaylock", configured]
    chosen = next((cmd for cmd in dict.fromkeys(preferred) if shutil.which(cmd)), preferred[0])
    if chosen == "swaylock":
        return [chosen, "-i", str(LOCK_BG), "--scaling", "fill"]
    return [chosen, "-i", str(LOCK_BG)]


# ---------------------------------------------------------------------------
# Screensaver window
# ---------------------------------------------------------------------------


class FlipClock(Gtk.Window):
    def __init__(self, cfg: dict[str, str]) -> None:
        super().__init__()
        self.cfg = cfg
        self.wallpaper = resolve_wallpaper(cfg)
        self.sigma = max(0.0, min(float(cfg.get("blur_sigma", 20) or 0), 60.0))
        self.digit_color = hex_rgb(cfg["clock_color"], (1.0, 1.0, 1.0))
        self.tile_color = hex_rgb(cfg["tile_color"], (0.102, 0.102, 0.102))
        self.radius = max(0.0, float(cfg.get("tile_radius", 18) or 0))
        self.family = font_family()

        initial = datetime.now()
        self.display_digits = [f"{initial.hour:02d}", f"{initial.minute:02d}", f"{initial.second:02d}"]
        self.previous_digits = list(self.display_digits)
        self.flip_start = [-1.0, -1.0, -1.0]
        self.flip_duration = 0.30

        self.set_title("Flip Clock Screensaver")
        self.set_decorated(False)
        self.set_can_focus(True)
        # GTK4 has no set_keep_above(); fullscreen gives the required stacking.
        if hasattr(self, "set_keep_above"):
            self.set_keep_above(True)

        area = Gtk.DrawingArea()
        area.set_hexpand(True)
        area.set_vexpand(True)
        area.set_draw_func(self.draw)
        self.set_child(area)
        self.area = area

        controller = Gtk.EventControllerKey.new()
        controller.connect("key-pressed", self.on_key)
        self.add_controller(controller)
        self.connect("destroy", lambda *_: release_instance())

        width, height = screen_size()
        blurred_image(self.wallpaper, self.sigma, width, height, CACHE_BG)
        self.background = cairo.ImageSurface.create_from_png(str(CACHE_BG))

        self.fullscreen()
        self.present()
        GLib.idle_add(self.grab_focus)
        GLib.timeout_add(1000, self.tick)
        GLib.timeout_add(16, self.animation_tick)

    def tick(self) -> bool:
        self.area.queue_draw()
        return True

    def animation_tick(self) -> bool:
        """Redraw at ~60fps only while a tile is mid-flip."""
        if any(start >= 0 for start in self.flip_start):
            self.area.queue_draw()
        return True

    def draw(self, _area: Gtk.DrawingArea, cr: cairo.Context, w: int, h: int) -> None:
        cr.set_source_rgb(0, 0, 0)
        cr.paint()

        if self.background is not None:
            sw, sh = self.background.get_width(), self.background.get_height()
            scale = max(w / sw, h / sh)
            cr.save()
            cr.translate((w - sw * scale) / 2, (h - sh * scale) / 2)
            cr.scale(scale, scale)
            cr.set_source_surface(self.background, 0, 0)
            cr.paint()
            cr.restore()

        now = datetime.now()
        targets = (f"{now.hour:02d}", f"{now.minute:02d}", f"{now.second:02d}")
        tile_w = int(w * 0.22)
        tile_h = int(tile_w * 0.75)
        gap = tile_w * 0.15
        total = 3 * tile_w + 2 * gap
        start_x = (w - total) / 2
        start_y = (h - tile_h) / 2
        font_size = int(tile_h * 0.40)
        moment = time.monotonic()

        for index, target in enumerate(targets):
            if target != self.display_digits[index]:
                self.previous_digits[index] = self.display_digits[index]
                self.display_digits[index] = target
                self.flip_start[index] = moment

            start = self.flip_start[index]
            progress = (moment - start) / self.flip_duration if start >= 0 else 1.0
            progress = min(1.0, max(0.0, progress))
            if progress >= 1.0:
                self.flip_start[index] = -1.0
                self.previous_digits[index] = self.display_digits[index]

            self.draw_tile(
                cr,
                start_x + index * (tile_w + gap),
                start_y,
                tile_w,
                tile_h,
                self.display_digits[index],
                self.previous_digits[index],
                progress,
                font_size,
            )

    def draw_digits(self, cr: cairo.Context, x: float, y: float, w: float, h: float, digits: str, font_size: int) -> None:
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription.from_string(f"{self.family} Bold {font_size}"))
        layout.set_text(digits, -1)
        layout.set_alignment(Pango.Alignment.CENTER)
        text_w, text_h = layout.get_pixel_size()
        cr.set_source_rgb(*self.digit_color)
        cr.move_to(x + (w - text_w) / 2, y + (h - text_h) / 2)
        PangoCairo.show_layout(cr, layout)

    def draw_tile(
        self,
        cr: cairo.Context,
        x: float,
        y: float,
        w: float,
        h: float,
        digits: str,
        previous: str,
        progress: float,
        font_size: int,
    ) -> None:
        middle = y + h / 2
        animating = progress < 1.0

        rounded_path(cr, x, y, w, h, self.radius)
        cr.set_source_rgb(*self.tile_color)
        cr.fill()

        cr.save()
        rounded_path(cr, x, y, w, h, self.radius)
        cr.clip()

        # The top half already shows the incoming digit while the old flap
        # folds away; the bottom half keeps the outgoing digit until it lands.
        cr.save()
        cr.rectangle(x, y, w, h / 2)
        cr.clip()
        self.draw_digits(cr, x, y, w, h, digits, font_size)
        cr.restore()

        cr.save()
        cr.rectangle(x, middle, w, h / 2)
        cr.clip()
        self.draw_digits(cr, x, y, w, h, previous if animating else digits, font_size)
        cr.restore()

        if animating:
            first_half = progress < 0.5
            scale = 1.0 - 2.0 * progress if first_half else 2.0 * progress - 1.0
            scale = max(0.0, min(1.0, scale))

            cr.save()
            if first_half:
                cr.rectangle(x, y, w, h / 2)
            else:
                cr.rectangle(x, middle, w, h / 2)
            cr.clip()

            # Squash the flap towards the seam to emulate a hinge in 2D.
            cr.translate(0, middle)
            cr.scale(1.0, scale)
            cr.translate(0, -middle)

            cr.rectangle(x, y if first_half else middle, w, h / 2)
            flap_color = tuple(min(1.0, channel + 0.07) for channel in self.tile_color)
            cr.set_source_rgb(*flap_color)
            cr.fill()
            self.draw_digits(cr, x, y, w, h, previous if first_half else digits, font_size)
            cr.restore()

        cr.restore()

        # Exact vertical-centre split-flap seam, 2px, soft white highlight.
        cr.save()
        rounded_path(cr, x, y, w, h, self.radius)
        cr.clip()
        cr.set_source_rgba(1, 1, 1, 0.15)
        cr.set_line_width(2.0)
        cr.move_to(x, middle)
        cr.line_to(x + w, middle)
        cr.stroke()
        cr.restore()

    def on_key(self, _controller: Gtk.EventControllerKey, keyval: int, _code: int, _state: Gdk.ModifierType) -> bool:
        if keyval == Gdk.KEY_space:
            self.lock_now()
            return True
        # Every other key is deliberately ignored.
        return True

    def lock_now(self) -> None:
        width, height = screen_size()
        blurred_image(self.wallpaper, self.sigma, width, height, LOCK_BG)
        command = lock_command(self.cfg)
        release_instance()
        self.close()
        try:
            os.execvp(command[0], command)
        except OSError as exc:
            print(f"flipclock: unable to start {command[0]}: {exc}", file=sys.stderr)


def main() -> int:
    if not claim_instance():
        print("flipclock: already running", file=sys.stderr)
        return 0
    # Stable WM_CLASS so the launcher/dock can match this window to its .desktop
    # entry (without this GTK reports the generic "GTK Application").
    GLib.set_prgname("flipclock")
    GLib.set_application_name("Flip Clock Screensaver")
    Gtk.init()
    loop = GLib.MainLoop()
    window = FlipClock(load_config())
    window.connect("destroy", lambda *_: loop.quit())
    window.connect("close-request", lambda *_: loop.quit())
    loop.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
