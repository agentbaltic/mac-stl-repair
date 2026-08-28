#!/usr/bin/env python3
"""
STL Repair - local drag-and-drop front end for stlrepair.

Starts a tiny web server bound to localhost and opens the default browser.
Nothing is uploaded anywhere: the "upload" is a loopback copy to a process
running on this Mac. Repaired files are written to ~/Downloads/STL Repaired.
"""

from __future__ import annotations

import http.server
import json
import os
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "STL Repair"
DEFAULT_OUT_DIR = Path.home() / "Downloads" / "STL Repaired"
PREFS_FILE = Path.home() / "Library" / "Application Support" / "STL Repair" / "prefs.json"


def _load_out_dir() -> Path:
    try:
        saved = json.loads(PREFS_FILE.read_text()).get("out_dir")
        if saved:
            return Path(saved)
    except Exception:
        pass
    return DEFAULT_OUT_DIR


def _save_out_dir(path: Path) -> None:
    try:
        PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PREFS_FILE.write_text(json.dumps({"out_dir": str(path)}))
    except Exception:
        pass


# Double-clicking the Dock icon while the app is already running is normal
# user behaviour, not a mistake. This app is a background HTTP server with
# no window of its own, so macOS has nothing to bring to the front for a
# second launch - without this check, the new process would sit there doing
# nothing visible, which looks exactly like a crash. So every launch checks
# for a live instance first: if one answers, just point the browser at it
# and exit immediately, before paying the cost of importing numpy/trimesh.
LOCK_FILE = Path.home() / "Library" / "Application Support" / "STL Repair" / "server.json"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just owned by someone else
    except Exception:
        return False


def _running_instance_url() -> str | None:
    """Return the URL of an already-running, responsive instance, if any."""
    try:
        info = json.loads(LOCK_FILE.read_text())
        pid, port = int(info["pid"]), int(info["port"])
    except Exception:
        return None
    if not _pid_alive(pid):
        return None
    url = f"http://127.0.0.1:{port}/"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as r:
            if r.status == 200 and b"Mac STL Repair" in r.read(4096):
                return url
    except Exception:
        pass
    return None


def _write_lock(port: int) -> None:
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOCK_FILE.write_text(json.dumps({"pid": os.getpid(), "port": port}))
    except Exception:
        pass


def _clear_lock() -> None:
    try:
        info = json.loads(LOCK_FILE.read_text())
        if int(info.get("pid", -1)) == os.getpid():
            LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


OUT_DIR = None  # set in main(), after imports are settled

# ---------------------------------------------------------------- page

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mac STL Repair</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
  :root{
    --ink:#1a1a1a; --cream:#f7f5f0; --amber:#e3a945; --teal:#2a9e76; --teal-dark:#1f7a5a;
    --slate:#4a5568; --ochre:#96742a; --rust:#b85c1a; --violet:#7a2eac;
    --hairline:#e5e5e5; --drop-border:#d8d2c4;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--cream);color:var(--ink);
    font-family:Inter,-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;
    font-size:15.5px;line-height:1.65;-webkit-font-smoothing:antialiased}
  .wrap{max-width:1120px;margin:0 auto;padding:0 24px}
  section.pad{padding:clamp(40px,6vw,80px) 0}
  a{color:var(--teal);text-decoration:none}
  a:hover{color:var(--teal-dark);text-decoration:underline}
  .eyebrow{font-weight:800;font-size:12px;letter-spacing:.16em;text-transform:uppercase;
    color:var(--ochre);margin-bottom:12px}
  h1{font-weight:900;font-size:clamp(34px,4.6vw,58px);letter-spacing:-.04em;line-height:1;margin:0 0 16px}
  .by{font-size:14px;color:var(--slate);font-weight:500}
  .by b{font-weight:700;color:var(--ink)}
  h2{font-weight:800;font-size:clamp(24px,2.6vw,32px);letter-spacing:-.02em;margin:0 0 10px}
  .lede{font-size:17px;color:var(--slate);margin:18px 0 34px;max-width:56ch}

  .card{background:#fff;border:1px solid var(--hairline);border-radius:16px}

  #drop{background:#fff;border:2px dashed var(--drop-border);border-radius:16px;
    padding:clamp(36px,6vw,56px) 24px;text-align:center;cursor:pointer;transition:.15s}
  #drop:hover{border-color:var(--amber)}
  #drop.over{border-color:var(--amber);background:#fdf6e8}
  #drop .big{font-size:20px;font-weight:800;letter-spacing:-.02em;margin-bottom:6px}
  #drop .small{color:var(--slate);font-size:13.5px}
  input[type=file]{display:none}

  .btn{display:inline-flex;align-items:center;justify-content:center;font-family:inherit;
    cursor:pointer;border-radius:100px;font-weight:800;letter-spacing:-.01em}
  .btn-primary{background:var(--ink);color:#fff;border:0;height:52px;padding:0 26px;font-size:15.5px}
  .btn-primary:hover{background:#000}
  .btn-secondary{background:transparent;color:var(--ink);border:1.5px solid var(--ink);
    height:52px;padding:0 26px;font-size:15.5px}
  .btn-secondary:hover{background:#fff}
  .btn-cta{background:var(--amber);color:var(--ink);border:0;height:40px;padding:0 18px;font-size:13.5px}
  .btn-cta:hover{background:#d99a36}
  .btn[disabled]{opacity:.6;cursor:default}

  .dest{margin-top:24px;display:flex;gap:14px;align-items:center;flex-wrap:wrap;
    font-size:13.5px;color:var(--slate)}
  .dest .path{font-weight:700;color:var(--ink);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}

  .row{background:#fff;border:1px solid var(--hairline);border-radius:16px;
    padding:20px 22px;margin-top:14px}
  .row h3{margin:0;display:flex;justify-content:space-between;gap:12px;align-items:center}
  .row h3 span:first-child{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
    font-size:14.5px;font-weight:600}

  .badge{display:inline-flex;align-items:center;gap:5px;height:30px;padding:0 14px;
    border-radius:100px;font-weight:800;font-size:13px;white-space:nowrap}
  .b-fixed{background:#e8f6f0;color:var(--teal-dark)}
  .b-partial{background:#fbf0da;color:var(--ochre)}
  .b-open{background:#f7e7db;color:var(--rust)}
  .b-run{background:#fbf0da;color:var(--ochre)}

  .bar{height:5px;background:#f0ece1;border-radius:100px;margin-top:14px;overflow:hidden}
  .bar>i{display:block;height:100%;width:0;background:var(--amber);transition:width .2s}

  table{width:100%;border-collapse:collapse;margin-top:16px;font-size:13.5px}
  td{padding:7px 9px;color:var(--slate);border-bottom:1px solid var(--hairline)}
  tr:last-child td{border-bottom:0}
  tr:first-child td{padding-top:0}
  td+td{text-align:right;font-variant-numeric:tabular-nums;width:88px;font-weight:600}
  .good{color:var(--teal-dark)!important;font-weight:800!important}
  .bad{color:var(--rust)!important;font-weight:800!important}
  .fixes{margin:14px 0 0;padding-left:22px;font-size:13.5px;color:var(--slate);list-style:none}
  .fixes li{margin:3px 0;position:relative}
  .fixes li.fix::before{content:"✓";position:absolute;left:-22px;color:var(--teal-dark);font-weight:800}
  .fixes li.meta{padding-left:0}
  .note{font-size:13px;color:var(--rust);margin-top:12px;background:#f7e7db;
    padding:10px 14px;border-radius:9px;line-height:1.55}

  .info{margin-top:18px;padding:26px 28px}
  .info p{margin:0;color:var(--slate);max-width:640px}
  .info b{color:var(--ink);font-weight:700}

  .promo{background:var(--violet);border-radius:16px;padding:26px 28px;margin-top:18px}
  .promo .k{font-weight:800;font-size:12px;letter-spacing:.16em;text-transform:uppercase;
    color:#fff;opacity:.75;margin-bottom:8px}
  .promo p{margin:0;color:#fff;font-size:clamp(15.5px,1.6vw,23px);font-weight:700;
    line-height:1.5;max-width:60ch}
  .promo a{color:#fff;text-decoration:underline;text-underline-offset:3px}

  footer{background:var(--ink);margin-top:8px}
  footer .wrap{padding:28px 24px;display:flex;justify-content:space-between;
    align-items:center;flex-wrap:wrap;gap:12px}
  footer, footer a{color:#a8a8a8;font-size:13.5px}
  footer b{color:#fff}
  footer .credit a{color:var(--amber);font-weight:700}
  footer .credit a:hover{color:#f0c26e}
</style>
</head>
<body>
<div class="wrap pad">
  <h1>Mac STL Repair</h1>
  <div class="by">By <b>Dave Tries This</b> &mdash;
    <a href="https://youtube.com/@davetriesthis" target="_blank" rel="noopener">youtube.com/@davetriesthis</a></div>

  <p class="lede">Makes 3D-print files watertight. No size limit &middot; nothing leaves this Mac.</p>

  <div id="drop">
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" style="margin:0 auto 14px;display:block;"><path d="M12 3v12m0-12l-4 4m4-4l4 4M5 17v2a2 2 0 002 2h10a2 2 0 002-2v-2" stroke="#96742a" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
    <div class="big">Drag STL files here</div>
    <div class="small">or click to choose &mdash; STL, OBJ, PLY, 3MF</div>
    <button class="btn btn-primary" id="pick" style="margin-top:18px">Choose files</button>
    <input type="file" id="file" multiple accept=".stl,.obj,.ply,.off,.3mf,.glb">
  </div>

  <div class="dest">
    <span>Saving to</span><span class="path" id="where">&hellip;</span>
    <button class="btn btn-secondary" id="change" style="height:36px;padding:0 16px;font-size:12.5px">Change&hellip;</button>
    <button class="btn btn-secondary" id="reveal" style="height:36px;padding:0 16px;font-size:12.5px">Open results folder</button>
  </div>

  <div id="list"></div>
</div>

<div class="wrap">
  <section class="pad" style="padding-top:8px">
    <div class="card info">
      <div class="eyebrow">Why this exists</div>
      <p>Mesh repair has always been the weak spot in a Mac 3D-printing setup. The
      desktop tools everyone recommends are Windows-only, which leaves Mac users
      on browser-based repair services &mdash; and those cap what you can upload,
      commonly around 50&nbsp;MB. A detailed sculpt or a scanned part sails past
      that limit long before it stops being an ordinary file, and you are
      handing your model to someone else's server to get it back. <b>Mac STL
      Repair runs natively on your own machine.</b> No upload, no queue, no size
      ceiling, and nothing ever leaves your Mac.</p>
    </div>

    <div class="card info" style="margin-top:16px">
      <div class="eyebrow">How to use it</div>
      <p>Drag one or more files onto the box above. Each is welded and checked,
      then repaired &mdash; holes closed, non-manifold edges resolved, flipped
      normals corrected, stray fragments dropped. Repaired copies are written to
      <b>Downloads &rsaquo; STL Repaired</b> and your originals are never
      modified. The card that appears shows before and after: when
      <b>Watertight</b> and <b>Manifold</b> both read <i>yes</i>, the file is
      ready to slice. If a note says triangles were added, glance at that area
      first &mdash; closing a hole means inventing new surface, and the app
      fills it plausibly rather than knowing what was originally there.</p>
    </div>

    <div style="margin-top:22px">
      <a class="btn btn-cta" href="https://rebrand.ly/stlrepair" target="_blank" rel="noopener">Share this tool &rarr; rebrand.ly/stlrepair</a>
    </div>

    <div class="promo">
      <div class="k">From the same workshop</div>
      <p>Try our teleprompter app, <a href="https://talkoverapp.com" target="_blank" rel="noopener">TalkOver</a>.
      It follows your voice, floats over your screen, makes recordings of your
      presentations, and has no subscription.</p>
    </div>
  </section>
</div>

<footer>
  <div class="wrap">
    <div>Mac STL Repair &middot; <b>By Dave Tries This</b> &mdash;
      <a href="https://youtube.com/@davetriesthis" target="_blank" rel="noopener">youtube.com/@davetriesthis</a></div>
    <div class="credit">By <a href="https://talkoverapp.com" target="_blank" rel="noopener"><b style="color:var(--amber)">AgentBaltic</b></a>
      &middot; <a href="https://talkoverapp.com" target="_blank" rel="noopener">talkoverapp.com</a></div>
  </div>
</footer>

<script>
const drop=document.getElementById('drop'), inp=document.getElementById('file'),
      list=document.getElementById('list'), where=document.getElementById('where');
where.textContent=OUTDIR;
document.getElementById('pick').onclick=e=>{e.stopPropagation();inp.click()};
drop.onclick=()=>inp.click();
inp.onchange=()=>{queue([...inp.files]);inp.value=''};
['dragenter','dragover'].forEach(t=>drop.addEventListener(t,e=>{
  e.preventDefault();drop.classList.add('over')}));
['dragleave','drop'].forEach(t=>drop.addEventListener(t,e=>{
  e.preventDefault();drop.classList.remove('over')}));
drop.addEventListener('drop',e=>queue([...e.dataTransfer.files]));

let q=[],busy=false;
function queue(fs){ fs.forEach(f=>q.push(f)); pump(); }
function pump(){ if(busy||!q.length)return; busy=true; send(q.shift()); }
function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function n(x){return Number(x).toLocaleString()}

function send(file){
  const row=document.createElement('div'); row.className='row';
  row.innerHTML='<h3><span>'+esc(file.name)+'</span><span class="badge b-run">Repairing&hellip;</span></h3>'+
                '<div class="bar"><i></i></div>';
  list.prepend(row);
  const badge=row.querySelector('.badge'), bar=row.querySelector('.bar>i');
  const x=new XMLHttpRequest();
  x.open('POST','/repair');
  x.setRequestHeader('X-Filename',encodeURIComponent(file.name));
  x.upload.onprogress=e=>{ if(e.lengthComputable) bar.style.width=(e.loaded/e.total*92)+'%' };
  x.upload.onload=()=>{ bar.style.width='96%'; };
  x.onload=()=>{
    bar.parentElement.remove();
    let r; try{ r=JSON.parse(x.responseText) }catch(_){ r={ok:false,error:'bad response'} }
    render(row,badge,r); busy=false; pump();
  };
  x.onerror=()=>{ bar.parentElement.remove(); badge.className='badge b-open';
    badge.textContent='! Failed'; busy=false; pump(); };
  x.send(file);
}

function render(row,badge,r){
  if(!r.ok){ badge.className='badge b-open'; badge.textContent='! Failed';
    row.insertAdjacentHTML('beforeend','<ul class="fixes"><li class="meta">'+esc(r.error||'failed')+'</li></ul>');
    return; }
  const b=r.before,a=r.after;
  if(r.healthy_after){ badge.className='badge b-fixed';
    badge.textContent=r.was_healthy?'✓ Already fine':'✓ Fixed'; }
  else { badge.className='badge b-open'; badge.textContent='! Still open'; }

  let h='<table>'+
    tr('Watertight', yn(b.watertight), yn(a.watertight))+
    tr('Manifold', yn(b.nonmanifold_edges===0), yn(a.nonmanifold_edges===0))+
    tr('Open edges', n(b.boundary_edges), n(a.boundary_edges))+
    tr('Shells', b.components, a.components)+
    tr('Triangles', n(b.faces), n(a.faces))+
    '</table>';
  if(r.fixes && r.fixes.length)
    h+='<ul class="fixes">'+r.fixes.map(f=>'<li class="fix">'+esc(f)+'</li>').join('')+'</ul>';
  if(r.warning) h+='<div class="note">'+esc(r.warning)+'</div>';
  h+='<ul class="fixes"><li class="meta">Saved as <b>'+esc(r.output_name)+'</b> &middot; '+
     esc(r.size)+' &middot; '+r.seconds+'s</li>'+
     '<li class="meta">Size: '+a.bbox_mm.join(' &times; ')+' mm</li></ul>';
  row.insertAdjacentHTML('beforeend',h);
}
function tr(k,x,y){
  const cls = y==='yes' ? ' class="good"' : (y==='no' ? ' class="bad"' : '');
  return '<tr><td>'+k+'</td><td>'+x+'</td><td'+cls+'>'+y+'</td></tr>';
}
function yn(v){return v?'yes':'no'}

document.getElementById('reveal').onclick=()=>fetch('/reveal',{method:'POST'});
document.getElementById('change').onclick=()=>{
  const btn=document.getElementById('change'); btn.disabled=true; btn.textContent='Choosing…';
  fetch('/choose-folder',{method:'POST'}).then(r=>r.json()).then(j=>{
    if(j.ok) where.textContent=j.display;
    btn.disabled=false; btn.textContent='Change…';
  }).catch(()=>{ btn.disabled=false; btn.textContent='Change…'; });
};
</script>
</body></html>
"""


# ------------------------------------------------------------- repair glue

class Opts:
    """Mirrors the CLI defaults that repair_mesh() reads."""
    merge_tol = 1e-8
    force = False
    filler = "auto"
    no_meshfix = False
    parts = "separate"
    min_part_faces = 8


def human_size(b):
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024 or u == "GB":
            return f"{b:.1f} {u}" if u != "B" else f"{b} B"
        b /= 1024


def repair_upload(tmp_path: Path, original_name: str) -> dict:
    import stlrepair as core

    t0 = time.time()
    log = core.Log(quiet=True)
    mesh = core.load_mesh(tmp_path)
    mesh, before, after = core.repair_mesh(mesh, Opts(), log)

    if len(mesh.faces) == 0:
        return {"ok": False, "error": "repair produced an empty mesh"}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / (Path(original_name).stem + "_repaired.stl")
    i = 2
    while dst.exists():
        dst = OUT_DIR / f"{Path(original_name).stem}_repaired_{i}.stl"
        i += 1
    mesh.export(str(dst), file_type="stl")

    # plain-language summary of what changed
    fixes = []
    closed = before["boundary_edges"] - after["boundary_edges"]
    if closed > 0:
        fixes.append(f"Closed {closed:,} open edges (holes)")
    nm = before["nonmanifold_edges"] - after["nonmanifold_edges"]
    if nm > 0:
        fixes.append(f"Fixed {nm:,} non-manifold edges")
    if before["components"] > after["components"]:
        fixes.append(f"Removed {before['components'] - after['components']} "
                     f"stray fragment(s)")
    if not before["winding_consistent"] and after["winding_consistent"]:
        fixes.append("Rebuilt inconsistent surface normals")
    if before["inverted"] and not after["inverted"]:
        fixes.append("Flipped inside-out normals")
    if before["degenerate_faces"]:
        fixes.append(f"Removed {before['degenerate_faces']:,} zero-area triangles")
    if before["duplicate_faces"]:
        fixes.append(f"Removed {before['duplicate_faces']:,} duplicate triangles")

    warning = None
    if before["watertight"] and after["watertight"] and before["volume_cm3"] > 0:
        d = (after["volume_cm3"] - before["volume_cm3"]) / before["volume_cm3"]
        if abs(d) > 0.01:
            warning = (f"Repair changed the solid volume by {d * 100:+.1f}% - "
                       f"check the shape before printing.")
    elif not before["watertight"] and after["faces"] > before["faces"]:
        warning = (f"{after['faces'] - before['faces']:,} triangles were added to "
                   f"close holes. Patched areas are reconstructed, not recovered - "
                   f"give them a look before printing.")

    return {
        "ok": True,
        "output_name": dst.name,
        "size": human_size(dst.stat().st_size),
        "seconds": round(time.time() - t0, 1),
        "healthy_after": core.is_healthy(after),
        "was_healthy": core.is_healthy(before),
        "fixes": fixes or ["Nothing needed fixing"],
        "warning": warning,
        "before": before,
        "after": after,
    }


# ------------------------------------------------------------------ server

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _display_path(self) -> str:
        return str(OUT_DIR).replace(str(Path.home()), "~", 1)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = PAGE.replace("OUTDIR", json.dumps(self._display_path()))
            self._send(200, page.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"{}")

    def do_POST(self):
        global OUT_DIR
        if self.path == "/reveal":
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(OUT_DIR)])
            return self._send(200, b'{"ok":true}')

        if self.path == "/choose-folder":
            # A page in a browser sandbox cannot pick a real filesystem folder,
            # so this asks the OS for one directly - a genuine Finder-style
            # open/save panel, not a browser download prompt.
            script = (
                'POSIX path of (choose folder with prompt '
                '"Save repaired STL files to:" default location '
                f'(POSIX file "{OUT_DIR}"))'
            )
            try:
                r = subprocess.run(["osascript", "-e", script],
                                   capture_output=True, text=True, timeout=120)
                chosen = r.stdout.strip()
                if r.returncode != 0 or not chosen:
                    return self._send(200, b'{"ok":false}')  # cancelled
                OUT_DIR = Path(chosen)
                OUT_DIR.mkdir(parents=True, exist_ok=True)
                _save_out_dir(OUT_DIR)
                return self._send(200, json.dumps(
                    {"ok": True, "display": self._display_path()}).encode())
            except Exception as e:
                return self._send(200, json.dumps(
                    {"ok": False, "error": str(e)}).encode())

        if self.path != "/repair":
            return self._send(404, b"{}")

        name = self.headers.get("X-Filename", "model.stl")
        from urllib.parse import unquote
        name = os.path.basename(unquote(name)) or "model.stl"
        length = int(self.headers.get("Content-Length", 0))

        # keep the original extension so the loader can infer the format
        ext = Path(name).suffix.lower() or ".stl"
        tmp = (Path(tempfile.gettempdir()) /
               f"stlrepair_{os.getpid()}_{time.time_ns()}{ext}")
        try:
            with open(tmp, "wb") as fh:
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    fh.write(chunk)
                    left -= len(chunk)
            result = repair_upload(tmp, name)
        except Exception as e:
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            tmp.unlink(missing_ok=True)

        self._send(200, json.dumps(result).encode())


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    global OUT_DIR

    already = _running_instance_url()
    if already:
        print(f"{APP_NAME} is already running at {already} - opening it.")
        webbrowser.open(already)
        return

    OUT_DIR = _load_out_dir()

    # Import the heavy libraries once, up front, so the first drop is not slow.
    import stlrepair  # noqa: F401

    srv = Server(("127.0.0.1", 0), Handler)
    port = srv.socket.getsockname()[1]
    url = f"http://127.0.0.1:{port}/"
    _write_lock(port)

    def _on_terminate(signum, frame):
        _clear_lock()
        os._exit(0)

    signal.signal(signal.SIGTERM, _on_terminate)

    print(f"{APP_NAME} running at {url}")
    print(f"Repaired files go to {OUT_DIR}")
    print("Quit this app (or close this window) when you are done.")

    threading.Thread(target=lambda: (time.sleep(0.4), webbrowser.open(url)),
                     daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _clear_lock()


if __name__ == "__main__":
    main()
