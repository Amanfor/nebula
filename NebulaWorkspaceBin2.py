import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")

from gi.repository import Gtk, Gdk, GLib, GtkLayerShell
import cairo as Cairo
import subprocess
import json
import os
import socket
import fcntl

# ── state file ────────────────────────────────────────────
NEBULA_DIR = os.path.expanduser("~/.local/share/nebula")
BIN_FILE   = os.path.join(NEBULA_DIR, "workspace_bin.json")
SOCKET_FILE = os.path.join(NEBULA_DIR, "workspace_bin.sock")
os.makedirs(NEBULA_DIR, exist_ok=True)

CSS = """
* { font-family: monospace; }

.bin-header {
    color: rgba(255,255,255,0.30);
    font-size: 11px;
    letter-spacing: 3px;
    margin-bottom: 8px;
}

.slot-box {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 12px;
    padding: 10px;
    margin: 4px 0;
}

.slot-box:hover {
    background: rgba(255,255,255,0.08);
    border-color: rgba(255,255,255,0.20);
}

.slot-name {
    color: rgba(255,255,255,0.70);
    font-size: 12px;
    letter-spacing: 1px;
}

.slot-apps {
    color: rgba(255,255,255,0.35);
    font-size: 10px;
    letter-spacing: 1px;
    margin-top: 4px;
}

.slot-btn {
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 6px;
    color: rgba(255,255,255,0.50);
    font-size: 14px;
    padding: 4px 10px;
    min-width: 36px;
    min-height: 36px;
}

.slot-btn:hover {
    background: rgba(255,255,255,0.15);
    border-color: rgba(255,255,255,0.30);
    color: rgba(255,255,255,0.90);
}
"""


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True,
                              text=True, timeout=0.8).stdout.strip()
    except Exception:
        return ""


def get_current_apps():
    """Return list of app states on current active workspace."""
    try:
        ws_data  = json.loads(run(["hyprctl", "activeworkspace", "-j"]))
        ws_id    = ws_data.get("id", -1)
        clients  = json.loads(run(["hyprctl", "clients", "-j"]))
        
        states = []
        for c in clients:
            if c.get("workspace", {}).get("id") == ws_id:
                state = {
                    "class": c.get("class", "?"),
                    "title": c.get("title", ""),
                    "address": c.get("address", ""),
                    "at": c.get("at", [0, 0]),
                    "size": c.get("size", [0, 0]),
                    "float": c.get("float", False),
                    "fullscreen": c.get("fullscreen", False),
                }
                states.append(state)
        
        return states
    except Exception:
        return []


def load_bin():
    try:
        with open(BIN_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def save_bin(slots):
    with open(BIN_FILE, "w") as f:
        json.dump(slots, f, indent=2)


def get_next_workspace_number():
    slots = load_bin()
    numbers = []
    for slot in slots:
        name = slot.get("name", "")
        if name.startswith("workspace "):
            try:
                num = int(name.split()[-1])
                numbers.append(num)
            except:
                pass
    if not numbers:
        return 1
    return max(numbers) + 1


# ══════════════════════════════════════════════════════════
# IPC SOCKET HANDLER
# ══════════════════════════════════════════════════════════

class IPCSocketHandler:
    def __init__(self, window):
        self._window = window
        self._running = True

    def start(self):
        if os.path.exists(SOCKET_FILE):
            os.remove(SOCKET_FILE)
        
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(SOCKET_FILE)
        self._sock.listen(5)
        self._sock.setblocking(False)
        
        flags = fcntl.fcntl(self._sock.fileno(), fcntl.F_GETFL)
        fcntl.fcntl(self._sock.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
        GLib.timeout_add(100, self._accept)

    def _accept(self):
        if not self._running:
            return False
        try:
            conn, _ = self._sock.accept()
            GLib.timeout_add(50, self._handle, conn)
        except BlockingIOError:
            pass
        except Exception:
            pass
        return True

    def _handle(self, conn):
        try:
            data = conn.recv(1024).decode().strip()
            conn.close()
            
            if data == "save":
                self._window.save_workspace()
            elif data == "reload":
                self._window.reload_slots()
            elif data.startswith("restore:"):
                try:
                    idx = int(data.split(":")[1])
                    self._window.restore_workspace(idx)
                except:
                    pass
            elif data.startswith("delete:"):
                try:
                    idx = int(data.split(":")[1])
                    self._window.delete_slot(idx)
                except:
                    pass
            elif data.startswith("rename:"):
                try:
                    parts = data.split(":")
                    idx = int(parts[1])
                    new_name = parts[2] if len(parts) > 2 else "workspace"
                    self._window.rename_slot(idx, new_name)
                except:
                    pass
        except:
            pass
        return False

    def stop(self):
        self._running = False
        try:
            self._sock.close()
        except:
            pass
        if os.path.exists(SOCKET_FILE):
            os.remove(SOCKET_FILE)


# ══════════════════════════════════════════════════════════
# WORKSPACE BIN WINDOW
# ══════════════════════════════════════════════════════════

class WorkspaceBinWindow(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_decorated(False)
        self.set_app_paintable(True)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.connect("draw", self._clear)

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT,  True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, 36)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT,  16)
        GtkLayerShell.set_keyboard_mode(
            self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        self._slots  = load_bin()

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._outer.set_margin_start(4)
        self._outer.set_margin_end(4)
        self._outer.set_margin_top(4)
        self._outer.set_margin_bottom(4)

        header = Gtk.Label(label="workspace bin")
        header.get_style_context().add_class("bin-header")
        header.set_halign(Gtk.Align.START)
        self._outer.pack_start(header, False, False, 0)

        self._slots_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._outer.pack_start(self._slots_box, False, False, 0)

        self.add(self._outer)
        self._rebuild()

    def _clear(self, widget, ctx):
        ctx.set_operator(Cairo.OPERATOR_SOURCE)
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        ctx.set_operator(Cairo.OPERATOR_OVER)
        return False

    def _rebuild(self):
        for child in self._slots_box.get_children():
            self._slots_box.remove(child)

        for i, slot in enumerate(self._slots):
            self._slots_box.pack_start(
                self._make_slot(i, slot), False, False, 0)

        self._slots_box.show_all()

    def _make_slot(self, index, slot):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.get_style_context().add_class("slot-box")

        top_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        name_lbl = Gtk.Label(label=slot.get("name", "workspace"))
        name_lbl.get_style_context().add_class("slot-name")
        name_lbl.set_xalign(0)
        name_lbl.set_hexpand(True)

        # rename button
        rename_btn = Gtk.Button(label="✎")
        rename_btn.get_style_context().add_class("slot-btn")
        rename_btn.set_relief(Gtk.ReliefStyle.NONE)
        rename_btn.connect("clicked", self._on_rename_clicked, index)
        rename_btn.set_tooltip_text("rename")

        # restore button
        restore_btn = Gtk.Button(label="↗")
        restore_btn.get_style_context().add_class("slot-btn")
        restore_btn.set_relief(Gtk.ReliefStyle.NONE)
        restore_btn.connect("clicked", self._restore, index)
        restore_btn.set_tooltip_text("launch apps")

        # delete button
        del_btn = Gtk.Button(label="×")
        del_btn.get_style_context().add_class("slot-btn")
        del_btn.set_relief(Gtk.ReliefStyle.NONE)
        del_btn.connect("clicked", self._delete_slot, index)
        del_btn.set_tooltip_text("delete")

        top_row.pack_start(name_lbl,    True,  True,  0)
        top_row.pack_start(rename_btn, False, False, 0)
        top_row.pack_start(restore_btn, False, False, 0)
        top_row.pack_start(del_btn,     False, False, 0)

        # Show app names
        apps = slot.get("apps", [])
        if apps:
            app_names = []
            for a in apps:
                if isinstance(a, dict):
                    app_names.append(a.get("class", "?")[:10])
                else:
                    app_names.append(str(a)[:10])
            apps_str = "  ".join(app_names)
        else:
            apps_str = "no apps"
        
        apps_lbl = Gtk.Label(label=apps_str)
        apps_lbl.get_style_context().add_class("slot-apps")
        apps_lbl.set_xalign(0)
        apps_lbl.set_ellipsize(3)
        apps_lbl.set_max_width_chars(26)

        box.pack_start(top_row, False, False, 0)
        box.pack_start(apps_lbl, False, False, 0)
        return box

    def _on_rename_clicked(self, btn, index):
        """Show rename dialog."""
        dialog = Gtk.MessageDialog(
            self, 0, Gtk.MessageType.QUESTION, Gtk.ButtonsType.OK_CANCEL,
            "Rename workspace"
        )
        dialog.set_title("Rename")
        
        box = dialog.get_content_area()
        
        entry = Gtk.Entry()
        entry.set_text(self._slots[index].get("name", "workspace"))
        entry.show()
        box.pack_start(entry, True, True, 0)
        
        entry_index = index
        
        def on_response(dlg, response_id):
            if response_id == Gtk.ResponseType.OK:
                new_name = entry.get_text().strip()
                if new_name:
                    self._slots[entry_index]["name"] = new_name
                    save_bin(self._slots)
                    self._rebuild()
            dialog.destroy()
        
        dialog.connect("response", on_response)
        dialog.show_all()
        entry.grab_focus()

    def rename_slot(self, index, new_name):
        """Rename slot by index from socket."""
        if 0 <= index < len(self._slots):
            self._slots[index]["name"] = new_name
            save_bin(self._slots)
            self._rebuild()

    def save_workspace(self):
        num = get_next_workspace_number()
        name = f"workspace {num}"
        apps = get_current_apps()
        self._slots.append({"name": name, "apps": apps})
        save_bin(self._slots)
        self._rebuild()

    def restore_workspace(self, index):
        self._restore(None, index)

    def reload_slots(self):
        self._slots = load_bin()
        self._rebuild()

    def _restore(self, btn, index):
        if index >= len(self._slots):
            return
            
        slot = self._slots[index]
        apps = slot.get("apps", [])
        
        # First pass: launch all apps
        launched = []
        for app in apps:
            app_class = app.get("class", "?")
            if app_class and app_class not in launched:
                launched.append(app_class)
                try:
                    subprocess.Popen(["gtk-launch", app_class])
                except:
                    pass
        
        # Second pass: restore window states
        import time
        time.sleep(0.5)
        
        for app in apps:
            app_class = app.get("class", "?")
            title = app.get("title", "")
            at = app.get("at", [0, 0])
            size = app.get("size", [800, 600])
            is_float = app.get("float", False)
            is_fullscreen = app.get("fullscreen", False)
            
            try:
                # Find the window
                result = run(["hyprctl", "clients", "-j"])
                clients = json.loads(result or "[]")
                
                for client in clients:
                    if client.get("class") == app_class:
                        addr = client.get("address", "")
                        if addr:
                            # Set position
                            if at[0] != 0 or at[1] != 0:
                                run(["hyprctl", "dispatch", "movewindow", f"pixel,{at[0]},{at[1]}", addr])
                            
                            # Set size
                            if size[0] > 0 and size[1] > 0:
                                run(["hyprctl", "dispatch", "resizewindow", f"{size[0]},{size[1]}", addr])
                            # Floating
                            if is_float:
                                run(["hyprctl", "dispatch", "togglefloating", addr])
                            # Fullscreen
                            if is_fullscreen:
                                run(["hyprctl", "dispatch", "fullscreen", addr])
                        break
            except:
                pass

    def _delete_slot(self, btn, index):
        self._slots.pop(index)
        save_bin(self._slots)
        self._rebuild()

    def set_blocked(self, blocked):
        if blocked:
            self.hide()
        else:
            self.show_all()


class HyprIPC:
    def __init__(self, windows):
        self._windows = windows

    def start(self):
        GLib.timeout_add(500, self._poll)

    def _poll(self):
        try:
            result = run(["hyprctl", "activewindow", "-j"])
            data = json.loads(result or "{}")
            app_open = bool(data.get("class", "").strip())
        except Exception:
            app_open = False
        
        for win in self._windows:
            win.set_blocked(app_open)
        return True


# ══════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    win = WorkspaceBinWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()

    ipc = IPCSocketHandler(win)
    ipc.start()

    hypr = HyprIPC([win])
    hypr.start()

    Gtk.main()
    ipc.stop()