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
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

APP_NAME = "STL Repair"
OUT_DIR = Path.home() / "Downloads" / "STL Repaired"

# ---------------------------------------------------------------- page

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>STL Repair</title>
<style>
  :root{
    --bg:#f6f7f9; --panel:#fff; --ink:#14181f; --muted:#5d6675;
    --line:#e2e6ec; --accent:#2f6df6; --accent-soft:#eaf1ff;
    --ok:#0f8a4f; --warn:#b06a00; --bad:#c8362c; --shadow:0 1px 3px rgba(16,24,40,.07);
  }
  @media (prefers-color-scheme:dark){
    :root:not([data-theme="light"]){
      --bg:#0f1115; --panel:#171a21; --ink:#e8ecf2; --muted:#98a2b3;
      --line:#262b35; --accent:#5b8dff; --accent-soft:#1b2740;
      --ok:#3ecf8e; --warn:#e0a44a; --bad:#f2695c; --shadow:none;
    }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;
    padding:32px 20px 60px}
  .wrap{max-width:780px;margin:0 auto}
  header{border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:16px}
  h1{font-size:26px;margin:0 0 5px;letter-spacing:-.02em;font-weight:680}
  .by{font-size:13.5px;color:var(--muted)}
  .by a{color:var(--accent);text-decoration:none;font-weight:600}
  .by a.mute{color:var(--muted);font-weight:400}
  .by a:hover{text-decoration:underline}
  .by .dot{margin:0 7px;opacity:.5}
  .sub{color:var(--muted);font-size:13.5px;margin-bottom:22px}
  .about{margin-top:38px;padding-top:26px;border-top:1px solid var(--line)}
  .about h2{font-size:14px;margin:0 0 7px;letter-spacing:.02em;
    text-transform:uppercase;color:var(--muted);font-weight:650}
  .about p{margin:0 0 22px;font-size:14px;line-height:1.62;color:var(--ink);
    max-width:66ch}
  .about b{font-weight:620}
  .share{background:var(--accent-soft);border-radius:10px;padding:12px 16px;
    font-size:13.5px;color:var(--muted)}
  .share a{display:block;color:var(--accent);font-weight:640;text-decoration:none;
    padding:3px 0}
  .share a:hover{text-decoration:underline}
  #drop{background:var(--panel);border:2px dashed var(--line);border-radius:14px;
    padding:44px 24px;text-align:center;transition:.15s;cursor:pointer;box-shadow:var(--shadow)}
  #drop:hover{border-color:var(--accent)}
  #drop.over{border-color:var(--accent);background:var(--accent-soft)}
  #drop .big{font-size:17px;font-weight:600;margin-bottom:6px}
  #drop .small{color:var(--muted);font-size:13px}
  .btn{display:inline-block;margin-top:14px;background:var(--accent);color:#fff;
    border:0;border-radius:8px;padding:9px 18px;font-size:14px;font-weight:550;cursor:pointer}
  .btn.ghost{background:transparent;color:var(--accent);border:1px solid var(--line)}
  input[type=file]{display:none}
  .row{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    padding:14px 16px;margin-top:12px;box-shadow:var(--shadow)}
  .row h3{margin:0;font-size:14.5px;font-weight:600;display:flex;
    justify-content:space-between;gap:12px;align-items:baseline}
  .tag{font-size:11.5px;font-weight:600;padding:2px 8px;border-radius:20px;white-space:nowrap}
  .t-run{background:var(--accent-soft);color:var(--accent)}
  .t-ok{background:color-mix(in srgb,var(--ok) 15%,transparent);color:var(--ok)}
  .t-warn{background:color-mix(in srgb,var(--warn) 18%,transparent);color:var(--warn)}
  .t-bad{background:color-mix(in srgb,var(--bad) 15%,transparent);color:var(--bad)}
  .bar{height:4px;background:var(--line);border-radius:3px;margin-top:10px;overflow:hidden}
  .bar>i{display:block;height:100%;width:0;background:var(--accent);transition:width .2s}
  table{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}
  td{padding:3px 0;color:var(--muted)}
  td+td{text-align:right;color:var(--ink);font-variant-numeric:tabular-nums;width:88px}
  .fixes{margin:8px 0 0;padding-left:18px;font-size:13px;color:var(--muted)}
  .note{font-size:12.5px;color:var(--warn);margin-top:8px}
  .foot{margin-top:26px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .foot span{color:var(--muted);font-size:12.5px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>STL Repair</h1>
    <div class="by">By <a href="https://youtube.com/@davetriesthis" target="_blank"
        rel="noopener">Dave Tries This</a> and
      <a href="https://youtube.com/@agentbaltic" target="_blank"
        rel="noopener">Agent Baltic</a></div>
  </header>

  <div class="sub">Makes 3D-print files watertight. No size limit &middot; nothing leaves this Mac.</div>

  <div id="drop">
    <div class="big">Drag STL files here</div>
    <div class="small">or click to choose &mdash; STL, OBJ, PLY, 3MF</div>
    <button class="btn" id="pick">Choose files</button>
    <input type="file" id="file" multiple accept=".stl,.obj,.ply,.off,.3mf,.glb">
  </div>

  <div id="list"></div>

  <div class="foot">
    <button class="btn ghost" id="reveal">Open results folder</button>
    <span id="where"></span>
  </div>

  <section class="about">
    <h2>Why this exists</h2>
    <p>Mesh repair has always been the weak spot in a Mac 3D-printing setup. The
    desktop tools everyone recommends are Windows-only, which leaves Mac users
    on browser-based repair services &mdash; and those cap what you can upload,
    commonly around 50&nbsp;MB. A detailed sculpt or a scanned part sails past
    that limit long before it stops being an ordinary file, and you are
    handing your model to someone else's server to get it back. <b>Mac STL
    Repair runs natively on your own machine.</b> No upload, no queue, no size
    ceiling, and nothing ever leaves your Mac.</p>

    <h2>How to use it</h2>
    <p>Drag one or more files onto the box above. Each is welded and checked,
    then repaired &mdash; holes closed, non-manifold edges resolved, flipped
    normals corrected, stray fragments dropped. Repaired copies are written to
    <b>Downloads &rsaquo; STL Repaired</b> and your originals are never
    modified. The card that appears shows before and after: when
    <b>Watertight</b> and <b>Manifold</b> both read <i>yes</i>, the file is
    ready to slice. If a note says triangles were added, glance at that area
    first &mdash; closing a hole means inventing new surface, and the app
    fills it plausibly rather than knowing what was originally there.</p>

    <div class="share">
      <a href="https://resources.agentbaltic.com/b/b3dVI" target="_blank"
         rel="noopener">Download The Latest Version</a>
      <a href="https://youtube.com/@davetriesthis" target="_blank"
         rel="noopener">Watch the Dave Tries This YouTube channel</a>
      <a href="https://youtube.com/@agentbaltic" target="_blank"
         rel="noopener">Watch the Agent Baltic YouTube channel</a>
    </div>
  </section>
</div>
<script>
const drop=document.getElementById('drop'), inp=document.getElementById('file'),
      list=document.getElementById('list');
document.getElementById('where').textContent='Saved to '+OUTDIR;
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
  row.innerHTML='<h3><span>'+esc(file.name)+'</span><span class="tag t-run">uploading</span></h3>'+
                '<div class="bar"><i></i></div>';
  list.prepend(row);
  const tag=row.querySelector('.tag'), bar=row.querySelector('.bar>i');

  const x=new XMLHttpRequest();
  x.open('POST','/repair');
  x.setRequestHeader('X-Filename',encodeURIComponent(file.name));
  x.upload.onprogress=e=>{ if(e.lengthComputable) bar.style.width=(e.loaded/e.total*92)+'%' };
  x.upload.onload=()=>{ bar.style.width='96%'; tag.textContent='repairing'; };
  x.onload=()=>{
    bar.parentElement.remove();
    let r; try{ r=JSON.parse(x.responseText) }catch(_){ r={ok:false,error:'bad response'} }
    render(row,tag,r);
    busy=false; pump();
  };
  x.onerror=()=>{ bar.parentElement.remove(); tag.className='tag t-bad';
    tag.textContent='failed'; busy=false; pump(); };
  x.send(file);
}

function render(row,tag,r){
  if(!r.ok){ tag.className='tag t-bad'; tag.textContent='error';
    row.insertAdjacentHTML('beforeend','<ul class="fixes"><li>'+esc(r.error||'failed')+'</li></ul>');
    return; }
  const b=r.before,a=r.after;
  if(r.healthy_after){ tag.className='tag t-ok';
    tag.textContent=r.was_healthy?'already fine':'repaired'; }
  else { tag.className='tag t-warn'; tag.textContent='partly fixed'; }

  let h='<table>'+
    tr('Watertight', yn(b.watertight), yn(a.watertight))+
    tr('Manifold', yn(b.nonmanifold_edges===0), yn(a.nonmanifold_edges===0))+
    tr('Open edges', n(b.boundary_edges), n(a.boundary_edges))+
    tr('Shells', b.components, a.components)+
    tr('Triangles', n(b.faces), n(a.faces))+
    '</table>';
  if(r.fixes && r.fixes.length)
    h+='<ul class="fixes">'+r.fixes.map(f=>'<li>'+esc(f)+'</li>').join('')+'</ul>';
  if(r.warning) h+='<div class="note">'+esc(r.warning)+'</div>';
  h+='<ul class="fixes"><li>Saved as <b>'+esc(r.output_name)+'</b> &middot; '+
     esc(r.size)+' &middot; '+r.seconds+'s</li>'+
     '<li>Size: '+a.bbox_mm.join(' &times; ')+' mm</li></ul>';
  row.insertAdjacentHTML('beforeend',h);
}
function tr(k,x,y){return '<tr><td>'+k+'</td><td>'+x+'</td><td>'+y+'</td></tr>'}
function yn(v){return v?'yes':'no'}

document.getElementById('reveal').onclick=()=>fetch('/reveal',{method:'POST'});
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

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = PAGE.replace(
                "OUTDIR", json.dumps(str(OUT_DIR).replace(str(Path.home()), "~")))
            self._send(200, page.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"{}")

    def do_POST(self):
        if self.path == "/reveal":
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(OUT_DIR)])
            return self._send(200, b'{"ok":true}')

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
    # Import the heavy libraries once, up front, so the first drop is not slow.
    import stlrepair  # noqa: F401

    srv = Server(("127.0.0.1", 0), Handler)
    port = srv.socket.getsockname()[1]
    url = f"http://127.0.0.1:{port}/"

    print(f"{APP_NAME} running at {url}")
    print(f"Repaired files go to {OUT_DIR}")
    print("Quit this app (or close this window) when you are done.")

    threading.Thread(target=lambda: (time.sleep(0.4), webbrowser.open(url)),
                     daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
