import os
os.environ.setdefault("GDK_BACKEND", "wayland")

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gtk, Gdk, GLib, GtkLayerShell, Pango
import json, os, time, sys, subprocess
import cairo as Cairo

# ── paths ─────────────────────────────────────────────────
NEBULA_DIR = os.path.expanduser("~/.local/share/nebula")
GOAL_FILE  = os.path.join(NEBULA_DIR, "today.json")
TODO_FILE  = os.path.join(NEBULA_DIR, "todo.json")
os.makedirs(NEBULA_DIR, exist_ok=True)

# ── voice module ──────────────────────────────────────────
_NEBULA_CONF = os.path.expanduser("~/.config/nebula")
if _NEBULA_CONF not in sys.path:
    sys.path.insert(0, _NEBULA_CONF)
try:
    import NebulaVoice as _voice
    _VOICE_OK = True
except ImportError:
    _VOICE_OK = False

def _play_voice(key, with_viz=False):
    if _VOICE_OK:
        _voice.play(key, with_viz=with_viz)

# ── css ───────────────────────────────────────────────────
CSS = """
* { font-family: monospace; }

.goal-header {
    color: rgba(255,255,255,0.50);
    font-size: 9px;
    letter-spacing: 3px;
}
.goal-text {
    color: rgba(255,255,255,0.90);
    font-size: 13px;
    letter-spacing: 2px;
}
.goal-placeholder {
    color: rgba(255,255,255,0.40);
    font-size: 13px;
    letter-spacing: 2px;
    font-style: italic;
}
.goal-entry {
    background: transparent;
    color: rgba(255,255,255,0.95);
    border: none;
    border-bottom: 1px solid rgba(255,255,255,0.50);
    font-size: 13px;
    letter-spacing: 2px;
    padding: 2px 0px;
    min-width: 280px;
    caret-color: rgba(255,255,255,0.9);
}
.todo-header {
    color: rgba(255,255,255,0.50);
    font-size: 9px;
    letter-spacing: 3px;
}
.task-text {
    color: rgba(255,255,255,0.80);
    font-size: 11px;
    letter-spacing: 1px;
    padding: 2px 0px;
}
.task-text:hover {
    color: rgba(255,255,255,1.0);
}
.task-text.done {
    color: rgba(255,255,255,0.28);
}
.clear-btn {
    background: transparent;
    border: none;
    color: rgba(255,255,255,0.35);
    font-size: 12px;
    padding: 0 0 0 6px;
}
.clear-btn:hover { color: rgba(255,255,255,0.80); }
.add-btn {
    background: transparent;
    border: 1px solid rgba(255,255,255,0.40);
    border-radius: 50%;
    color: rgba(255,255,255,0.70);
    min-width: 18px;
    min-height: 18px;
    padding: 0;
    font-size: 13px;
    margin-right: 8px;
}
.add-btn:hover {
    border-color: rgba(255,255,255,0.90);
    color: rgba(255,255,255,1.0);
}
.task-entry {
    background: transparent;
    color: rgba(255,255,255,0.90);
    border: none;
    border-bottom: 1px solid rgba(255,255,255,0.40);
    font-size: 11px;
    padding: 1px 0px;
    min-width: 180px;
    caret-color: rgba(255,255,255,0.9);
}
"""

# ── state ─────────────────────────────────────────────────
def load_goal():
    today = time.strftime("%Y-%m-%d")
    try:
        with open(GOAL_FILE) as f:
            data = json.load(f)
        if data.get("date") == today:
            return data.get("goal", "")
    except (OSError, json.JSONDecodeError):
        pass
    return ""

def save_goal(text):
    with open(GOAL_FILE, "w") as f:
        json.dump({"date": time.strftime("%Y-%m-%d"), "goal": text}, f)

def load_tasks():
    try:
        with open(TODO_FILE) as f:
            return json.load(f).get("items", [])
    except (OSError, json.JSONDecodeError):
        return []

def save_tasks(tasks):
    with open(TODO_FILE, "w") as f:
        json.dump({"items": tasks}, f, indent=2)

# ── transparent window helper ─────────────────────────────
def make_transparent(win):
    win.set_decorated(False)
    win.set_app_paintable(True)
    screen = win.get_screen()
    visual = screen.get_rgba_visual()
    if visual:
        win.set_visual(visual)
    win.connect("draw", _clear_bg)

def _clear_bg(widget, ctx):
    ctx.set_operator(Cairo.OPERATOR_SOURCE)
    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()
    ctx.set_operator(Cairo.OPERATOR_OVER)
    return False


# ══════════════════════════════════════════════════════════
# GOAL WINDOW — small, anchored top-center
# ══════════════════════════════════════════════════════════

class GoalWindow(Gtk.Window):
    """
    Daily goal widget.

    Behaviour:
    - If no goal set today  → shows editable entry on click (first login flow)
    - If goal already set   → locked, shows goal as plain text
                              clicking plays the "you can't change it" voice
    """

    def __init__(self):
        super().__init__()
        make_transparent(self)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 28)
        GtkLayerShell.set_keyboard_mode(
            self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        self._goal   = load_goal()
        self._locked = bool(self._goal)   # locked if goal already exists

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(4)
        box.set_margin_bottom(8)

        header = Gtk.Label(label="daily goal")
        header.get_style_context().add_class("goal-header")
        box.pack_start(header, False, False, 0)

        # ── display stack: label ↔ entry ──────────────────
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(120)

        # label side — always shown when locked
        self._label = Gtk.Label()
        self._label.set_halign(Gtk.Align.CENTER)
        self._refresh_label()

        self._click_box = Gtk.EventBox()
        self._click_box.add(self._label)
        self._click_box.connect("button-press-event", self._on_label_click)

        # entry side — only shown when not yet locked
        self._entry = Gtk.Entry()
        self._entry.get_style_context().add_class("goal-entry")
        self._entry.set_has_frame(False)
        self._entry.set_alignment(0.5)
        self._entry.set_placeholder_text("what's the goal for today?")
        self._entry.connect("activate",        self._commit)
        self._entry.connect("focus-out-event", self._commit)
        self._entry.connect("key-press-event", self._on_key)

        self._stack.add_named(self._click_box, "label")
        self._stack.add_named(self._entry,     "entry")
        self._stack.set_visible_child_name("label")

        box.pack_start(self._stack, False, False, 0)
        self.add(box)

        # if no goal yet, open entry automatically on startup
        if not self._locked:
            GLib.timeout_add(400, self._open_entry)

    def _open_entry(self):
        self._entry.set_text("")
        self._stack.set_visible_child_name("entry")
        self._entry.grab_focus()
        return False   # one-shot

    def _on_label_click(self, *_):
        if self._locked:
            # goal is set — play the locked voice and do nothing else
            _play_voice("goal_locked", with_viz=True)
        else:
            # no goal yet — open entry
            self._open_entry()

    def _refresh_label(self):
        if self._goal:
            self._label.set_text(self._goal)
            self._label.get_style_context().remove_class("goal-placeholder")
            self._label.get_style_context().add_class("goal-text")
        else:
            self._label.set_text("set today's goal")
            self._label.get_style_context().remove_class("goal-text")
            self._label.get_style_context().add_class("goal-placeholder")

    def _commit(self, *_):
        text = self._entry.get_text().strip()
        if not text:
            # don't save empty goal — keep entry open
            return
        self._goal   = text
        self._locked = True
        save_goal(text)
        self._refresh_label()
        self._stack.set_visible_child_name("label")
        # keyboard no longer needed
        GtkLayerShell.set_keyboard_mode(
            self, GtkLayerShell.KeyboardMode.NONE)

    def _on_key(self, widget, event):
        # Escape cancels only if goal was already set before
        if event.keyval == Gdk.KEY_Escape and self._locked:
            self._stack.set_visible_child_name("label")
            return True
        return False


# ══════════════════════════════════════════════════════════
# TODO WINDOW — small, anchored bottom-left
# ══════════════════════════════════════════════════════════

class TodoWindow(Gtk.Window):
    def __init__(self):
        super().__init__()
        make_transparent(self)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT,   True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, 36)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT,   36)
        GtkLayerShell.set_keyboard_mode(
            self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        self._tasks = load_tasks()

        self._outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._outer.set_margin_top(4)
        self._outer.set_margin_bottom(4)
        self._outer.set_margin_start(2)
        self._outer.set_margin_end(8)

        # header row
        header_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header = Gtk.Label(label="to-do")
        header.get_style_context().add_class("todo-header")
        header.set_halign(Gtk.Align.START)

        clear_btn = Gtk.Button(label="🗑")
        clear_btn.get_style_context().add_class("clear-btn")
        clear_btn.set_relief(Gtk.ReliefStyle.NONE)
        clear_btn.connect("clicked", self._clear_all)

        header_row.pack_start(header,    False, False, 0)
        header_row.pack_start(clear_btn, False, False, 0)
        self._outer.pack_start(header_row, False, False, 0)

        # task rows
        self._rows = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._outer.pack_start(self._rows, False, False, 0)

        # add row
        add_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        add_row.set_margin_top(6)

        self._add_btn = Gtk.Button(label="+")
        self._add_btn.get_style_context().add_class("add-btn")
        self._add_btn.set_relief(Gtk.ReliefStyle.NONE)
        self._add_btn.connect("clicked", self._show_entry)

        self._entry = Gtk.Entry()
        self._entry.get_style_context().add_class("task-entry")
        self._entry.set_has_frame(False)
        self._entry.set_placeholder_text("new task…")
        self._entry.connect("activate",        self._commit_task)
        self._entry.connect("focus-out-event", self._cancel_entry)
        self._entry.connect("key-press-event", self._entry_key)
        self._entry.set_no_show_all(True)
        self._entry.hide()

        add_row.pack_start(self._add_btn, False, False, 0)
        add_row.pack_start(self._entry,   False, False, 0)
        self._outer.pack_start(add_row, False, False, 0)

        self.add(self._outer)
        self._rebuild()



        self._btn_fade_id = None

    def _rebuild(self):
        for child in self._rows.get_children():
            self._rows.remove(child)
        for i, task in enumerate(self._tasks):
            self._rows.pack_start(self._make_row(i, task), False, False, 0)
        self._rows.show_all()

    def _make_row(self, index, task):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        label = Gtk.Label(label=task["text"])
        label.get_style_context().add_class("task-text")
        label.set_xalign(0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(30)

        if task["done"]:
            label.get_style_context().add_class("done")
            attrs = Pango.AttrList()
            attrs.insert(Pango.attr_strikethrough_new(True))
            label.set_attributes(attrs)

        ebox = Gtk.EventBox()
        ebox.add(label)
        ebox.connect("button-press-event",
            lambda w, e, i=index: self._toggle(i))

        row.pack_start(ebox, False, False, 0)
        return row

    def _show_entry(self, *_):
        self._entry.show()
        self._entry.grab_focus()

    def _commit_task(self, *_):
        text = self._entry.get_text().strip()
        if text:
            self._tasks.append({"text": text, "done": False})
            save_tasks(self._tasks)
            self._rebuild()
        self._cancel_entry()

    def _cancel_entry(self, *_):
        self._entry.set_text("")
        self._entry.hide()

    def _entry_key(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self._cancel_entry()
            return True
        return False

    def _toggle(self, index):
        self._tasks[index]["done"] = not self._tasks[index]["done"]
        save_tasks(self._tasks)
        self._rebuild()

    def _clear_all(self, *_):
        self._tasks = []
        save_tasks(self._tasks)
        self._rebuild()


# ══════════════════════════════════════════════════════════
# HYPRLAND IPC — disable input when any app is focused
# ══════════════════════════════════════════════════════════

class HyprIPC:
    """
    Polls hyprctl every 500ms to check if any window is active.
    Active window  → set empty input region (fully click-through).
    Desktop active → restore input region to widget bounds.
    """
    def __init__(self, windows):
        self._windows = windows
        self._blocked = False

    def start(self):
        # poll on GTK main thread via timeout — no threading needed
        GLib.timeout_add(500, self._poll)

    def _poll(self):
        try:
            import subprocess, json as _json
            result = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True, text=True, timeout=0.4)
            data     = _json.loads(result.stdout or "{}")
            app_open = bool(data.get("class", "").strip())
        except Exception:
            app_open = False
        self._set_blocked(app_open)
        return True  # keep polling

    def _set_blocked(self, block):
        if block == self._blocked:
            return
        self._blocked = block
        for win in self._windows:
            if block:
                win.hide()
            else:
                win.show_all()


# ── entry point ───────────────────────────────────────────

if __name__ == "__main__":
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS.encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )

    goal_win = GoalWindow()
    goal_win.connect("destroy", Gtk.main_quit)
    goal_win.show_all()

    todo_win = TodoWindow()
    todo_win.connect("destroy", Gtk.main_quit)
    todo_win.show_all()

    # disable widget input whenever an app window is focused
    ipc = HyprIPC([goal_win, todo_win])
    ipc.start()

    # ── startup voices ────────────────────────────────────
    # delay slightly so layer shell finishes rendering first
    goal_already_set = bool(load_goal())
    if _VOICE_OK:
        GLib.timeout_add(700, lambda: (_voice.play_startup(goal_already_set), False)[1])

    Gtk.main()()
