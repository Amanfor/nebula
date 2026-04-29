import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gtk, Gdk, GLib, GtkLayerShell
import cairo as Cairo
import subprocess
import json

# ── css ───────────────────────────────────────────────────
CSS = """
* { font-family: monospace; }

.track-title {
    color: rgba(255,255,255,0.75);
    font-size: 11px;
    letter-spacing: 1px;
}
.track-artist {
    color: rgba(255,255,255,0.35);
    font-size: 9px;
    letter-spacing: 2px;
}
.ctrl-btn {
    background: transparent;
    border: none;
    color: rgba(255,255,255,0.40);
    font-size: 14px;
    padding: 0 6px;
    min-width: 24px;
    min-height: 24px;
}
.ctrl-btn:hover { color: rgba(255,255,255,0.90); }
.ctrl-btn.play  { color: rgba(255,255,255,0.70); font-size: 16px; }
.ctrl-btn.play:hover { color: rgba(255,255,255,1.0); }
.time-label {
    color: rgba(255,255,255,0.22);
    font-size: 9px;
    letter-spacing: 1px;
    margin: 0 4px;
}
"""

# ── helpers ───────────────────────────────────────────────
def playerctl(args):
    try:
        r = subprocess.run(["playerctl"] + args,
                           capture_output=True, text=True, timeout=0.5)
        return r.stdout.strip()
    except Exception:
        return ""

def fmt_time(s_str):
    try:
        s = int(float(s_str))
        return f"{s // 60}:{s % 60:02d}"
    except Exception:
        return "0:00"

def fmt_us(us_str):
    try:
        s = int(us_str) // 1_000_000
        return f"{s // 60}:{s % 60:02d}"
    except Exception:
        return "0:00"

def _clear_bg(widget, ctx):
    ctx.set_operator(Cairo.OPERATOR_SOURCE)
    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()
    ctx.set_operator(Cairo.OPERATOR_OVER)
    return False


# ══════════════════════════════════════════════════════════
# HYPR IPC — shared pattern (same as NebulaShell)
# ══════════════════════════════════════════════════════════

class HyprIPC:
    def __init__(self, windows):
        self._windows = windows
        self._blocked = False

    def start(self):
        GLib.timeout_add(500, self._poll)

    def _poll(self):
        try:
            result = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True, text=True, timeout=0.4)
            data     = json.loads(result.stdout or "{}")
            app_open = bool(data.get("class", "").strip())
        except Exception:
            app_open = False
        self._set_blocked(app_open)
        return True

    def _set_blocked(self, block):
        if block == self._blocked:
            return
        self._blocked = block
        for win in self._windows:
            if block:
                win.hide()
            else:
                win.show_all()


# ══════════════════════════════════════════════════════════
# MEDIA WINDOW
# ══════════════════════════════════════════════════════════

class MediaWindow(Gtk.Window):
    POLL_MS = 2000

    def __init__(self):
        super().__init__()
        self.set_decorated(False)
        self.set_app_paintable(True)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.connect("draw", _clear_bg)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._build_ui()
        self._refresh()
        GLib.timeout_add(self.POLL_MS, self._refresh)

    def _show(self):
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, 28)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        self.show_all()

    def _build_ui(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        outer.set_margin_start(8)
        outer.set_margin_end(8)
        outer.set_margin_top(4)
        outer.set_margin_bottom(4)

        self._title_lbl = Gtk.Label()
        self._title_lbl.get_style_context().add_class("track-title")
        self._title_lbl.set_ellipsize(3)
        self._title_lbl.set_max_width_chars(28)
        self._title_lbl.set_halign(Gtk.Align.CENTER)

        self._artist_lbl = Gtk.Label()
        self._artist_lbl.get_style_context().add_class("track-artist")
        self._artist_lbl.set_halign(Gtk.Align.CENTER)

        outer.pack_start(self._title_lbl,  False, False, 0)
        outer.pack_start(self._artist_lbl, False, False, 0)

        ctrl = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        ctrl.set_halign(Gtk.Align.CENTER)

        def btn(label, cls, cb):
            b = Gtk.Button(label=label)
            b.get_style_context().add_class("ctrl-btn")
            if cls:
                b.get_style_context().add_class(cls)
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", cb)
            return b

        self._prev_btn = btn("⏮", None,   lambda *_: playerctl(["previous"]))
        self._play_btn = btn("▶",  "play", self._toggle_play)
        self._next_btn = btn("⏭", None,   lambda *_: playerctl(["next"]))

        self._time_lbl = Gtk.Label(label="0:00")
        self._time_lbl.get_style_context().add_class("time-label")

        for w in (self._prev_btn, self._play_btn,
                  self._next_btn, self._time_lbl):
            ctrl.pack_start(w, False, False, 0)

        outer.pack_start(ctrl, False, False, 0)
        self.add(outer)

    def _toggle_play(self, *_):
        playerctl(["play-pause"])
        GLib.timeout_add(200, self._refresh)

    def _refresh(self):
        title  = playerctl(["metadata", "title"])  or ""
        artist = playerctl(["metadata", "artist"]) or ""
        status = playerctl(["status"])             or "Stopped"
        pos    = playerctl(["position"])           or "0"
        length = playerctl(["metadata", "mpris:length"]) or "0"

        self._title_lbl.set_text(title[:32] if title else "—")
        self._artist_lbl.set_text(artist)
        self._play_btn.set_label("⏸" if status == "Playing" else "▶")
        self._time_lbl.set_text(f"{fmt_time(pos)} / {fmt_us(length)}")
        return True


# ── entry point ───────────────────────────────────────────

if __name__ == "__main__":
    win = MediaWindow()
    win.connect("destroy", Gtk.main_quit)
    win._show()

    ipc = HyprIPC([win])
    ipc.start()

    Gtk.main()