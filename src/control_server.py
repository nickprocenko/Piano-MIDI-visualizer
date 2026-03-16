"""Local HTTP control panel — runs in a background daemon thread.

Opens on http://localhost:8181/ while the app is running.
The main thread queues patches via App._control_patches; the HTTP handler
only writes to that queue so there are no cross-thread mutations.
"""

from __future__ import annotations

import json
import queue
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable

PORT = 8181


def _make_handler(
    patch_queue: queue.SimpleQueue,
    get_state: Callable[[], dict],
) -> type:
    """Return a handler class bound to the given queue and state reader."""

    class Handler(BaseHTTPRequestHandler):
        _pq = patch_queue
        _gs = get_state

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # suppress access-log spam

        # ------------------------------------------------------------------
        def do_OPTIONS(self) -> None:
            self.send_response(200)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path == "/":
                self._serve_html()
            elif self.path == "/api/settings":
                self._json_ok(self._gs())
            elif self.path == "/api/themes":
                self._serve_themes()
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
            except Exception:
                self.send_error(400)
                return

            if self.path == "/api/patch":
                self._pq.put(data)
                self._json_ok({"ok": True})
            else:
                self.send_error(404)

        # ------------------------------------------------------------------
        def _serve_themes(self) -> None:
            try:
                import src.themes as themes_mod
                themes = themes_mod.load_user_themes()
                active = themes_mod.get_active_index()
            except Exception:
                themes, active = [], 0
            self._json_ok({"themes": themes, "active_index": active})

        def _json_ok(self, data: Any) -> None:
            body = json.dumps(data).encode()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")

        def _serve_html(self) -> None:
            body = _HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


class ControlServer:
    """Starts the background HTTP control panel on localhost:8181."""

    def __init__(
        self,
        patch_queue: queue.SimpleQueue,
        get_state: Callable[[], dict],
    ) -> None:
        self._patch_queue = patch_queue
        self._get_state = get_state
        self._server: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        handler_cls = _make_handler(self._patch_queue, self._get_state)

        class _TCPServer(socketserver.TCPServer):
            allow_reuse_address = True

        try:
            server = _TCPServer(("127.0.0.1", PORT), handler_cls)
        except OSError:
            # Port already in use — skip silently rather than crashing the app.
            return
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()


# ---------------------------------------------------------------------------
# Embedded HTML control panel
# ---------------------------------------------------------------------------

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Piano Visualizer Control</title>
<style>
:root {
  --bg: #0f0f14;
  --panel: #16161e;
  --accent: #00b4b4;
  --text: #d2d2d2;
  --muted: #969696;
  --border: #505060;
  --btn-bg: #232330;
  --btn-hover: #3c3c50;
  --on-bg: #1a3a1a;
  --on-color: #6ed76e;
  --off-bg: #3a1a1a;
  --off-color: #dc8c8c;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; min-height: 100vh; }
header { background: var(--panel); border-bottom: 1px solid var(--border); padding: 12px 20px; display: flex; align-items: center; gap: 12px; position: sticky; top: 0; z-index: 10; }
header h1 { font-size: 17px; font-weight: 700; color: var(--accent); letter-spacing: 0.5px; }
#status { font-size: 12px; color: var(--muted); margin-left: auto; }
.main { max-width: 960px; margin: 0 auto; padding: 18px; display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.section { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.section.full { grid-column: 1 / -1; }
.section h2 { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--accent); margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 7px; }
.row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.row:last-child { margin-bottom: 0; }
.row label { width: 148px; min-width: 148px; color: var(--muted); font-size: 13px; }
.row input[type=range] { flex: 1; accent-color: var(--accent); cursor: pointer; height: 4px; }
.row .val { width: 38px; text-align: right; font-size: 13px; font-variant-numeric: tabular-nums; }
.color-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.color-row label { width: 148px; min-width: 148px; color: var(--muted); font-size: 13px; }
.color-row input[type=color] { width: 42px; height: 28px; border: 1px solid var(--border); border-radius: 4px; cursor: pointer; background: none; padding: 2px; }
.rgb-wrap { flex: 1; display: flex; flex-direction: column; gap: 5px; }
.rgb-wrap input[type=range] { width: 100%; height: 4px; cursor: pointer; }
.effects-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 7px; margin-bottom: 12px; }
.toggle-btn { padding: 8px 4px; border: 1px solid var(--border); border-radius: 5px; cursor: pointer; font-size: 12px; font-weight: 600; text-align: center; user-select: none; background: var(--btn-bg); color: var(--muted); }
.toggle-btn.active { background: var(--on-bg); color: var(--on-color); border-color: var(--on-color); }
.effects-sliders { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.theme-grid { display: flex; flex-wrap: wrap; gap: 8px; }
.theme-btn { padding: 8px 16px; border: 1px solid var(--border); border-radius: 5px; cursor: pointer; font-size: 13px; background: var(--btn-bg); color: var(--text); font-family: inherit; }
.theme-btn:hover { background: var(--btn-hover); }
.theme-btn.active { border-color: var(--accent); color: var(--accent); background: rgba(0,180,180,0.08); }
.vis-btn { padding: 6px 20px; border: 1px solid var(--border); border-radius: 5px; cursor: pointer; font-size: 13px; font-weight: 600; background: var(--off-bg); color: var(--off-color); font-family: inherit; }
.vis-btn.active { background: var(--on-bg); color: var(--on-color); border-color: var(--on-color); }
@media (max-width: 600px) {
  .main { grid-template-columns: 1fr; }
  .section.full { grid-column: 1; }
  .effects-grid { grid-template-columns: repeat(2, 1fr); }
  .effects-sliders { grid-template-columns: 1fr; }
  .row label, .color-row label { width: 120px; min-width: 120px; }
}
</style>
</head>
<body>
<header>
  <h1>Piano Visualizer Control</h1>
  <span id="status">Loading…</span>
</header>
<div class="main">

  <!-- Themes -->
  <div class="section full" id="sec-themes" style="display:none">
    <h2>Themes</h2>
    <div class="theme-grid" id="theme-btns"></div>
  </div>

  <!-- Color -->
  <div class="section">
    <h2>Color</h2>
    <div class="color-row">
      <label>Outer (note)</label>
      <input type="color" id="cp-outer">
      <div class="rgb-wrap">
        <input type="range" id="s-color_r" min="0" max="255" data-ns="color_r" style="accent-color:#ff6a6a">
        <input type="range" id="s-color_g" min="0" max="255" data-ns="color_g" style="accent-color:#6ed76e">
        <input type="range" id="s-color_b" min="0" max="255" data-ns="color_b" style="accent-color:#6a8aff">
      </div>
    </div>
    <div class="color-row">
      <label>Inner (glow)</label>
      <input type="color" id="cp-inner">
      <div class="rgb-wrap">
        <input type="range" id="s-interior_r" min="0" max="255" data-ns="interior_r" style="accent-color:#ff6a6a">
        <input type="range" id="s-interior_g" min="0" max="255" data-ns="interior_g" style="accent-color:#6ed76e">
        <input type="range" id="s-interior_b" min="0" max="255" data-ns="interior_b" style="accent-color:#6a8aff">
      </div>
    </div>
    <div class="row">
      <label>Inner Blend %</label>
      <input type="range" id="s-inner_blend_percent" min="0" max="100" step="5" data-ns="inner_blend_percent">
      <span class="val" id="v-inner_blend_percent"></span>
    </div>
    <div class="row">
      <label>Outer Edge Width</label>
      <input type="range" id="s-outer_edge_width_px" min="1" max="8" step="1" data-ns="outer_edge_width_px">
      <span class="val" id="v-outer_edge_width_px"></span>
    </div>
    <div class="row">
      <label>Glow Strength %</label>
      <input type="range" id="s-glow_strength_percent" min="0" max="180" step="5" data-ns="glow_strength_percent">
      <span class="val" id="v-glow_strength_percent"></span>
    </div>
  </div>

  <!-- Motion & Shape -->
  <div class="section">
    <h2>Motion &amp; Shape</h2>
    <div class="row">
      <label>Rise Speed</label>
      <input type="range" id="s-speed_px_per_sec" min="80" max="1200" step="20" data-ns="speed_px_per_sec">
      <span class="val" id="v-speed_px_per_sec"></span>
    </div>
    <div class="row">
      <label>Decay Speed</label>
      <input type="range" id="s-decay_speed" min="0" max="240" step="5" data-ns="decay_speed">
      <span class="val" id="v-decay_speed"></span>
    </div>
    <div class="row">
      <label>Decay Value</label>
      <input type="range" id="s-decay_value" min="0" max="100" step="5" data-ns="decay_value">
      <span class="val" id="v-decay_value"></span>
    </div>
    <div class="row">
      <label>Note Width</label>
      <input type="range" id="s-width_px" min="4" max="40" step="1" data-ns="width_px">
      <span class="val" id="v-width_px"></span>
    </div>
    <div class="row">
      <label>Edge Roundness</label>
      <input type="range" id="s-edge_roundness_px" min="0" max="20" step="1" data-ns="edge_roundness_px">
      <span class="val" id="v-edge_roundness_px"></span>
    </div>
  </div>

  <!-- Effects -->
  <div class="section full">
    <h2>Effects</h2>
    <div class="effects-grid">
      <div class="toggle-btn" data-ns-toggle="effect_glow_enabled">Glow</div>
      <div class="toggle-btn" data-ns-toggle="effect_highlight_enabled">Edge Highlight</div>
      <div class="toggle-btn" data-ns-toggle="effect_sparks_enabled">Sparks</div>
      <div class="toggle-btn" data-ns-toggle="effect_smoke_enabled">Smoke</div>
      <div class="toggle-btn" data-ns-toggle="effect_press_smoke_enabled">Start Mist</div>
      <div class="toggle-btn" data-ns-toggle="effect_moon_dust_enabled">Moon Dust</div>
      <div class="toggle-btn" data-ns-toggle="effect_steam_smoke_enabled">Steam Wisps</div>
      <div class="toggle-btn" data-ns-toggle="effect_halo_pulse_enabled">Halo Pulse</div>
    </div>
    <div class="effects-sliders">
      <div class="row" style="margin-bottom:0">
        <label>Highlight Strength %</label>
        <input type="range" id="s-highlight_strength_percent" min="0" max="170" step="5" data-ns="highlight_strength_percent">
        <span class="val" id="v-highlight_strength_percent"></span>
      </div>
      <div class="row" style="margin-bottom:0">
        <label>Spark Amount %</label>
        <input type="range" id="s-spark_amount_percent" min="0" max="300" step="5" data-ns="spark_amount_percent">
        <span class="val" id="v-spark_amount_percent"></span>
      </div>
      <div class="row" style="margin-bottom:0">
        <label>Smoke Amount %</label>
        <input type="range" id="s-smoke_amount_percent" min="0" max="300" step="5" data-ns="smoke_amount_percent">
        <span class="val" id="v-smoke_amount_percent"></span>
      </div>
      <div class="row" style="margin-bottom:0">
        <label>Start Mist Amount %</label>
        <input type="range" id="s-press_smoke_amount_percent" min="0" max="250" step="5" data-ns="press_smoke_amount_percent">
        <span class="val" id="v-press_smoke_amount_percent"></span>
      </div>
    </div>
  </div>

  <!-- Keyboard -->
  <div class="section">
    <h2>Keyboard</h2>
    <div class="row">
      <label>Height %</label>
      <input type="range" id="s-height_percent" min="8" max="45" step="1" data-ks="height_percent">
      <span class="val" id="v-height_percent"></span>
    </div>
    <div class="row">
      <label>Brightness %</label>
      <input type="range" id="s-brightness" min="15" max="150" step="5" data-ks="brightness">
      <span class="val" id="v-brightness"></span>
    </div>
    <div class="row">
      <label>Visible</label>
      <button class="vis-btn" id="btn-visible">Hidden</button>
    </div>
  </div>

</div>
<script>
var timers = {}, settings = {};

function hex(r,g,b){ return '#'+[r,g,b].map(v=>v.toString(16).padStart(2,'0')).join(''); }
function setStatus(m){ document.getElementById('status').textContent = m; }

function populate(s){
  settings = s;
  var ns = s.note_style || {}, ks = s.keyboard_style || {};
  document.querySelectorAll('[data-ns]').forEach(function(el){
    var k=el.dataset.ns, v=ns[k];
    if(v===undefined) return;
    el.value = v;
    var ve = document.getElementById('v-'+k); if(ve) ve.textContent = v;
  });
  document.querySelectorAll('[data-ks]').forEach(function(el){
    var k=el.dataset.ks, v=ks[k];
    if(v===undefined) return;
    el.value = v;
    var ve = document.getElementById('v-'+k); if(ve) ve.textContent = v;
  });
  document.getElementById('cp-outer').value = hex(ns.color_r||0, ns.color_g||230, ns.color_b||230);
  document.getElementById('cp-inner').value = hex(ns.interior_r||120, ns.interior_g||255, ns.interior_b||255);
  document.querySelectorAll('[data-ns-toggle]').forEach(function(el){
    el.classList.toggle('active', !!(ns[el.dataset.nsToggle]));
  });
  var vis = ks.visible !== undefined ? ks.visible : true;
  var vb = document.getElementById('btn-visible');
  vb.classList.toggle('active', vis);
  vb.textContent = vis ? 'Visible' : 'Hidden';
}

function send(type, patch){
  fetch('/api/patch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:type,patch:patch})})
    .then(function(){ setStatus('Saved'); }).catch(function(){ setStatus('Send failed'); });
}
function debSend(key, type, patch, ms){
  clearTimeout(timers[key]);
  timers[key] = setTimeout(function(){ send(type, patch); }, ms||80);
}

// NS sliders
document.querySelectorAll('[data-ns]').forEach(function(el){
  el.addEventListener('input', function(){
    var k=el.dataset.ns, v=parseInt(el.value,10);
    var ve=document.getElementById('v-'+k); if(ve) ve.textContent=v;
    if(k==='color_r'||k==='color_g'||k==='color_b'){
      document.getElementById('cp-outer').value=hex(
        parseInt(document.getElementById('s-color_r').value,10),
        parseInt(document.getElementById('s-color_g').value,10),
        parseInt(document.getElementById('s-color_b').value,10));
    }
    if(k==='interior_r'||k==='interior_g'||k==='interior_b'){
      document.getElementById('cp-inner').value=hex(
        parseInt(document.getElementById('s-interior_r').value,10),
        parseInt(document.getElementById('s-interior_g').value,10),
        parseInt(document.getElementById('s-interior_b').value,10));
    }
    debSend(k,'note_style',{[k]:v});
  });
});

// KS sliders
document.querySelectorAll('[data-ks]').forEach(function(el){
  el.addEventListener('input', function(){
    var k=el.dataset.ks, v=parseInt(el.value,10);
    var ve=document.getElementById('v-'+k); if(ve) ve.textContent=v;
    debSend(k,'keyboard_style',{[k]:v});
  });
});

// Outer colour picker
document.getElementById('cp-outer').addEventListener('input', function(e){
  var h=e.target.value;
  var r=parseInt(h.slice(1,3),16),g=parseInt(h.slice(3,5),16),b=parseInt(h.slice(5,7),16);
  document.getElementById('s-color_r').value=r;
  document.getElementById('s-color_g').value=g;
  document.getElementById('s-color_b').value=b;
  debSend('outer_cp','note_style',{color_r:r,color_g:g,color_b:b});
});

// Inner colour picker
document.getElementById('cp-inner').addEventListener('input', function(e){
  var h=e.target.value;
  var r=parseInt(h.slice(1,3),16),g=parseInt(h.slice(3,5),16),b=parseInt(h.slice(5,7),16);
  document.getElementById('s-interior_r').value=r;
  document.getElementById('s-interior_g').value=g;
  document.getElementById('s-interior_b').value=b;
  debSend('inner_cp','note_style',{interior_r:r,interior_g:g,interior_b:b});
});

// Effect toggles
document.querySelectorAll('[data-ns-toggle]').forEach(function(el){
  el.addEventListener('click', function(){
    var k=el.dataset.nsToggle;
    var nv = el.classList.contains('active') ? 0 : 1;
    el.classList.toggle('active', !!nv);
    send('note_style',{[k]:nv});
  });
});

// Visibility
document.getElementById('btn-visible').addEventListener('click', function(){
  var btn=this, nv=!btn.classList.contains('active');
  btn.classList.toggle('active',nv);
  btn.textContent=nv?'Visible':'Hidden';
  send('keyboard_style',{visible:nv});
});

// Themes
function loadThemes(){
  fetch('/api/themes').then(function(r){ return r.json(); }).then(function(d){
    if(!d.themes||!d.themes.length) return;
    var sec=document.getElementById('sec-themes'); sec.style.display='';
    var cont=document.getElementById('theme-btns'); cont.innerHTML='';
    d.themes.forEach(function(t,i){
      var btn=document.createElement('button');
      btn.className='theme-btn'+(i===d.active_index?' active':'');
      btn.textContent=t.name||('Theme '+(i+1));
      btn.onclick=function(){
        fetch('/api/patch',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({type:'theme',index:i})})
          .then(function(){ setStatus('Theme applied'); setTimeout(function(){loadSettings();loadThemes();},350); });
      };
      cont.appendChild(btn);
    });
  }).catch(function(){});
}

function loadSettings(){
  fetch('/api/settings').then(function(r){ return r.json(); }).then(function(d){
    populate(d); setStatus('Ready');
  }).catch(function(){ setStatus('Cannot connect to app'); });
}

loadSettings();
loadThemes();
</script>
</body>
</html>
"""
