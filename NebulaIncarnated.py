
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gtk, Gdk, GLib, GtkLayerShell
from fabric import Application
import cairo
import math
import time
import subprocess
import json
import os

TWO_PI           = 2 * math.pi
VOICE_STATE_FILE = "/tmp/nebula_voice_active"  # "1" = playing, "0" = idle
BLOB_R           = 90
FPS              = 60
FRAME_MS         = 1000 // FPS
BAT_TTL          = 30
IDLE_THRESHOLD   = 10.0  # seconds before triggering animation
IDLE_CHECK       = 2.0    # seconds between checking workspace clients


# ══════════════════════════════════════════════════════════
# WORKSPACE ORBIT
# ══════════════════════════════════════════════════════════

class WorkspaceOrbit:
    RX_FRAC         = 0.30
    RY_FRAC         = 0.22
    BLOB_R          = 18
    ACTIVE_BONUS    = 5
    OFFSET          = -math.pi / 2   # 12 o'clock start (original)
    ROTATION_SPEED  = 0.4  # radians per second for orbiting
    DECELERATION    = 2.0  # how fast rotation slows down
    IDLE_THRESHOLD  = 10.0  # seconds before orbiting starts
    IDLE_CHECK      = 2.0    # seconds between checking

    def __init__(self):
        self._blobs       = []
        self._last_ws     = 0.0
        self._last_act    = 0.0
        self._last_tick   = time.monotonic()
        self._orbit_angle = 0.0
        self._current_speed = 0.0  # current rotation speed (decelerates)
        self._idle_since  = None
        self._mouse_moved = False
        self._last_mouse_check = 0.0
        self._refresh_ws()
        self._refresh_active()

    def _run(self, args):
        try:
            r = subprocess.run(
                ["hyprctl"] + args,
                capture_output=True, text=True, timeout=0.5)
            return json.loads(r.stdout)
        except Exception:
            return None

    def _assign_angles(self, ids):
        n    = len(ids)
        step = (2 * math.pi) / n if n else 0
        for blob in self._blobs:
            i             = ids.index(blob["id"])
            blob["angle"] = self.OFFSET + step * i

    def _refresh_ws(self):
        data = self._run(["workspaces", "-j"])
        if not data:
            return
        ids = sorted(ws["id"] for ws in data)
        self._blobs = [b for b in self._blobs if b["id"] in ids]
        existing    = {b["id"] for b in self._blobs}
        for wid in ids:
            if wid not in existing:
                self._blobs.append({"id": wid, "angle": 0.0, "active": False})
        self._assign_angles(ids)

    def _refresh_active(self):
        data = self._run(["activeworkspace", "-j"])
        if not data:
            return
        aid = data.get("id", -1)
        for b in self._blobs:
            b["active"] = (b["id"] == aid)

    def _check_mouse_moved(self):
        """Check if mouse is idle (no movement)."""
        now = time.monotonic()
        if now - self._last_mouse_check < 0.5:
            return self._mouse_moved
        self._last_mouse_check = now

        # Use xinput to check mouse activity
        try:
            result = subprocess.run(
                ["xinput", "query", "pointer", "10.0.0.0"],
                capture_output=True, text=True, timeout=0.5
            )
            # If command succeeds and returns quickly, mouse is active
            self._mouse_moved = True
        except:
            pass

        return self._mouse_moved

    def _check_idle(self):
        """Check if current workspace is idle with no apps."""
        now = time.monotonic()
        if now - self._last_ws < self.IDLE_CHECK:
            return

        self._last_ws = now

        # Check if mouse moved recently (user is active)
        if self._check_mouse_moved():
            # Decelerate when mouse moves (user is active)
            if self._current_speed > 0:
                self._current_speed = max(0, self._current_speed - self.DECELERATION * 0.5)
            self._idle_since = None
            return

        # Get active workspace ID
        ws_data = self._run(["activeworkspace", "-j"])
        if not ws_data:
            self._idle_since = None
            return

        wid = ws_data.get("id")
        if wid is None:
            self._idle_since = None
            return

        # Get clients in this workspace
        clients = self._run(["clients", "-j"])
        has_clients = False

        if clients:
            for c in clients:
                ws = c.get("workspace")
                if ws is not None:
                    ws_id = ws.get("id") if isinstance(ws, dict) else ws
                    if ws_id == wid:
                        has_clients = True
                        break

        if has_clients:
            self._idle_since = None
        else:
            if self._idle_since is None:
                self._idle_since = now

            idle_time = now - self._idle_since
            if idle_time > self.IDLE_THRESHOLD:
                # Gradually accelerate to full speed
                self._current_speed = min(self.ROTATION_SPEED, self._current_speed + 0.01)
            else:
                # Not idle yet, maintain slow rotation
                if self._current_speed > 0:
                    self._current_speed = max(0, self._current_speed - self.DECELERATION * 0.1)

    def on_mouse_move(self):
        """Call this when mouse movement is detected."""
        self._mouse_moved = True
        # Start decelerating instead of stopping instantly
        if self._current_speed > 0:
            self._current_speed = max(0, self._current_speed - self.DECELERATION)

    def tick(self):
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now

        # Reset mouse movement flag periodically
        self._mouse_moved = False

        # Check for idle state
        self._check_idle()

        # Update orbit angle based on current speed
        if self._current_speed > 0:
            self._orbit_angle += self._current_speed * dt

        # Refresh workspace/active info
        if now - self._last_ws >= 1.0:
            self._refresh_ws()
        if now - self._last_act >= 0.5:
            self._refresh_active()
            self._last_act = now

    def _pos(self, blob, cx, cy, W, H):
        # Base angle from offset
        base_angle = blob["angle"]
        # Add orbital rotation based on current angle
        angle = self._orbit_angle + base_angle
        return (
            cx + math.cos(angle) * W * self.RX_FRAC,
            cy + math.sin(angle) * H * self.RY_FRAC,
        )

    def _r(self, blob):
        return self.BLOB_R + (self.ACTIVE_BONUS if blob["active"] else 0)

    def draw(self, ctx, cx, cy, W, H):
        for blob in sorted(self._blobs, key=lambda b: b["active"]):
            x, y   = self._pos(blob, cx, cy, W, H)
            r      = self._r(blob)
            active = blob["active"]

            # glow for active
            if active:
                ctx.save()
                g = cairo.RadialGradient(x, y, r * 0.2, x, y, r * 2.4)
                g.add_color_stop_rgba(0, 1, 1, 1, 0.10)
                g.add_color_stop_rgba(1, 1, 1, 1, 0.00)
                ctx.set_source(g)
                ctx.arc(x, y, r * 2.4, 0, TWO_PI)
                ctx.fill()
                ctx.restore()

            # body
            ctx.save()
            ctx.set_source_rgba(1, 1, 1, 0.92 if active else 0.28)
            ctx.arc(x, y, r, 0, TWO_PI)
            ctx.fill()

            # rim highlight
            ctx.set_source_rgba(1, 1, 1, 0.22 if active else 0.08)
            ctx.set_line_width(0.8)
            ctx.arc(x - r * 0.22, y - r * 0.30, r * 0.45,
                    math.pi * 1.1, math.pi * 1.88)
            ctx.stroke()
            ctx.restore()

    def handle_click(self, mx, my, cx, cy, W, H):
        for blob in self._blobs:
            x, y = self._pos(blob, cx, cy, W, H)
            r    = self._r(blob) + 8
            if (mx - x) ** 2 + (my - y) ** 2 <= r ** 2:
                subprocess.Popen(
                    ["hyprctl", "dispatch", "workspace", str(blob["id"])])
                return True
        return False


# ══════════════════════════════════════════════════════════
# CORE BLOB
# ══════════════════════════════════════════════════════════

class CoreBlob(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()

        self._battery       = 0.0
        self._charging      = False
        self._time_str      = ""
        self._battery_ts    = 0.0
        self._last_minute   = ""
        self._clock_str     = ""
        self._glow_gradient = None
        self._last_cx       = None
        self._last_cy       = None

        self._orbit = WorkspaceOrbit()

        self._battery, self._charging, self._time_str = self._read_battery()
        self._battery_ts  = time.monotonic()
        self._clock_str   = time.strftime("%H:%M")
        self._last_minute = self._clock_str

        # voice mode state
        self._voice_active  = False
        self._voice_start_t = 0.0   # monotonic time when voice started

        self.connect("draw", self._draw)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect("button-press-event", self._on_click)
        self.connect("motion-notify-event", self._on_mouse_move)

        GLib.timeout_add(FRAME_MS, self._tick)

    # ── battery ───────────────────────────────────────────
    def _read_int(self, path):
        try:
            with open(path) as f:
                return int(f.read().strip())
        except OSError:
            return None

    def _read_battery(self):
        for prefix in ("BAT0", "BAT1"):
            base = f"/sys/class/power_supply/{prefix}"
            try:
                level = self._read_int(f"{base}/capacity")
                if level is None:
                    continue
                level /= 100.0

                charging = False
                try:
                    with open(f"{base}/status") as f:
                        status = f.read().strip().lower()
                    charging = status in ("charging", "full")
                except OSError:
                    pass

                time_str = self._estimate_time(base, level, charging)
                return level, charging, time_str

            except OSError:
                continue
        return 0.75, False, ""

    def _estimate_time(self, base, level, charging):
        charge_now  = self._read_int(f"{base}/charge_now")
        charge_full = self._read_int(f"{base}/charge_full")
        current_now = self._read_int(f"{base}/current_now")

        if current_now and current_now > 0:
            if charging and charge_full and charge_now:
                return self._fmt_hours((charge_full - charge_now) / current_now)
            elif not charging and charge_now:
                return self._fmt_hours(charge_now / current_now)

        energy_now  = self._read_int(f"{base}/energy_now")
        energy_full = self._read_int(f"{base}/energy_full")
        power_now   = self._read_int(f"{base}/power_now")

        if power_now and power_now > 0:
            if charging and energy_full and energy_now:
                return self._fmt_hours((energy_full - energy_now) / power_now)
            elif not charging and energy_now:
                return self._fmt_hours(energy_now / power_now)

        return ""

    def _fmt_hours(self, hours):
        if hours <= 0 or hours > 24:
            return ""
        h = int(hours)
        m = int((hours - h) * 60)
        if h > 0 and m > 0:
            return f"{h}h {m:02d}m"
        elif h > 0:
            return f"{h}h"
        return f"{m}m"

    def _maybe_update_battery(self):
        now = time.monotonic()
        if now - self._battery_ts >= BAT_TTL:
            self._battery, self._charging, self._time_str = self._read_battery()
            self._battery_ts = now

    def _maybe_update_clock(self):
        cur = time.strftime("%H:%M")
        if cur != self._last_minute:
            self._clock_str   = cur
            self._last_minute = cur

    # ── voice state ──────────────────────────────────────
    def _check_voice(self):
        """Poll the voice state file written by NebulaVoice.py."""
        try:
            with open(VOICE_STATE_FILE) as f:
                active = f.read().strip() == "1"
        except OSError:
            active = False
        if active and not self._voice_active:
            self._voice_start_t = time.monotonic()
        self._voice_active = active

    def _voice_radius(self):
        """
        Returns current blob radius during voice mode.
        Pulses like speech — slow drift with faster syllable-like spikes.
        """
        t = time.monotonic() - self._voice_start_t
        # base breathing pulse
        slow  = math.sin(t * 1.8) * 0.4
        # syllable ripple
        fast  = math.sin(t * 6.5) * 0.25 + math.sin(t * 4.1 + 1.2) * 0.15
        # combine — clamp to 0–1
        norm  = max(0.0, min(1.0, 0.5 + slow + fast))
        return BLOB_R + norm * 22   # pulses between BLOB_R and BLOB_R+22

    # ── tick ─────────────────────────────────────────────
    def _tick(self):
        self._check_voice()
        self._maybe_update_battery()
        self._maybe_update_clock()
        self._orbit.tick()
        self.queue_draw()
        return True

    def _on_click(self, widget, event):
        W = widget.get_allocated_width()
        H = widget.get_allocated_height()
        self._orbit.handle_click(event.x, event.y, W / 2, H / 2, W, H)

    def _on_mouse_move(self, widget, event):
        self._orbit.on_mouse_move()

    # ── glow (cached) ─────────────────────────────────────
    def _get_glow(self, cx, cy, r):
        if (self._glow_gradient is None
                or cx != self._last_cx or cy != self._last_cy):
            g = cairo.RadialGradient(cx, cy, r * 0.1, cx, cy, r * 2.8)
            g.add_color_stop_rgba(0.0, 1, 1, 1, 0.10)
            g.add_color_stop_rgba(1.0, 1, 1, 1, 0.00)
            self._glow_gradient = g
            self._last_cx = cx
            self._last_cy = cy
        return self._glow_gradient

    # ── draw helpers ──────────────────────────────────────
    def _draw_blob(self, ctx, cx, cy, r):
        ctx.set_source(self._get_glow(cx, cy, r))
        ctx.arc(cx, cy, r * 2.8, 0, TWO_PI)
        ctx.fill()

        ctx.set_source_rgba(1, 1, 1, 0.95)
        ctx.arc(cx, cy, r, 0, TWO_PI)
        ctx.fill()

        ctx.set_source_rgba(1, 1, 1, 0.35)
        ctx.set_line_width(1.2)
        ctx.arc(cx - r * 0.24, cy - r * 0.33, r * 0.52,
                math.pi * 1.1, math.pi * 1.88)
        ctx.stroke()

    def _draw_fluid(self, ctx, cx, cy, r, battery, charging):
        ctx.save()
        ctx.arc(cx, cy, r - 0.5, 0, TWO_PI)
        ctx.clip()

        fill_h = 2 * r * battery

        if charging:
            if battery > 0.80:
                ctx.set_source_rgba(0.10, 0.55, 0.20, 0.22)
            else:
                ctx.set_source_rgba(0.55, 0.35, 0.05, 0.22)
        else:
            ctx.set_source_rgba(0, 0, 0, 0.22)

        ctx.rectangle(cx - r, cy + r - fill_h, 2 * r, fill_h)
        ctx.fill()

        if 0.05 < battery < 0.98:
            ctx.set_source_rgba(0, 0, 0, 0.10)
            ctx.set_line_width(0.8)
            ctx.move_to(cx - r + 2, cy + r - fill_h)
            ctx.line_to(cx + r - 2, cy + r - fill_h)
            ctx.stroke()

        ctx.restore()

    def _draw_bolt(self, ctx, cx, cy, size, alpha):
        ctx.save()
        ctx.set_source_rgba(0, 0, 0, alpha)
        ctx.set_line_width(1.4)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        s = size
        ctx.move_to(cx + s * 0.25, cy - s)
        ctx.line_to(cx - s * 0.45, cy + s * 0.08)
        ctx.line_to(cx + s * 0.38, cy + s * 0.08)
        ctx.line_to(cx - s * 0.25, cy + s)
        ctx.stroke()
        ctx.restore()

    def _centered_text(self, ctx, text, cx, cy, size, r, g, b, a, bold=False):
        ctx.set_source_rgba(r, g, b, a)
        ctx.select_font_face(
            "monospace",
            cairo.FONT_SLANT_NORMAL,
            cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL,
        )
        ctx.set_font_size(size)
        _, _, tw, th, _, _ = ctx.text_extents(text)
        ctx.move_to(cx - tw / 2, cy + th / 2)
        ctx.show_text(text)

    # ── main draw ────────────────────────────────────────
    def _draw(self, widget, ctx):
        W = widget.get_allocated_width()
        H = widget.get_allocated_height()

        ctx.set_operator(cairo.OPERATOR_SOURCE)
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        ctx.set_operator(cairo.OPERATOR_OVER)

        cx = W / 2
        cy = H / 2
        t  = time.monotonic()

        if self._voice_active:
            # ── VOICE MODE — pulsing glow, nothing else ───
            r = self._voice_radius()

            # large soft glow — grows with radius
            glow_r = r * 3.5
            g = cairo.RadialGradient(cx, cy, r * 0.2, cx, cy, glow_r)
            g.add_color_stop_rgba(0.0, 1, 1, 1, 0.18)
            g.add_color_stop_rgba(0.6, 1, 1, 1, 0.06)
            g.add_color_stop_rgba(1.0, 1, 1, 1, 0.00)
            ctx.set_source(g)
            ctx.arc(cx, cy, glow_r, 0, TWO_PI)
            ctx.fill()

            # blob body — clean white circle, no fluid, no text
            ctx.set_source_rgba(1, 1, 1, 0.95)
            ctx.arc(cx, cy, r, 0, TWO_PI)
            ctx.fill()

            # rim highlight scales with r
            ctx.set_source_rgba(1, 1, 1, 0.35)
            ctx.set_line_width(1.2)
            ctx.arc(cx - r * 0.24, cy - r * 0.33, r * 0.52,
                    math.pi * 1.1, math.pi * 1.88)
            ctx.stroke()

        else:
            # ── NORMAL MODE ───────────────────────────────
            r = BLOB_R

            # workspace orbit
            self._orbit.draw(ctx, cx, cy, W, H)

            # ripple
            ripple = (t * 0.35) % 1.0
            ctx.set_source_rgba(1, 1, 1, 0.06 * (1.0 - ripple))
            ctx.set_line_width(0.8)
            ctx.arc(cx, cy, r + ripple * 55, 0, TWO_PI)
            ctx.stroke()

            # core blob + fluid
            self._draw_blob(ctx, cx, cy, r)
            self._draw_fluid(ctx, cx, cy, r, self._battery, self._charging)

            # clock
            self._centered_text(
                ctx, self._clock_str,
                cx, cy - 10,
                size=26, r=0, g=0, b=0, a=0.82, bold=True)

            # battery %
            bat_str = f"{int(self._battery * 100)}%"
            ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL,
                                 cairo.FONT_WEIGHT_NORMAL)
            ctx.set_font_size(13)
            _, _, tw, th, _, _ = ctx.text_extents(bat_str)

            if self._charging:
                text_x = cx - tw / 2 - 7
                ctx.set_source_rgba(0, 0, 0, 0.45)
                ctx.move_to(text_x, cy + 22 + th / 2)
                ctx.show_text(bat_str)
                self._draw_bolt(ctx, cx + tw / 2 + 1, cy + 22,
                                size=6, alpha=0.50)
            else:
                self._centered_text(
                    ctx, bat_str,
                    cx, cy + 22,
                    size=13, r=0, g=0, b=0, a=0.45)

            # time estimate
            if self._time_str:
                self._centered_text(
                    ctx, self._time_str,
                    cx, cy + 40,
                    size=10, r=0, g=0, b=0, a=0.30)


# ══════════════════════════════════════════════════════════
# SHELL WINDOW
# ══════════════════════════════════════════════════════════

class ShellWindow(Gtk.Window):
    def __init__(self):
        super().__init__()

        self.set_decorated(False)
        self.set_app_paintable(True)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.BOTTOM)

        for edge in (GtkLayerShell.Edge.TOP,    GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT,   GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)

        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.add(CoreBlob())


# ── entry point ───────────────────────────────────────────


# ══════════════════════════════════════════════════════════
# STARTUP — play voice if no daily goal set today
# ══════════════════════════════════════════════════════════

NEBULA_DIR  = os.path.expanduser("~/.local/share/nebula")
GOAL_FILE   = os.path.join(NEBULA_DIR, "today.json")
VOICE_FILE  = "/home/aman/.config/nebula/voice/NEBULA_Initialized.mp3"

def _goal_set_today():
    """Return True if user already set a goal for today."""
    try:
        with open(GOAL_FILE) as f:
            data = json.load(f)
        return (data.get("date") == time.strftime("%Y-%m-%d")
                and bool(data.get("goal", "").strip()))
    except (OSError, json.JSONDecodeError):
        return False

VOICE_VIZ = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "NebulaVoiceViz.py")

def _play_startup_voice():
    """Play voice + launch visualizer if no goal set today."""
    if not _goal_set_today() and os.path.exists(VOICE_FILE):
        # launch audio
        subprocess.Popen(
            ["mpv", "--no-video", "--really-quiet", VOICE_FILE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # launch visualizer (self-destructs after clip duration)
        import sys
        venv_python = sys.executable
        if os.path.exists(VOICE_VIZ):
            subprocess.Popen(
                [venv_python, VOICE_VIZ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

app = Application()

def activate(app):
    win = ShellWindow()
    win.set_application(app)
    win.show_all()
    # slight delay so layer shell renders before audio starts
    GLib.timeout_add(800, lambda: (_play_startup_voice(), False)[1])

app.connect("activate", activate)
app.run()
