#!/usr/bin/env python3

import gi, subprocess, sys
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, Gdk

class PowerMenu(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.set_wmclass("powermenu", "powermenu")  # Add this line
        # ... rest of your code

HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }

html, body {
  width: 100vw; height: 100vh;
  background: rgba(10, 10, 12, 0.93);
  display: flex; align-items: center; justify-content: center;
  font-family: monospace;
  overflow: hidden;
}

.container {
  position: relative;
  width: 280px; height: 280px;
}

.center-blob {
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  width: 76px; height: 76px;
  border-radius: 50%;
  background: rgba(255,255,255,0.88);
  cursor: pointer;
  transition: all 0.4s cubic-bezier(0.34, 1.4, 0.64, 1);
  z-index: 10;
  box-shadow: 0 0 0 1px rgba(255,255,255,0.12);
}

.center-blob::after {
  content: '';
  position: absolute;
  inset: -6px;
  border-radius: 50%;
  border: 1px solid rgba(255,255,255,0.10);
  animation: ripple 2.8s ease-out infinite;
}

@keyframes ripple {
  0%   { inset: -4px;  opacity: 0.15; }
  100% { inset: -24px; opacity: 0; }
}

.container:hover .center-blob {
  width: 16px; height: 16px;
  background: rgba(255,255,255,0.25);
  box-shadow: none;
}
.container:hover .center-blob::after { display: none; }

.btn {
  position: absolute;
  top: 50%; left: 50%;
  width: 72px; height: 72px;
  border-radius: 50%;
  border: 1px solid rgba(255,255,255,0.10);
  background: rgba(255,255,255,0.04);
  transform: translate(-50%, -50%) scale(0.2);
  opacity: 0;
  cursor: pointer;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: 6px;
  transition:
    transform 0.42s cubic-bezier(0.34, 1.4, 0.64, 1),
    opacity   0.30s ease,
    background 0.25s ease,
    border-color 0.25s ease;
  pointer-events: none;
  user-select: none;
}

.btn svg {
  width: 20px; height: 20px;
  stroke: rgba(255,255,255,0.55);
  fill: none;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
  transition: stroke 0.25s ease;
}

.btn span {
  font-size: 8px;
  letter-spacing: 0.16em;
  color: rgba(255,255,255,0.28);
  transition: color 0.25s ease;
}

.container:hover .btn {
  opacity: 1;
  pointer-events: all;
}

.container:hover .btn-lock     { transform: translate(calc(-50% - 105px), -50%) scale(1); transition-delay: 0.00s; }
.container:hover .btn-logout   { transform: translate(-50%, calc(-50% - 105px)) scale(1); transition-delay: 0.05s; }
.container:hover .btn-reboot   { transform: translate(calc(-50% + 105px), -50%) scale(1); transition-delay: 0.10s; }
.container:hover .btn-shutdown { transform: translate(-50%, calc(-50% + 105px)) scale(1); transition-delay: 0.15s; }

.btn:hover {
  background: rgba(255,255,255,0.92);
  border-color: rgba(255,255,255,0.80);
}
.btn:hover svg   { stroke: rgba(10,10,12,0.80); }
.btn:hover span  { color: rgba(10,10,12,0.60); }

.link {
  position: absolute;
  top: 50%; left: 50%;
  height: 1px;
  background: rgba(255,255,255,0.06);
  transform-origin: left center;
  opacity: 0;
  transition: opacity 0.3s ease 0.1s;
  pointer-events: none;
}
.container:hover .link { opacity: 1; }

.link-left     { width: 68px; transform: translate(-50%, -50%) rotate(180deg); }
.link-top      { width: 68px; transform: translate(-50%, -50%) rotate(270deg); }
.link-right    { width: 68px; transform: translate(-50%, -50%) rotate(0deg); }
.link-bottom   { width: 68px; transform: translate(-50%, -50%) rotate(90deg); }

.hint {
  position: fixed;
  bottom: 28px; left: 50%;
  transform: translateX(-50%);
  font-size: 9px;
  letter-spacing: 0.16em;
  color: rgba(255,255,255,0.12);
  pointer-events: none;
}
</style>
</head>
<body>

<div class="container" id="root">
  <div class="link link-left"></div>
  <div class="link link-top"></div>
  <div class="link link-right"></div>
  <div class="link link-bottom"></div>

  <div class="center-blob"></div>

  <div class="btn btn-lock" onclick="run('lock')">
    <svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>
    <span>lock</span>
  </div>

  <div class="btn btn-logout" onclick="run('logout')">
    <svg viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
    <span>logout</span>
  </div>

  <div class="btn btn-reboot" onclick="run('reboot')">
    <svg viewBox="0 0 24 24"><path d="M21.5 2v6h-6"/><path d="M21.34 15.57a10 10 0 1 1-.57-8.38"/></svg>
    <span>reboot</span>
  </div>

  <div class="btn btn-shutdown" onclick="run('shutdown')">
    <svg viewBox="0 0 24 24"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
    <span>shutdown</span>
  </div>
</div>

<div class="hint">hover to expand &nbsp;·&nbsp; esc to close</div>

<script>
function run(action) {
  window.webkit.messageHandlers.nebula.postMessage(action);
}

document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') window.webkit.messageHandlers.nebula.postMessage('close');
});
</script>
</body>
</html>"""

COMMANDS = {
    'lock':     ['loginctl', 'lock-session'],
    'logout':   ['loginctl', 'terminate-user', 'self'],
    'reboot':   ['systemctl', 'reboot'],
    'shutdown': ['systemctl', 'poweroff'],
    'close':    None,
}

class PowerMenu(Gtk.Window):
    def __init__(self):
        super().__init__()

        # fullscreen transparent window
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.maximize()

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.set_keep_above(True)
        self.connect('destroy', Gtk.main_quit)
        self.connect('key-press-event', self.on_key)

        # webkit view with transparent background
        wv = WebKit2.WebView()
        wv.set_background_color(Gdk.RGBA(0, 0, 0, 0))

        settings = wv.get_settings()
        settings.set_enable_javascript(True)

        # message handler — receives action from JS
        mgr = wv.get_user_content_manager()
        mgr.connect('script-message-received::nebula', self.on_message)
        mgr.register_script_message_handler('nebula')

        wv.load_html(HTML, 'file:///')
        self.add(wv)
        self.show_all()

    def on_key(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()

    def on_message(self, mgr, result):
        action = result.get_js_value().to_string()
        cmd = COMMANDS.get(action)
        Gtk.main_quit()
        if cmd:
            subprocess.Popen(cmd)

if __name__ == '__main__':
    app = PowerMenu()
    Gtk.main()
