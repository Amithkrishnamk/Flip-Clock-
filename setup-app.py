#!/usr/bin/env python3
"""GTK4 / libadwaita setup application for the flip-clock screensaver."""

from __future__ import annotations

import configparser
import math
import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")

import cairo  # noqa: E402
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from PIL import Image, ImageFilter, ImageOps  # noqa: E402

CONFIG_PATH = Path.home() / ".config" / "flipclock-screensaver" / "config.ini"
PREVIEW_TMP = Path("/tmp/flipclock-setup-preview.png")
PREVIEW_CONFIG = Path("/tmp/flipclock-preview.ini")
SCREENSAVER_PID = Path("/tmp/flipclock-screensaver.pid")
SCRIPT_PATH = Path(__file__).resolve().parent / "screensaver.py"

DEFAULTS = {
    "wallpaper": str(Path.home() / "Pictures" / "wallpaper.jpg"),
    "blur_sigma": "20",
    "clock_color": "#ffffff",
    "tile_color": "#1a1a1a",
    "tile_radius": "18",
    "tile_width": "22",
    "tile_height": "29",
    "lock_command": "swaylock",
}

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".avif"}


def load_config() -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
    parser.read_dict({"screensaver": DEFAULTS})
    try:
        parser.read(CONFIG_PATH, encoding="utf-8")
    except (OSError, configparser.Error):
        ...
    cfg = dict(DEFAULTS)
    for key in DEFAULTS:
        if parser.has_option("screensaver", key):
            # configparser only strips ';' comments when they are preceded by
            # whitespace; older config files wrote long paths without a space.
            cfg[key] = parser.get("screensaver", key).split(";", 1)[0].strip()
    return cfg


def config_text(cfg: dict[str, str]) -> str:
    """Render config text. Always put whitespace before ';' so it parses."""
    def line(key: str, value: str, comment: str) -> str:
        return f"{key} = {value}".ljust(44) + f" ; {comment}"

    return "\n".join(
        [
            "[screensaver]",
            line("wallpaper", cfg["wallpaper"], "wallpaper image path"),
            line("blur_sigma", cfg["blur_sigma"], "Gaussian blur radius 0-60"),
            line("clock_color", cfg["clock_color"], "digit colour"),
            line("tile_color", cfg["tile_color"], "tile colour"),
            line("tile_radius", cfg["tile_radius"], "corner radius 0-40"),
            line("tile_width", cfg["tile_width"], "tile width, percent of screen width"),
            line("tile_height", cfg["tile_height"], "tile height, percent of screen height"),
            line("lock_command", cfg["lock_command"], "swaylock or i3lock"),
            "",
            "[hotkey]",
            "trigger = ctrl+backslash",
            "",
        ]
    )


def write_config(cfg: dict[str, str]) -> None:
    """Write config.ini; inline comments start with ';' so #hex colours survive."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config_text(cfg), encoding="utf-8")


def stop_screensaver() -> None:
    """Stop any clock instance so the next launch reads the current settings."""
    subprocess.run(
        ["pkill", "-f", "[s]creensaver.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    SCREENSAVER_PID.unlink(missing_ok=True)


def session_lock() -> str:
    """Wayland -> swaylock, X11 -> i3lock."""
    return "i3lock" if os.environ.get("XDG_SESSION_TYPE", "").strip().lower() == "x11" else "swaylock"


def rgba_from_hex(value: str) -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    if not rgba.parse(value.strip()):
        rgba.parse("#ffffff")
    return rgba


def rgba_to_hex(rgba: Gdk.RGBA) -> str:
    return "#{:02x}{:02x}{:02x}".format(
        int(round(rgba.red * 255)), int(round(rgba.green * 255)), int(round(rgba.blue * 255))
    )


def rgb_from_hex(value: str, fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    rgba = Gdk.RGBA()
    if rgba.parse(value.strip()):
        return rgba.red, rgba.green, rgba.blue
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


def preview_font_family() -> str:
    try:
        families = {f.get_name().lower() for f in Pango.FontMap.get_default().list_families()}
        if "bebas neue" in families:
            return "Bebas Neue"
        if "archivo black" in families:
            return "Archivo Black"
    except Exception:
        ...
    return "Sans"


def dependency_report() -> list[tuple[str, bool, str]]:
    report: list[tuple[str, bool, str]] = []
    python = shutil.which("python3")
    report.append(("python3", bool(python), python or "not found"))
    try:
        import PIL

        report.append(("python3-pillow", True, f"Pillow {PIL.__version__}"))
    except ImportError:
        report.append(("python3-pillow", False, "module not found"))
    for name in ("swaylock", "i3lock", "sxhkd"):
        found = shutil.which(name)
        report.append((name, bool(found), found or "not found"))
    try:
        import gi

        gi.require_version("Adw", "1")
        from gi.repository import Adw as _Adw

        report.append(("libadwaita", True, "importable via PyGObject"))
    except Exception as exc:
        report.append(("libadwaita", False, str(exc)))
    try:
        fonts = subprocess.run(
            ["fc-list", ":", "family"], capture_output=True, text=True, timeout=5
        ).stdout.lower()
        found = "bebas neue" in fonts or "archivo black" in fonts
        report.append(("Bebas Neue font", found, "installed" if found else "font not found"))
    except (OSError, subprocess.SubprocessError) as exc:
        report.append(("Bebas Neue font", False, str(exc)))
    return report


def render_blur_preview(source: Path, sigma: float, destination: Path) -> None:
    """Worker thread: produce a 300x180 blurred preview image."""
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    with Image.open(source) as raw:
        image = ImageOps.fit(raw.convert("RGB"), (300, 180), method=resampling)
    if sigma > 0:
        image = image.filter(ImageFilter.GaussianBlur(radius=sigma))
    image.save(destination, format="PNG")


class SetupApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.flipclock.setup", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.cfg = load_config()
        self.window: Adw.ApplicationWindow | None = None
        self.blur_generation = 0
        self.preview_process: subprocess.Popen | None = None

    def do_activate(self) -> None:
        window = Adw.ApplicationWindow(
            application=self,
            title="Flip Clock Screensaver — Setup",
            default_width=720,
            default_height=900,
        )
        self.window = window

        overlay = Adw.ToastOverlay()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Flip Clock Screensaver", subtitle="Setup"))
        root.append(header)

        page = Adw.PreferencesPage()
        page.add(self.wallpaper_group())
        page.add(self.appearance_group())
        page.add(self.lock_group())
        page.add(self.hotkey_group())
        page.add(self.buttons_group())
        root.append(page)

        overlay.set_child(root)
        window.set_content(overlay)
        window.present()
        self.load_thumbnail()
        self.start_blur_worker()
        GLib.timeout_add(1000, self.tick_clock_preview)

    # -- group builders ----------------------------------------------------

    def wallpaper_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Wallpaper", description="Image behind the clock and on the lock screen.")
        row = Adw.ActionRow(title="Wallpaper Image", subtitle=self.cfg["wallpaper"])
        button = Gtk.Button(label="Choose…")
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", self.choose_wallpaper)
        row.add_suffix(button)
        group.add(row)
        self.wallpaper_row = row

        self.thumbnail = Gtk.Picture()
        self.thumbnail.set_size_request(200, 120)
        self.thumbnail.set_content_fit(Gtk.ContentFit.FILL)
        frame = Gtk.Frame()
        frame.set_child(self.thumbnail)
        frame.set_halign(Gtk.Align.CENTER)
        frame.set_margin_top(6)
        frame.set_margin_bottom(12)
        group.add(frame)
        return group

    def appearance_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Appearance", description="Blur, colours and tile geometry.")

        blur_row = Adw.ActionRow(title="Blur Amount", subtitle="Gaussian blur sigma")
        blur = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 60, 1)
        blur.set_value(float(self.cfg.get("blur_sigma", 20) or 0))
        blur.set_draw_value(False)
        blur.set_hexpand(True)
        blur.set_size_request(220, -1)
        blur.set_valign(Gtk.Align.CENTER)
        self.blur_value = Gtk.Label(label=str(int(blur.get_value())))
        self.blur_value.set_width_chars(3)
        blur_row.add_suffix(blur)
        blur_row.add_suffix(self.blur_value)
        blur.connect("value-changed", self.on_blur_changed)
        group.add(blur_row)

        self.blur_picture = Gtk.Picture()
        self.blur_picture.set_size_request(300, 180)
        self.blur_picture.set_content_fit(Gtk.ContentFit.FILL)
        blur_frame = Gtk.Frame()
        blur_frame.set_child(self.blur_picture)
        blur_frame.set_halign(Gtk.Align.CENTER)
        blur_frame.set_margin_top(6)
        blur_frame.set_margin_bottom(12)
        group.add(blur_frame)

        # Live miniature of the clock: updates with every setting and ticks.
        self.clock_preview = Gtk.DrawingArea()
        self.clock_preview.set_size_request(300, 180)
        self.clock_preview.set_hexpand(True)
        self.clock_preview.set_draw_func(self.draw_clock_preview)
        clock_frame = Gtk.Frame()
        clock_frame.set_child(self.clock_preview)
        clock_frame.set_halign(Gtk.Align.CENTER)
        clock_frame.set_margin_top(6)
        clock_frame.set_margin_bottom(12)
        group.add(clock_frame)

        clock_row = Adw.ActionRow(title="Clock Color", subtitle="Digits")
        clock_button = Gtk.ColorButton.new_with_rgba(rgba_from_hex(self.cfg["clock_color"]))
        clock_button.set_valign(Gtk.Align.CENTER)
        clock_button.connect("color-set", self.on_clock_color)
        clock_row.add_suffix(clock_button)
        group.add(clock_row)

        tile_row = Adw.ActionRow(title="Tile Color", subtitle="Tile background")
        tile_button = Gtk.ColorButton.new_with_rgba(rgba_from_hex(self.cfg["tile_color"]))
        tile_button.set_valign(Gtk.Align.CENTER)
        tile_button.connect("color-set", self.on_tile_color)
        tile_row.add_suffix(tile_button)
        group.add(tile_row)

        radius_row = Adw.ActionRow(title="Corner Radius", subtitle="Tile corner radius, pixels")
        radius = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 40, 1)
        radius.set_value(float(self.cfg.get("tile_radius", 18) or 0))
        radius.set_draw_value(False)
        radius.set_hexpand(True)
        radius.set_size_request(220, -1)
        radius.set_valign(Gtk.Align.CENTER)
        self.radius_value = Gtk.Label(label=str(int(radius.get_value())))
        self.radius_value.set_width_chars(3)
        radius_row.add_suffix(radius)
        radius_row.add_suffix(self.radius_value)
        radius.connect("value-changed", self.on_radius_changed)
        group.add(radius_row)

        width_row = Adw.ActionRow(title="Tile Width", subtitle="Percent of screen width (10-30)")
        width = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 30, 1)
        width.set_value(float(self.cfg.get("tile_width", 22) or 22))
        width.set_draw_value(False)
        width.set_hexpand(True)
        width.set_size_request(220, -1)
        width.set_valign(Gtk.Align.CENTER)
        self.width_value = Gtk.Label(label=str(int(width.get_value())))
        self.width_value.set_width_chars(3)
        width_row.add_suffix(width)
        width_row.add_suffix(self.width_value)
        width.connect("value-changed", self.on_width_changed)
        group.add(width_row)

        height_row = Adw.ActionRow(title="Tile Height", subtitle="Percent of screen height (10-60)")
        height = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 60, 1)
        height.set_value(float(self.cfg.get("tile_height", 29) or 29))
        height.set_draw_value(False)
        height.set_hexpand(True)
        height.set_size_request(220, -1)
        height.set_valign(Gtk.Align.CENTER)
        self.height_value = Gtk.Label(label=str(int(height.get_value())))
        self.height_value.set_width_chars(3)
        height_row.add_suffix(height)
        height_row.add_suffix(self.height_value)
        height.connect("value-changed", self.on_height_changed)
        group.add(height_row)
        return group

    def lock_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Lock Screen", description="Selected from the current session type.")
        row = Adw.ComboRow(
            title="Lock Command",
            subtitle="Used when SPACE is pressed",
            model=Gtk.StringList.new(["swaylock", "i3lock"]),
        )
        row.set_selected(0 if session_lock() == "swaylock" else 1)
        self.cfg["lock_command"] = session_lock()
        row.connect("notify::selected", self.on_lock_changed)
        group.add(row)
        return group

    def hotkey_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Hotkey",
            description="Edit ~/.config/hypr/user.lua (Ryoku), hyprland.conf, or ~/.config/sxhkd/sxhkdrc to change",
        )
        row = Adw.ActionRow(title="Activate Screensaver", subtitle="Ctrl + \\")
        group.add(row)
        return group

    def buttons_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Actions")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_homogeneous(True)
        box.set_margin_top(6)
        box.set_margin_bottom(14)
        box.set_margin_start(12)
        box.set_margin_end(12)

        check = Gtk.Button(label="Check Dependencies")
        check.connect("clicked", self.on_check_dependencies)
        preview = Gtk.Button(label="Preview")
        preview.connect("clicked", self.on_preview)
        save = Gtk.Button(label="Save & Apply")
        save.add_css_class("suggested-action")
        save.connect("clicked", self.on_save)

        box.append(check)
        box.append(preview)
        box.append(save)
        group.add(box)
        return group

    # -- helpers -----------------------------------------------------------

    def toast(self, message: str) -> None:
        overlay = self.window.get_content() if self.window else None
        if isinstance(overlay, Adw.ToastOverlay):
            overlay.add_toast(Adw.Toast.new(message))

    def wallpaper_path(self) -> Path | None:
        candidate = Path(os.path.expanduser(os.path.expandvars(self.cfg["wallpaper"])))
        return candidate if candidate.is_file() else None

    def load_thumbnail(self) -> None:
        source = self.wallpaper_path()
        if source is not None:
            self.thumbnail.set_filename(str(source))

    def start_blur_worker(self) -> None:
        source = self.wallpaper_path()
        if source is None:
            return
        self.blur_generation += 1
        generation = self.blur_generation
        sigma = float(self.cfg.get("blur_sigma", 20) or 0)

        def work() -> None:
            try:
                render_blur_preview(source, sigma, PREVIEW_TMP)
            except OSError as exc:
                print(f"flipclock: blur preview failed: {exc}", file=sys.stderr)
                return
            GLib.idle_add(self.apply_blur_preview, generation)

        threading.Thread(target=work, daemon=True).start()

    def apply_blur_preview(self, generation: int) -> bool:
        if generation != self.blur_generation or not PREVIEW_TMP.is_file():
            return False
        texture = Gdk.Texture.new_from_filename(str(PREVIEW_TMP))
        self.blur_picture.set_paintable(texture)
        self.clock_preview.queue_draw()
        return False

    def tick_clock_preview(self) -> bool:
        self.clock_preview.queue_draw()
        return True

    def draw_clock_preview(self, _area: Gtk.DrawingArea, cr: cairo.Context, w: int, h: int) -> None:
        """Miniature of the fullscreen clock using the current UI settings."""
        cr.set_source_rgb(0.05, 0.05, 0.06)
        cr.paint()

        try:
            background = cairo.ImageSurface.create_from_png(str(PREVIEW_TMP))
        except Exception:
            background = None
        if background is not None:
            sw, sh = background.get_width(), background.get_height()
            scale = max(w / sw, h / sh)
            cr.save()
            cr.translate((w - sw * scale) / 2, (h - sh * scale) / 2)
            cr.scale(scale, scale)
            cr.set_source_surface(background, 0, 0)
            cr.paint()
            cr.restore()

        now = datetime.now()
        digits = (f"{now.hour:02d}", f"{now.minute:02d}")
        width_ratio = min(30.0, max(10.0, float(self.cfg.get("tile_width", 22) or 22))) / 100.0
        height_ratio = min(60.0, max(10.0, float(self.cfg.get("tile_height", 29) or 29))) / 100.0
        tile_w = max(18, int(w * width_ratio))
        tile_h = max(14, int(h * height_ratio))
        gap = tile_w * 0.15
        colon_w = tile_w * 0.32
        total = 2 * tile_w + colon_w + 2 * gap
        start_x = (w - total) / 2
        start_y = (h - tile_h) / 2
        radius = max(0.0, min(float(self.cfg.get("tile_radius", 18) or 0), tile_w / 2, tile_h / 2))
        font_size = max(8, int(tile_h * 0.40))
        tile_color = rgb_from_hex(self.cfg["tile_color"], (0.102, 0.102, 0.102))
        digit_color = rgb_from_hex(self.cfg["clock_color"], (1.0, 1.0, 1.0))
        family = preview_font_family()

        def draw_text(text: str, x: float, width: float) -> None:
            layout = PangoCairo.create_layout(cr)
            layout.set_font_description(Pango.FontDescription.from_string(f"{family} Bold {font_size}"))
            layout.set_text(text, -1)
            layout.set_alignment(Pango.Alignment.CENTER)
            text_w, text_h = layout.get_pixel_size()
            cr.set_source_rgb(*digit_color)
            cr.move_to(x + (width - text_w) / 2, start_y + (tile_h - text_h) / 2)
            PangoCairo.show_layout(cr, layout)

        for index, text in enumerate(digits):
            x = start_x + index * (tile_w + colon_w + 2 * gap)
            y = start_y
            rounded_path(cr, x, y, tile_w, tile_h, radius)
            cr.set_source_rgb(*tile_color)
            cr.fill()

            draw_text(text, x, tile_w)

            cr.save()
            rounded_path(cr, x, y, tile_w, tile_h, radius)
            cr.clip()
            cr.set_source_rgba(1, 1, 1, 0.15)
            cr.set_line_width(2.0)
            cr.move_to(x, y + tile_h / 2)
            cr.line_to(x + tile_w, y + tile_h / 2)
            cr.stroke()
            cr.restore()

        draw_text(":", start_x + tile_w + gap, colon_w)

    # -- callbacks ---------------------------------------------------------

    def choose_wallpaper(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserDialog(
            title="Choose wallpaper",
            parent=self.window,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Open", Gtk.ResponseType.ACCEPT)
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Images")
        file_filter.add_pixbuf_formats()
        dialog.add_filter(file_filter)
        dialog.connect("response", self.wallpaper_selected)
        dialog.show()

    def wallpaper_selected(self, dialog: Gtk.FileChooserDialog, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            path = file.get_path() if file else None
            if path:
                self.cfg["wallpaper"] = path
                self.wallpaper_row.set_subtitle(path)
                self.thumbnail.set_filename(path)
                self.start_blur_worker()
                self.clock_preview.queue_draw()
        dialog.destroy()

    def on_blur_changed(self, scale: Gtk.Scale) -> None:
        self.cfg["blur_sigma"] = str(int(scale.get_value()))
        self.blur_value.set_label(self.cfg["blur_sigma"])
        self.start_blur_worker()

    def on_radius_changed(self, scale: Gtk.Scale) -> None:
        self.cfg["tile_radius"] = str(int(scale.get_value()))
        self.radius_value.set_label(self.cfg["tile_radius"])
        self.clock_preview.queue_draw()

    def on_width_changed(self, scale: Gtk.Scale) -> None:
        self.cfg["tile_width"] = str(int(scale.get_value()))
        self.width_value.set_label(self.cfg["tile_width"])
        self.clock_preview.queue_draw()

    def on_height_changed(self, scale: Gtk.Scale) -> None:
        self.cfg["tile_height"] = str(int(scale.get_value()))
        self.height_value.set_label(self.cfg["tile_height"])
        self.clock_preview.queue_draw()

    def on_clock_color(self, button: Gtk.ColorButton) -> None:
        self.cfg["clock_color"] = rgba_to_hex(button.get_rgba())
        self.clock_preview.queue_draw()

    def on_tile_color(self, button: Gtk.ColorButton) -> None:
        self.cfg["tile_color"] = rgba_to_hex(button.get_rgba())
        self.clock_preview.queue_draw()

    def on_lock_changed(self, row: Adw.ComboRow, _pspec: object) -> None:
        self.cfg["lock_command"] = "swaylock" if row.get_selected() == 0 else "i3lock"

    def on_check_dependencies(self, _button: Gtk.Button) -> None:
        dialog = Adw.MessageDialog(
            transient_for=self.window,
            heading="Dependency Check",
            body="Required components for the flip-clock screensaver",
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for name, ok, detail in dependency_report():
            label = Gtk.Label()
            mark = "✓" if ok else "✗"
            color = "green" if ok else "red"
            label.set_markup(f'<span foreground="{color}" weight="bold">{mark}</span> {name} — {detail}')
            label.set_xalign(0)
            box.append(label)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(box)
        scrolled.set_min_content_height(280)
        dialog.set_extra_child(scrolled)
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        dialog.set_close_response("close")
        dialog.present()

    def on_preview(self, _button: Gtk.Button) -> None:
        if self.preview_process is not None and self.preview_process.poll() is None:
            self.preview_process.terminate()
        stop_screensaver()
        # Render the unsaved settings from the UI, not the last saved config.
        PREVIEW_CONFIG.write_text(config_text(self.cfg), encoding="utf-8")
        environment = dict(os.environ)
        environment["FLIPCLOCK_CONFIG"] = str(PREVIEW_CONFIG)
        self.preview_process = subprocess.Popen(
            [sys.executable, str(SCRIPT_PATH)],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        def stop() -> bool:
            if self.preview_process is not None and self.preview_process.poll() is None:
                self.preview_process.terminate()
            self.preview_process = None
            return False

        GLib.timeout_add(5000, stop)
        self.toast("Preview running for 5 seconds")

    def on_save(self, _button: Gtk.Button) -> None:
        try:
            write_config(self.cfg)
        except OSError as exc:
            self.toast(f"Could not write config: {exc}")
            return
        if self.preview_process is not None and self.preview_process.poll() is None:
            self.preview_process.terminate()
        # A clock opened from the launcher/hotkey must not keep the old image.
        stop_screensaver()
        try:
            result = subprocess.run(
                ["systemctl", "--user", "restart", "flipclock-daemon"],
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            self.toast(f"Saved config; daemon restart failed: {exc}")
            return
        if result.returncode == 0:
            self.toast("Configuration saved and daemon restarted")
        else:
            self.toast("Configuration saved; daemon restart failed")


def main() -> int:
    app = SetupApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
