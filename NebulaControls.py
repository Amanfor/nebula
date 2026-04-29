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

.ctrl-col {
    background: transparent;
}

.icon-lbl {
    color: rgba(255,255,255,0.40);
    font-size: 18px;
    padding: 2px 0;
}
.icon-lbl:hover { color: rgba(255,255,255,0.90); }
.icon-lbl.on    { color: rgba(255,255,255,0.80); }

.val-lbl {
    color: rgba(255,255,255,0.22);
    font-size: 8px;
    letter-spacing: 1px;
}

.divider {
    background: rgba(255,255,255,0.08);
    min-height: 1px;
    margin: 4px 0;
}
"""

# ── system helpers ────────────────────────────────────────

def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True,
                              text=True, timeout=0.8).stdout.strip()
    except Exception:
        return ""

def get_volume():
    out = run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    try:
        muted = "[MUTED]" in out
        val   = int(float(out.split()[1]) * 100)
        return val, muted
    except Exception:
        return 50, False

def set_volume(v):
    v = max(0, min(100, v))
    subprocess.Popen(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@",
                      f"{v / 100:.2f}"])

def toggle_mute():
    subprocess.Popen(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"])

def get_brightness():
    cur = run(["brightnessctl", "get"])
    mx  = run(["brightnessctl", "max"])
    try:
        return int(int(cur) / int(mx) * 100)
    except Exception:
        return 50

def set_brightness(v):
    v = max(1, min(100, v))
    subprocess.Popen(["brightnessctl", "set", f"{v}%"])

def get_wifi():
    return run(["nmcli", "-t", "-f", "WIFI", "radio"]).strip() == "enabled"

def toggle_wifi():
    subprocess.Popen(["nmcli", "radio", "wifi",
                      "off" if get_wifi() else "on"])

def get_bluetooth():
    return "Powered: yes" in run(["bluetoothctl", "show"])

def toggle_bluetooth():
    subprocess.Popen(["bluetoothctl", "power",
                      "off" if get_bluetooth() else "on"])

def _clear_bg(widget, ctx):
    ctx.set_operator(Cairo.OPERATOR_SOURCE)
    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()
    ctx.set_operator(Cairo.OPERATOR_OVER)
    return False


# ══════════════════════════════════════════════════════════
# HYPR IPC — same pattern as NebulaShell
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
# SCROLLABLE ICON — label that responds to scroll wheel
# ══════════════════════════════════════════════════════════

class ScrollIcon(Gtk.EventBox):
    """
    An icon label + value label stacked vertically.
    Scroll up/down → calls on_scroll(delta).
    Click          → calls on_click().
    """
    def __init__(self, icon, on_scroll, on_click=None):
        super().__init__()
        self._on_scroll = on_scroll
        self._on_click  = on_click

        self.add_events(
            Gdk.EventMask.SCROLL_MASK |
            Gdk.EventMask.SMOOTH_SCROLL_MASK |
            Gdk.EventMask.BUTTON_PRESS_MASK)

        self.connect("scroll-event",       self._scroll)
        self.connect("button-press-event", self._click)

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        col.set_halign(Gtk.Align.CENTER)

        self._icon_lbl = Gtk.Label(label=icon)
        self._icon_lbl.get_style_context().add_class("icon-lbl")

        self._val_lbl = Gtk.Label(label="")
        self._val_lbl.get_style_context().add_class("val-lbl")

        col.pack_start(self._icon_lbl, False, False, 0)
        col.pack_start(self._val_lbl,  False, False, 0)
        self.add(col)

    def set_icon(self, icon):
        self._icon_lbl.set_text(icon)

    def set_value(self, text):
        self._val_lbl.set_text(text)

    def set_active(self, on):
        ctx = self._icon_lbl.get_style_context()
        if on:
            ctx.add_class("on")
        else:
            ctx.remove_class("on")

    def _scroll(self, widget, event):
        # smooth scroll or discrete
        if event.direction == Gdk.ScrollDirection.UP:
            self._on_scroll(+5)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self._on_scroll(-5)
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            _, dy = event.get_scroll_deltas()
            self._on_scroll(int(-dy * 5))
        return True

    def _click(self, widget, event):
        if self._on_click:
            self._on_click()
        return True


# ══════════════════════════════════════════════════════════
# CONTROLS WINDOW — right side vertical strip
# ══════════════════════════════════════════════════════════

class ControlsWindow(Gtk.Window):
    POLL_MS = 3000

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
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT,  True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP,    True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 20)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        self.show_all()

    def _build_ui(self):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        col.set_valign(Gtk.Align.CENTER)
        col.set_halign(Gtk.Align.CENTER)
        col.set_margin_start(4)
        col.set_margin_end(4)
        col.get_style_context().add_class("ctrl-col")

        # ── volume — scroll to adjust, click to mute ──────
        self._vol_icon = ScrollIcon(
            "󰕾",
            on_scroll=self._scroll_volume,
            on_click=self._click_mute,
        )
        col.pack_start(self._vol_icon, False, False, 0)

        # ── brightness — scroll to adjust ─────────────────
        self._bright_icon = ScrollIcon(
            "󰃠",
            on_scroll=self._scroll_brightness,
        )
        col.pack_start(self._bright_icon, False, False, 0)

        # divider
        div = Gtk.Box()
        div.get_style_context().add_class("divider")
        div.set_size_request(18, 1)
        col.pack_start(div, False, False, 0)

        # ── wifi — click to toggle ─────────────────────────
        self._wifi_icon = ScrollIcon(
            "󰤨",
            on_scroll=lambda d: None,
            on_click=self._click_wifi,
        )
        col.pack_start(self._wifi_icon, False, False, 0)

        # ── bluetooth — click to toggle ───────────────────
        self._bt_icon = ScrollIcon(
            "󰂯",
            on_scroll=lambda d: None,
            on_click=self._click_bt,
        )
        col.pack_start(self._bt_icon, False, False, 0)

        self.add(col)

    # ── scroll callbacks ──────────────────────────────────
    def _scroll_volume(self, delta):
        vol, _ = get_volume()
        set_volume(vol + delta)
        GLib.timeout_add(80, self._refresh)

    def _scroll_brightness(self, delta):
        br = get_brightness()
        set_brightness(br + delta)
        GLib.timeout_add(80, self._refresh)

    # ── click callbacks ───────────────────────────────────
    def _click_mute(self):
        toggle_mute()
        GLib.timeout_add(120, self._refresh)

    def _click_wifi(self):
        toggle_wifi()
        GLib.timeout_add(400, self._refresh)

    def _click_bt(self):
        toggle_bluetooth()
        GLib.timeout_add(400, self._refresh)

    # ── state refresh ─────────────────────────────────────
    def _refresh(self):
        vol, muted = get_volume()
        self._vol_icon.set_icon("󰖁" if muted else "󰕾")
        self._vol_icon.set_value(f"{vol}%")
        self._vol_icon.set_active(not muted)

        br = get_brightness()
        self._bright_icon.set_value(f"{br}%")

        wifi_on = get_wifi()
        self._wifi_icon.set_icon("󰤨" if wifi_on else "󰤭")
        self._wifi_icon.set_active(wifi_on)
        self._wifi_icon.set_value("on" if wifi_on else "off")

        bt_on = get_bluetooth()
        self._bt_icon.set_icon("󰂯" if bt_on else "󰂲")
        self._bt_icon.set_active(bt_on)
        self._bt_icon.set_value("on" if bt_on else "off")

        return True


# ── entry point ───────────────────────────────────────────

if __name__ == "__main__":
    win = ControlsWindow()
    win.connect("destroy", Gtk.main_quit)
    win._show()

    ipc = HyprIPC([win])
    ipc.start()

    Gtk.main()