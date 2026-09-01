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
LAST_OUTPUT = None  # most recent repaired file, so "Open results folder" can select it

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
  .titlerow{display:flex;align-items:center;gap:18px;flex-wrap:wrap;
    margin-bottom:4px}
  .titlerow h1{margin:0}
  .by{display:flex;align-items:center;gap:11px;font-size:14px;color:var(--slate);
    font-weight:500;text-decoration:none;line-height:1.35;
    padding-left:18px;border-left:1px solid var(--line)}
  .by:hover{text-decoration:none}
  .by:hover .chan{text-decoration:underline}
  .by img{border-radius:50%;display:block;flex:none;width:46px;height:46px}
  .by b{font-weight:800;color:var(--ink)}
  .chan{color:var(--teal)}
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
  .hint{margin-top:9px;font-size:12.5px;color:var(--slate);line-height:1.5}

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
  <div class="titlerow">
    <h1>Mac STL Repair</h1>
    <a class="by" href="https://youtube.com/@agentbaltic" target="_blank" rel="noopener">
      <img class="ablogo" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAAAAAXNSR0IArs4c6QAAAHhlWElmTU0AKgAAAAgABAEaAAUAAAABAAAAPgEbAAUAAAABAAAARgEoAAMAAAABAAIAAIdpAAQAAAABAAAATgAAAAAAAABIAAAAAQAAAEgAAAABAAOgAQADAAAAAQABAACgAgAEAAAAAQAAAICgAwAEAAAAAQAAAIAAAAAAewEwQAAAAAlwSFlzAAALEwAACxMBAJqcGAAAQABJREFUeAHtnQecnVWZ/8+9d+70zCSTTELqpDeK9CYlgAqCWFGssLorKrZFXdR1/YirLv4ti6CwwKoIdlERUCRCFAiEDiGkkZ5J78n0mdv+v+9z3vfOe2fuDJMGWc2Zedspz3naec5zyvvemPu/FeJCN6EjqaOtP9Svueaa0gsvvLCuoiIxvLa25ojOzq766urKSWvXbjg+l8tNGTFi+Kj6+mE1wNi2bXvTli1bN8ZiseUNDaOfa2lpW1lWVrptz56mze3tma333XffTsHr6q++IK1C14yOtI5sEHdIX2KHNHYeOYTOAa45HTCYaz7ccccdVSeddOzEioqKYyoqyl+TTJbMTCTiE+LxxAgJtba0tLREwcVigMm5bDbrMpmMHQBJJBJ2xOO+mlwu69LptOvq6kpLWfZks5ktmUx2dSqVXtze3vFCe3v7gqefnr/qsssua80j0X0DnihpiC+KcMgqw6GsADARiRAQep6Js2bNKrnppuunV1dXn1VVVXm2hH1CSUlyXGVlRTIWoxhC9gJG2BIiMPY6SHkcSoGCSJlUPiZYGdfW1p5Kp1ONUopnW1vbHm5paXnkyis/vfShhx6i5UdDT2XopbzRzK/G/aGmAFGGIXAYZuGKK65IXnXVJ04cMmTwxWVlZeerVR9ZWVlZRmImk7Yjm903QfsaBn6Ox2NSihI7KNXW1tYpa7Gos7Nz9q5du++97rofPHPrrbemekAMFbqoFeuR9xV7PFQUADxKdHAt6D/nz39y6vDhIy6Reb+ktDR5bGVldYxWmEqlzJS/YpzqpyKsRDKZVBeTkDK05Lq6UvPVTfx269Ytvz322FOW9SiKVUMZCND6ymitVdf79GorAPV721po5hNLlix8XX193T+Xl5dfUFVVPQihq5XtsznvTfrBiaHbkHUyZWhtbWnu6Oi4f9u2nT+aMeOoB1Vj3qLpPlSEV9UivJoKQIuHCTDFGCNPu/zyy9/7ttra2o/LmXuthK+W3inznu/+lfX/TpBvIstQ5qQETs7jY3v27Lnx9tt/cZfo7IhQAQ/gBUT29CEi2Q7O7auhAL0Ixqm77bYfXlJXV/tZOXUn4nSpPz3kW/tARYJVkN9iow45jc/s3Lnnux/84L/8tofTGDaIgi5woHXsa75XWgEYvxPyfd+yZS++ftiw4f8xaFDVWaHgfZa/z3OoCM3NrY9s377161OnHv1AhFLkgSIQejqRPvYAn18pBQhbfd7cz5v3t8lTpkz5ioZy75Wpj/89tfiXk1FoEdQ1ZDWE/MXy5cu/evrp56yIlMMv4jjo1gDBHOyARkMMGp3B3K9ateyTxxxzzGNq+e8XM+L0kfs6Vj/YyB8M+NAKzdAOD+AFPIE3QX00FPgF38K4IOnAXg62BcDk4+Wiye7xxx+fMWXKuOvq6urOZyaO2bbDQRLWLCXd386dO2cvX9541WmnnbYkwhcUgIaKQhzwIePBUgDgIvy8CVuxYsk/jRgx4lsy+fUdHf1O46vYP2YoL6906hK2bdmy5erJk2f8JMKFsAvN8zOStl+3B6MLACbCR2Ozd9/9o0EbN669edy4MbdVVJQdFn4/4qJhwCN4Bc/gXZCdISL8DLvTfqDsXdKBtgD0WaG5ck888fCUqVOn/njIkKFndHa2/0P183snhsLc8g00bKxwu3bteHTZsmUfOvXUs5dHchR0q5H4fbo9kAoQ9lW2bLpgwXNnNzSMu72mZlBDR0f7PiH3j16ovLzCNTU1r127tvHyY445/uEIPw6YEhwoBSho+YsXv3hpQ8OYWzWbV8Pw7nDYdw4wb6BZxKa1a9dfMXPm0b+OQApHB/vlSR8IBUD4wDFEVq9e+tGRI0feIM82yYLN4bD/HGChSSOm1KZNmz41YcL0myMQ91sJ9tcJBIG88JcvX/yvI0eOulFz4IeFH5HS/t7SkOApvIXHEXhh6w8VIZI0sNv9sQC0fA7r80Fs7Ngx/6218hhj/MPhwHOAuQLtecitW7f+M1OmzPxepIZ99gn2VQGwHAjfbPzKlUs/Onr0qBsl/Phh4UfEchBuAyXIbtiw8eOTJhV0ByhBwSaagVS/L10ASoPJMfOzePH8S0ePHnmDNkUcFv5AOL6feWhg8Bqew/sIOBoj8twrme5V5qAyNI3KchrqndXQ0HArDh/bsg6HV4YD8Bqew3tkEKkVIYR+WSS679u9VQCETwefYzVPM1Y/Y6h32Nvvm8EHKwWew3tkgCyCesJ1F+Q0oLA3CoBm2fYlpig1w3e7du6MPTzOHxCfD0omeI8MkEWPaWN8AeT1smGgTiCKknf61q1dccuYcWOuaG/rsaiTE7hYkQUriweXMA1QAwnkHyiK3fAoEdbUHVvsDj4NLGd3aaAPtN30BZ/ye09XNw7cAduHispqt75x/a1jGyZ8JIzTNbTW3RkjieHtQClBm6yTf2nJwsuHj6i/oqO9yPSu0eQJK9iKby9kUCVpRdJJKhp83qJJfUSy1r53u8NDnHpepRqCtX/7FEL2CjZ6ZrrGuwV9IL9X0cABP+eQBTJBNhEQoT8Qiep9G2LYO6U7BuFbv//0o49OGzlq+HfkhNqW7OLM8ULTekYQwiq4hofUIJ8e5jswVxZSBg47xKfYFTj+2D/MsHaCzwsr9tJK3OD2holW7I1mgFtCR1xKkHVxWV5kg4wC2ABDCfr1B6C8v0A6osrccssVybETx35/UE3NMByQgTGHor0lXVxx+kPjlU07MC10b3DGSofHwMsZnnbKulQ65ZANMkJWAZTQ/Pcp597SKay/VI825FuxYtEnxjc0fB/h9y3AsG9H+cK6w7hCwIf+U9gie7bKA0cPkL0AwpnTfYUNr3MGq1SLR2vXNH5y4uQZP4jwGDkWfbm1T81QAbAxyHPnPjixflj9VwrfswN1iodGIgqKNIq/nH4pSyT0xfJIlr26DeHtVaF85ih9nsacaO2pDvnse3ETxasbXpR/AwfmYYGXfALhl8nk3NBhw74yd+7ciREoaFjRUUFftYYSNMdv0sRJX6uprRlWuIfPM8ULObyPVGm3fYHvma/wee/UprBssaduJhdLfbk4sPHMDRV6/+AV1udp3fvGEkLp5pVXgnQ642pqBw+bNLHha2EeXVGAokLqS0JgZMJftOiF8/RC5qWdxbz+SA0H4taz+kBA8jBCeN1MUvwBkF4BvAOH7gGD1Nne4YYMGXIpsosALToqKKYAId+yt9xyS7J+2NCvlpWVJ7QIFYH1Mrd7kfVlIB345P2UXr74IUxjVqMCbSRJ1A8b9lVkGDAxdMryJBBf8BBkpK8gc3bFisWXNowb96t0Si9lBondJj8f0esGXRn4UKxXcRvbFiuP88noY6Bhf/Hor54Ql/DaX94BpcHggZP2siA1SHSJZIlrbFz37smTp4U7iagB+doqLkB6WgAycGRvu+228rq6IZ+P6wXHbuFTxIe+RwL7J3ygR2UcrWdvhN8Tjsd6H8/FGBBIa29ximIQpS0afyDuNUVkH7cYXFvzeWQZwAwpyataTwWg77cxyZlnnvLWmpra47qK7ukL4URRzcOMRu73/cszONDZYigFtcPog8nsfSUySls/6PcJ3ujqO9UhO60VHHfm6ae8NZIN+SJnCz0VwFo/X+Ooqan5NDN+ecQKbrK9TTH2VgGi7FAL8fcW3eepP8FEBae9JvYGDfvjeP9ey6H22RZMnfUZQQ3RMmGlvXEKceu+kjefL6QhNEWqwuqxuqhPplOci8XgQ1jL3l2pq2cwFhIdHGTxRzeeURyRj4EJ81tR8tJVeujaRORqBg/6NDIN6qN7D0r4myA+rxUZ7ep9/cSJDbNFaYyxf5TBYeaIEikKgyNmqEdhHh7EEJjFyyEB6Z7v+BdjQAg7VIqY4JRK4Hz6pampye3Yucu1NLeojpzT52HckMG1rq6uxr7OoQ84FdRhAguYAFw/ZUoEiuqVlfjonReyIsNy3YlBTu9HeSGocSgdXHLwSGWSJUl7BRy4fQXK5suJN74yKvJ8gofgYfwJpAh3LRTg46NCVE3ilo61M85bVKAMuVWr152vXcUP+FL5SZp0dHIAiZlzMGzYkCvk+cf8K1z5KpRcBAMgKou+yeS+/OWvuBUrVrpyzUYhPII+leLOO+9cd+WVV9hnXbxiWFKfJxSoVB+H2LVzp7v7gTnuwQf/6pYsWeJ2797jUnwlRH9YgkHV1W7C+PHuzLPPchde+EY3btxYpfvvCoSMphJ98s09+tjj7tvf/q69g2cM1nd+PKM9GlAWUooChqMeL2xScu5LX/qiO/bYY9369evdF7/4JdfWyncewCYn2rrcBz7wfveud16ibxv47z8An7QwQNfGjRvdF77wJdch84xSssNn7Jgx7tpvfkO8anOf+9znXVNzs7dwQcGwQYCTKYbFe4yBAa/DeBpsqiulYeAg963/d62rqal25RUVMWSqYqEC0A2YRQgVwDdXxT777LzJ+h7PBV1d4UcsIJ7Da79u8iEkLVlSKgEtdPfc/UfXIQFBKEEf8xFj0m7r1q3u0ndfohY7WK0lLEUOYPq8nsisfXgpWVrhHnzgAXfddTe4BS+8KI3OGUNifJjJWkXOpVMdrrWlzWlvnHv4kUfd7bff4T525Ufd+97zbjEkpm3U0mWZQspinbZv3+7mzXvClZWXGX4hw0L5hML3WHXjGNNSdtAQnd7pV9mEKfVTTz2r9/j0XOJbLF8l27jxO+744453kydP0Odsgvch1MpzLIcHAZyffvoZvR3cZcqIwFoMLnyIu0ULl7hNWzY7nG+sgQWhEwv47/H28MArpxPYchBr91KqI0bUu4xg80GrTr2JjEyR7QknnL7CYPqsgaS8FEzC9fVHvKu6elC1mf4gp794BAuiggf64z/96T7X3NrmkvTPGn5wJEqTrryq0m3YtEnMf1KWoSKvqcECoyBkxCAUMqM03/K+/Z3vuo987ONu4eKlrlymHhjAQrAmUBOK9wl4e6aqqspt27rDfeXLX3Wf/8K/+1ev48ASbDGOK4zjJQvmyjnA03CVdSgR7IQsSlw4cxBfWhrkI11HvCShumERploWijxSplKlcZRXVkjJdrhvfOO/1AgQvkQmpfBl9BgENnWqRbrSinKXVHk7hA8BgZqPA0zDLxngKL9HefhkDjSUqxxWjTxl+ETif6nw0/cRFVdieSrEF75kBq7IEpki2wANLmYFAhUz5cleo69rVlWVvxPEiwa1pp6B7+Do02jugQf/aq2LdN/qYIF0WFSBBNYhncZPsBx27j55Q1mSLHXfu/777r//+3ohrQGrCPIbTLyJzbIXDgGJaEwnH40iwDgYmywpc7/85a/dNdd8VTigLCJPR1zLpiipdxw9ySgEeHZp1qyjrd3ML+vqdkiRO7TZhfgOmXN23mDiyU+IJ0SX6gMGfwSS9BUzdVdz3A9v/YkJx1s46OcQjlLgEuHuBePL4d9kRUtWc/hYy9bWVrMwHR2d1nI72ltdp7oGWrFVr2Jg4WHGpOydHmfRoTeIlK/TtQtvfYrGZTQtbLlVJptNq6GUvxMZg6+CEUMXAEfs4W1ve9vxFRWVR0Ns0aAWSgAREKBYUhr32F/mubVr1kow+joWGSQ9nL54gm7G99fPPPOse+mll9y0qRNdRoSGIWSOfA43e/Ycd9ONt0iDy+WlCC0xBzNWVpZ0b73k7e4Nb3iDGzVqlNWhV6jd3/72sPvD3XerL24z0wx2MnXu17/6nTv7rFnuoje9UUOhDmM8CoIFCUNGSj5q5Cj3zkveZjpmwg2SuQ8ZbHR6sp0mxaw1QbpXI0GzNJ1UBr7gCN54403upJNPcCefdJyU1NwqU4CcrJLBzSuNhC88Muqu0pkuObbl7lOfvtIESaMBoPkiurZIMX79qztdK6/WU7/iykvLze+oqa2G5dZt0OBYs9FHM81K+LYcl3Kxh7DyaGQsJXgi4EMnCsCY0CQydOjgNytTou/39+FQMMQIzGGqK+N+99u7TNsSSbgRk7mpdjNmTndPPfmMIQXRO2Ql7rr7HvfFL3zO5braxQhakA790aLa2jpM+CBcmvTtCkKqZd6/9e1r3UUXXSh+6BOuai1gceSRM9zrXneeO+fcWe6qqz7n9shBRAHjMVkHMfrnv/ilFOb1gWJgjtUV6EggJQWUUFOl7lOf+njer7CE6MmUXJYi8FuwOBk+apH11iNGvOpCCWA8XX1clgZhfeMb17qf/ex2VyVBYK1y1niEh+rPqEsCF3OUPTpWa1VlqfvIFf8sFqJentemVeLTtm3b3N1/uEfdbKvtK7H+Xf7HBz/0ATd27DjljwBSHcDHcoWxKDWyRcbKHCqAKbI1U+aMKytLL+jT/BuKIAVyfuUJU7bspWXusccft2lHKklL0yZOmuQ++9nPqK8rNfwhmv5JH11220WI/+xq4LkKZFKa/PDDj7oXXlxk3r93fsRQ/X35y1+0lqwPMMrUtQk+5ljmUa+bt7U1u9edO0tKdbVZiq7OlPX/MGPRokUakaxwJcIRM0sLQKHABYHmZKFQgg4pHgqP6ccL5+DZ7ttkjq17IK1dcOjTRaMEigCAC4fhCsGshawMPssLcl5v/p9bjDYTgroi2gxbulMohOEhB9H+UCBvU3y9LaqXA1w65NWDI/UHn7311VK1CbmrS/gqb/4Qrvo4tuHkTx5D8EfGkfUBmxe2nZ2nnnr8NDk+R5r3HClaeBuSCrEMr8rd/bP/4vRVbXPEkDbe7xlnnOZOOOEEN9OswHPW75XIV6CbeOLJp9zFF19kfVUIG4Hc/+fZEkrKe9ViBgI788zXure+/a3GDM9pVWrEG0uN4SjCxRdf6B56+CGlxdyUqVPchPETbEg4eswoCUt+g1qQBcoKR5AHAl1CUv12iSwQwacp3u4txurLCi5dGumWMxCeJRIjeDhktHQTqdJxDG/7ye1On3txZ599pmuTYoVCp2sjYDzM12cYJ/kHWFgaygSq1GF4+VifRxmtnArRWBipFOYzlKxE9IRskTGyVvxC0sJhoMaNdfrwclXpy73Lb0wQcgz1mvY0uwf+MsdVSBHQYJyZQVXV7txzzlJ6zp0761w3b+7j1vpJxxn78/0PSGBvEs+8xguUvo2zw724cKE5aR5hKM+5N73pIo0cytX6fD/qGeKdKvIZk8SAstKEu+H666SQwfyDmhrCwKkyU6t6wTf0ioFN2TaZ02efnW8OJHEEz2yYbg8Wh+M5dcoUo8NjpmiVB4YXVM41jB/nZsyY6X7/u9+bx4771d7e6b761f90P/v5Ha5u6BCVUazoRVxQT1kcwwQKoGdgE0fwtIYtnhSZD3Uj8M04J6F7S0k5lVGWsKwBKHKCF8gYWSu5UAE0tJhVpEzRKJiEJ/7wI3PdsmXLvXctHDrVak877RQ3Y/p0OV+t6qPPdf8jM9gqM8p4lFbxuMbiq1aucRMmNNiEBfH0b1vl1FkQ7IyOCg3/ZsyYIUFG9x96pbGdOcYhWonyS9jwrZ0vbwUYY55hW1zTtU5+AQGWkU48LX9NY6O77PIPGgyLl+LYmJ0MigAm1qluaJ373e9+5YbX11thGTNTGpuAEf45efB43Ff966fdksWLNCfykrd68gcWayj7zWu/5b79nWsFD0dUoxE5pGkJkvLWjaii6FyBalcQ3mFQOvj5A+pVztJA1Mdboj29/CmQ9U3kNAtw7733VmoIc/xAXu8CFVhLP3jnnb8zL7ey0jOYL6pf/OY32XCwXcOXCRMb3GvPOF19/2wpgMbxqnCHxsp/lrn/5Kc+Zt2Fi5VogqXZdarrsNakPKxn660XN7SuTgLwpIbaTUv+z6990/rYEhube08afaAl2SSUGMZCyAVvfIP76Ec+bAJG+1GURK57NMAkCn05AUXyrR8sYao39z5OiiTYaATdRkyE+lyBpugJ/2LYsDrN8l3tPvShD5uzSBlGJb///R/cmWed4d75zktdUj6J+UCC5evR2eq2x/zJeAFRCp7nyu+LmAKbJuZz+3z5x35ukDGyRuYXX3xxmymA3jGbpFfNxsGglw1CIiEGrFm9xs2bh3nXJ1BljhijDxs+zJ1x5mnWaiGSVnbBG89399+v/j1APibtv/uee9373n+pmKMhqRiRDpwrBGJMloZjdhFwnmhjBsOiuFu6dJl76olnTNG8gOh5YYk3kYDBAz7q6KNcQrOU2Wz3UAzGhsoE42m5Vo6KMKuyGAYLj01RGVkAlIfui9EKZtjLJV+j8vvRiT4O7Wapv//gP13ubrzpZluvwMLR9TCredppp2qYWGLwNZAwU54VPF8jnFekpXKvJ+Fq9FGtj/Itn2eLAPNoicL7sExQ1C7IGFkjc0W8aDa1poZf2qhIQuhAArNSc+b8Va15lxowbUXetJyxU085xenrINaqMG/0waeceqobNXaM61L3kJOgcbheWrpEH5B6ypQH8isrKqUsmg1TGVoY06AIsEUMtSAqYQSWIaMJDSQQE5yEhkF0RQz/ypgVE14oDhshwokaaKIFMRpIiPk29BJQ4GGKR40c4UYdMVKHrqM4jnBjRo/U/PxoN3b0aDdO1yOUBjzTYrx54WG4BDhhxmEsM45dmqL+xCc+5k4+8URZuC4Jyi9orW1c5775ze9I2eGxBKcrgjcBI0UbJhq1fZwQJ5I3ZviyPiavHBSMCh2wPQP8QNbInDSzAGqJr/FDs57ZC58NuATU2touZ262eb7EoYfMgs1//gV36bveJyRAFCb7oVKTRgkWJ4xwXNLpnMa0d2ucfq7F67d73ODaWrdtx458haz6rZaVYV7dJqYoS7+pv9rBNW5o/VCrk5iE+lVGDXtamvUUKLGEA3NpKZSxFhO0KL9GkXIzp09zt932Q0vzXr6fqYQXKKEF0YD1YvXRWo8UqVcwuhSLJRSDwe/r3/ia+8Bll9t6gap3ZRVlNgzWtxJNmfBzmJMIJ3qMYQFgj7cKKYTWyoRppyATaZYB/hcPHkLvNOhD5kr5uVGj/vnIvsEA3lcBI5gjf+qpJzXOXmICyIqpprxqkevXb3KNazeoIVO1ZzpKwCycb0EeDnPZTz71tFu3bqNraBjr6uVcySS5TVo0MhMpxnTIg2aE8brXzVL1KuclaAz5LzGX0Yq1HtVTUVklE/s999Of/9KsgCq3+jweYO+th00lq1sBOxaVoKW2dpCsgtLVij3WkeoApEB5ugLqY0LHC4XcQQgK0udzpGQFjjn2aPfxT1zpvv61a11SlsnKqobb77jDhM7EEYGzcRgaLQTKGjx1X8CiMPhyiougEuYoEhUm6cpuIWQuPv3mN7/Rknt8Qt8TQFaNESALLtMVc/fcc488br/aRTuBIZhWTC+ePiYZ06y+xq6kM3UJojkpR0xC2K6l3jlzHhIiLGpUuNPVP2ZkMk2oUhosyh//9Ge3YMEi9fWVqkWCo7zSBg8eJLM8zI3QiteY0ZoaVr/92GOPGh4hk1SL/RnjFRnyN8QXZBi20k2ZH0BLxyzroA5auz/odmQZVDeKYj4Ci0whQOOi6KP7IpMCSZ2aTLrssg+4c8+bZRNYPr8mpJiMEjy/qqnMsmoABy40dgf6f2BFKepO5Y7OVzn8n4aYOYaZevJYkKN4QNbIHNnHx48fXyeTMAJi+w8yWWrJLL8iOITrKxMCIigt4bF5FHPN5AwzZzarxSyb5uOJNxMOdjowQ3/84x+Vp0UM7nTnX/B6V1tT47K2gOHHxs3aBPKVr3xNK307rZXDZIItnqhFgoMu7rvf/Z5bvWqtnuVgiWH0zxCJeQ2FYkooRpNuedBmPTOZxUcZWUjCobUjuC/VDKUdSa3csc4R4Wz+NhKZlxU4gp+6kc9//t9k4YaacoN7iA9M4N6zQ+cIHPL1CuDdK9LDiEb3zhNN9ffIGpmPl+xL+F09MbYGrew7UJHfWDFnzl+17r3JxukQTAuaPn2quyIYbom7EqiYz8wZ0hHaKM7u3c3uBzfeqMUMvVWsPAhvwYKF7knNDJ555qmaaJnk3vrWN7sf/1jz51Uyy6qP5c/5z8/XsOpf3Gc++6/uxBOPt2EVjGORZeXK5Vo/uNksBYL0a+MImCq8oKHJGA1ABeLDwDTvghcWihlM0TK9i4nzsvAtOlA4FErp4yeM1w6kIcrvnUnLAzDqM1qjPPSzotOmTnJXX/1Zd/W//TuV9xJ03vcztOwUojfgq6fMn4sXKoSLrJE5si+pqxs2QtOYJX1bAM8EiO0U0xnT00/zNiqTF8w5v0lTu+94xyVSe80/g4fi1Q6NXpjjHaq4duXMdY888qit7WNmO9XP3/X7u9wZrz3ZHMNPfuqT7plnnreJFMbPAmj99KLFS9yHP/wxN358gxstr5zugcmjVatW8yVNef5lNuULjvIIbXiVYNIF82oBXAoVghHDqlWr3Lvf/V7LYenQpCf6Zz83r25C9ORklZhGve3H/+vOPfds5aBByOSLTn8YCJ2ijPbdBtbwEq1kPvH40+43d95p6wRxygFF2YWZ7sENXFGgEAbWS4+WszuWGB8MgsnAMbcRUewwR19XaEXmyF7f6m+rx3T2GQLA5Fmw4EW1mAVmNjHhoDVYHu85s85yqU4tXnT4tWzmvW09W0M5JnjoDpz6OOYEaGUgAGHME7AItG79FptbOGLEcHf9Dde5qWo1HZ1t1nLJmaC7ETeWr1zt/vq3R9yfZz/onp//omtRC2bzRqcWS0aPGumOOmqmCQsVwAFEIVA036/77oA4LEKoEEzg2CKRWoWyKt6P/bs0r9ElobP6R17KMZ4HD/J7v0GZJQfqYviK+oRwqcMSOQvwF7/4b5rZnO6yKZlfpXmrpEQFyll2/9j3OZCF6YTAw5t8CNMKIsNUcCkMyBPZx7VuPKm7pRRmyj9BpzD8g4Zue9QvG5FiFgstp556sgQ2RSbUVpRVJCSmGxPKdsn0n6FZwfrhQ8VAlEBjUDF027btbs6Df5OnXGF+wowZ09yPfvxDN+scOU8qg4VhyJRTi2MzBaaergEPnlbaqlWwEcPr3Xe++x03aeIkzQAqvyy5CVXdELQxieMFojYmUx0qBHR4QaAUgbUQXsZL0A8Oyxe0xKgzCn8w/cD0XUBPRgMAhcpofmS4+48v/bvWNpiY8krJi5yGDwgXitPKRU/YDBQFXMzxoU40lnLduhbqXLRo0XvoRfbxxsYNx/dbuYTHEE6/revmPfaEHLVBYj7evrZ7SRAXXvRGW/zorgWiQaz7YAIIZRmtSaJzzznblai1VGkoWKENEIMEb86cObYwA/Yoyrixo93NN/3AXXvt193RR82Qx8wvbEgZtOOli+VRXdOyLpWC8RZ1Pz+74ye26oZRKtHkUKkWh7AuCQ1NTSRSAJy4co3FWbVDedhKxtieNQemnS2eCSUdFUqvlKJVay2/Ul0Rm1xp5dDA9rWSZFx+SoWVKy9na5l2HCWlZLI8XqG8hYEnXvHoKjvceefOcpdf/n7Fai3F8FBd8EGHybA/M6A06qqQApWJNraClZfjiKuk1zPddwdT4u7HInc5vTW04fjY44/PXXTyySfMDLdX9cxJP08/hxlfv1GbFaU5YQtialRfqVKr1DhXM3ReI3tC6H6m29itFcTNm7eaObU+W9hjEpl5SzD1q2ffMumnymxzxbJlK91Ly5bL+dxs6/dVEtjYhnGa6p2piaLxVkFaziibT/fI2YzJDwBvuiesA8snbLXavHmz2AWrxTE4FDJc99QZ5SMtxKwC/KWVS/C0Yv2qmTm+G9ZvtNaLgBl1MMPJxgyUrligj6c61vcbG9db3dYVCB/4x9I1eyINN84R9KgDA7tu/XrVjfXUoQaGI82OYnYhFWIfgImgwhA2GlB4bWxdHFu16qVdY8aMGtyXEwgiMAAkSjSv7g0l5kjx6tdZFAJb+jmQMo00Jvu77mpJlzlW31NC3xzkFHDDK4TDg5k5i5W4lJf+iu7CxswgJPgaa5jnnhZDqJ8/+mgZK7tXz+xNLeNu5UcpWFswHisHTpPO1GaCyeMpxfHwoFTlVADaSWdPI8rPk+0hUFZW+AwfCYWuDXgEyhhsy604ppBJE9ikkLRky4my+i7LW02LtLI402Q02qSQCBzF9ptoPa+ZVfU1ej6CS7HQUwEYma1fv3F3rLl5R0aMCTrA3kVNGDDLvFQP3GbDlJXW5KvnjsBTNwKeSI9enD5LEx0ojdd0K5A/QWsYbIMDDPPS8vUIDCoEU7SbXpUjGKFtTApLclUuZfMYCT/BRTFDwcPQuLzmrE28qFXa5ljAgRu4ekW1VmZwyOPh6GJw7Jmsguzp163gQoIXPGlAwi+S0gc4ojqEUP0BQf3GT/JYMChGl1XB5I7xQt4HyqCD2de45A26UjuV0o3yIA3uPR3Cx2QWQO1hAYiVwmb7cf+DglwgzvDTidkwKmJfXCxt5tuETjrDEaX5vCAIU72JlN+sdI0/DUkPu+AcESQEoCgJCViiMhMrwKqLOjClCTlWlIYLoeYXQFN50JaZFAwUD8ZY/WqprF5Sh4dnQPWs0YDg4jDqrNwoUsBU5fXiDa7SME9jRLGsBnAL4Ok5ofK5DIioLukqrcxjKwEqjrkSOCIOGb5KNv6BJ04vT3Etl/N1l1yqRSMc/Vq98I9paT0nHyCeHOSSMe05DLooxG9awdX4TAz49B1K5IU39dsFUFZwbB083exaXviVy3VsUj0wQeIxPFEQ720bEhCkg6pjySEuMXiiKx12pItXjpIwAzZw7SU8j6x4Y6t9nY0Pu471j4oJQdtRHVlJLVcx1tXOeJeYpMkfKRbi8vUqjbLABVSqye1a/GtXktoJFeKdhCwTXj7zXa609kjRAJ6UVGbhA6tTOxa6PcvucaVxKSx7GISmz6N81l3RslTCNCysV0mACQ50wPyhoce66ulvdrn2HW73/J+6eGqXZSRbtmyYaNDCWekQ45Q1HECYAsmBFZ2ZLvk86592qc2Pu+yeRikBi11YPyl0aa34Kb9p2GRXNvxEFx88SQosZ9UQgbfKJ8iMWooFuoBNm7Y0lci736gFmT59AApDLLrv0i0uvfZ+F29dLaajufoTo8wUqyIIC0+UoAwOUpfm+1uqJ7qyGW93gyZcJONRKQalBbdbCXx+gyDIgpXS3vZlv3bJzU/YkrNnuPpPpXbEBruuEdNcsv5kFw9aGFUTgMOZhc6YdhNlGx9ysdZlEqYmr8SQtKtw8Ynnu1itNovmePvJ18nVFLpto8utulstVsvX9NX2p2wqa7zNl1AdVKNycWaL9IA6GRxds5oUy0hgiWkXaYp8t8utne0SXdssR1z7E9rL1BimvNnFy2oF2sOi1WuDm+rW+whr/+TaltzrYk0vudJMi1kltJHNKKynuM71Ltf0ostuiLk9yTpXMvYMN2j6u122dqqLmS8i3noEde0dUABkL38svkzHzN5ZumO8HyDSxAGcMvb7mwerOuI5tRLR7Z0qEW5MQetAVglSgKRaZLZthcs8e4N2/2xwg475F5dR6/Utqrse4BByqiO9XVvWdiz1jo/RIgYLTjytIVd6h+tc+5grqz/JtoCH5VQyoFl169ZMvBynLO8niHGGlUwqU7nwxugJruDrpKhxOZJlWgOw/laZvAMspLA+hh1mWfHihVk5LAFWSXmNN+Cqp1xaNOg+4/jxa/XTWDHRlYN3GJf8iEfw4CvaJX7F05vd7hdvdW7lbKmqzL7KxOIVpnzUZ4RhicR3qsomtMMnLQu3/B7trVzuBp98lUsMPdFPxRu+Hmu7jZwYgZnsx40b/ZxxI5LY6xYm6Y9/cEiIaABkxdSYGJpRX98pAjpFWEomlh0+KSGZUStXZmMYDE2KGallf3BdG1m584Ybuk3BDL5JQ3WIbWseccmMTJ7y0ZrFHbU0Fnu0jCtmpzc+7DKt64WOxBpaqDziwlb10XEgGmoSG/VHXUEm3YQOm1ld0yJW6ti2rYUttVK6C3Bjr0AmJZgZWqiHZKZaaXH1gWwxt6GxymZUjgML53IalVgDEdMEi/4yLq9dWitcJEAU0eDJrRUvXWa32/n0d1zJ0t+r0ch6KR0a8BPwFnKCl8mWice8VKp01yGdUYNwWqwq1dzKnhWu6ckbXLZppZRGC2qSgSlqnug8g3TDEH70cyVtbe0rX278XqAgcNHkJCI0k5VOVrn4Ue/Q+3Mab0OkMRt0NS+wY7lLbVBLze4O+n5NgKT3uPbGR92gMWeLLLVO/QHQK4EA4+C0r3Fdm56WMVQqZo86pVy0ABocpjnRutF1qXuo0L7DjAkPRQmlq1u7N7U1fPNjbGURFDqZvAKQm+4ohmdZMdLlxpyHjBQpHwfroUALdy3rndu+QAzXMFAH3niqarhzI44TTKml7VZinK56xYtEvfZc0C/HOQRHAgl6C0FUF8VmVaNP8OKdrnXBr1xMXSyDMqmf4Yhj3ZmscSUjtZ1s+DFaRxms6eQWl9q1TLx93JW2NsrR1QSayjAFkWxa5HYt+F839OR/F8u0jA7zuk2k0WL0CBdkX6Jfq9zGtOnLBYERIA4JC5hiAALRi1uuouEcF6+eLvpwPAhKFQOTrt01zf+RSy35ieiUryCSmCjJyClKyCxmY7RlhCZx0EAENymGtG9+Vv32GkXLH5eHK2/BZavHqhvZJGXSsrJBkv5veMJVjn+LMdIEpPhCJdAjQVXQCIwXtLiAKb7bIgMEqZ3JnygfcrSrOEO0UAu6af2IrpoD6Vxzn+vY9qL0wjulKFJuyDRXe9rnlVcOqSkA4LzikYvu2J5ALTzM9xEe+sOJZnItvWup61xxl6vQfUrdUEzMoPvoqp7iqk/8tCuTAuRkTXyLFp7jxa8pa9yu+bc4t+ERp9U81S8aUOTGua5z7KOuZMwbhQpEEOBzd0DmyD6+c+f2LZoFTIfmsDtL5A7+RP4sBY4KeEYCybGRg35ODIjpGuMl0C6lZfQW7PCjZP3UVcAImCw4aD1mGQYC2YgS04h1cng6Gh+XVqMgqIfagvyF8te8x7mq8Uo3tnsHbdsSl2peJYEKPugYYoJhMO1B8cT6g3qQPelWIChBOl0LwiBnNitGq7vRIFIC1BZufUYhK5PAkM7ERtcnxbDuAHzSsgQSWFYAsmqx0JtVOZfBTtAoZA0lHLpL25UMnfgDKIoQisXTrm3NQy4pJzEjRRMy+lc3FK9zg074pEsecZZmAgVbi1N0N1galqdj1ZPckJOudJ214+U00+UIezG6LKeFuXWPiYfaDGv0QnN3QNbIHNnH29szW9V/NdGn9x1gi0IIDASNMLRLB4zlj+EJc0qA0pHVvHymY7seNFQTY5i8YHdNorROxFUauHAZlIaGA5bes1xmdrHN/DEPIG66XM0YVz7yDDHiuPzCEPgm0rtchwhNyJRi4m3CxYvQnlWxggALfd9yYKw9KB4kQ4J057MpzjPRNFbM9DOBKA6K5+n1w0dgBnFGPzwSEAGCG3nQoiFsPMYrU3sJUblQOlzTbIec2q1Pi/4qxes9CBRJChWfeLErG/Fa6Y/iVFfYSK0DU0vPKd6Vayp+4kWuXYrRJWvZpRFWurxOr6hrT0aaVVjJBOIiwfw3yRzZl6xZs2bn1KnjtmhYUNfXdLAxRQAg0RhpwGi5Ig7Ecno7N9dqaQg7HLJ17VglszbblZm2ewCdMvvlo44VLAkAR0nBM1+sUEto3fiMBLvDZfWCqECrf9dCzqjTXLb0CJm00wXvXglcL5fyJxBdG5502Wlvkb81TDDpZjyOMDgf8vRbquVDD8JhqCkFeJhS5EsZPcY7FfMgEDgtGuUJQiB8LI0J1eoNlIEsVGS0clV5UxDdYy31jIJ1Nq1xJc0bpQA0JlkfdZeZ5GBX03CuTU7lxBcsnIcFJsJBF1M0uq3Rs1zuZJbX5WtUatNpea2rKR2mBqhuSTz2/o+KBYEhoHZMbUH2Je9617u6tm3buFoLNTPCDL2uaBv1ihibZhQRaCPa61yba372RikaY3v5BNJCCI2xYNG+zZV17ZCglE/NP53WMGvC61zV2FlmCcgJGVDDX6Zjs0utfdiVquVBnM0DltbLxzhLcDVCHnqk6xw6XRbieRtdUHu2eblr3/KMq1B/Z8vGhihQBZd74xzIE8K6KClxWZruTMqkS0DKYrnJand60r0osj8U1++980pg2chKEDz/HMTqGVh0fV7wZEFN1DrVLciO66q73Wsk0ybRxHsSANKlpsElakfbPIq3bL4cmPhMQUb8jorhrmLae1RUdEkGYMGWOFuipu81oEF+PbEol0plVyN7xiHKnFqkTBdyXyxADrwKyNKDgIl+0MfpKNup4hBG5cqEVciq1fMSCG/r0C5zmOkjL3GDj/qwiKrUgVkTYIOrU0Kz2hufdPHdSzTxIwLUZdjM3fCpLjloku712ley1pWM1u4hKYCyCK6850yr61jzsFrBWQLGLiIIJnglpQrqoM8GOfCzCC4k9Ah5XYBfYXI37/K5Q6thjMgzGCWhkD9b5gBgqGSkht0QimTK0L5VdMhPYLFKQrThZsURorfGnEGjSfzwoQdSmEF4jy+CUpmgQDg4aLwqQrbugL+CzD32WurtegGN6SsYDYJnfOBB/2bCAaCxKf0Ms1i4eFzNKbN8cgSVk/fosQiZDc+7ttWzld6qkkDDlHmGxbL6CsZabRez71RpskaIZ7Jaux91uoZkbKJQbhFZNvwUDRUGCwGpn4omRXxs8zPyol9S3TA+EIEhG1CkeBNAgBNVR0QUZOp9ITuUGsvDk480eGEVJJliWSMAsud2KPQ8ZMoaHPKjjPKN5GzGmDfQMNIsEvSQCYWl/7YgeGFl9gwQugtdsbQGFMqxvKT5dJ59KChs1gGZk2YWoKmpfYHW+1N6h7+Pt4MADliQQ2YiUQevNaXUP7kymSohi+OCBqeFPIMYl5Zv0LVbQ7tO02rXtNB1PrlK1m6zqzr6g4IkolEbKU2mea3m4V90lXIiGdfHNbrIVo9z1WOOF7NDXsgvHzrGtdXPcNn1jyhSJOqId+0yr7eq7hjBlDIKN/4QgMdY0QhFlglYpqTULCWDkRYnnnEtCPDXLEogCJQVXAJFx1HsLsIdDIf5qpWWpzuTo4RqwlJMiI9XSFq8Qlm1n/EjH/9CK5vWJ2Ew40QQnxcmBQjgYlTqHh6K/zkNq6HRgMhBVOP0282tgJ1wAJE1MifCFEC/T75y3LgRjXphYxIzWsUCigUaRoiaHn2XRrkuVVLrqk/5jEvUTAQfBW8N9AOymrBocp2rH3Fty2535Rp3sjqoVQHXseROV3bEsa50xOkiUhZDr5d1bXjKlcobTrP9WnHsgCjR6lfT87eJCMUJcYKNGlo3CRk4JSx0YcarU91HbIY2ppZqY4U5l2DLQTm1KQgQzn49PUwL07sFp0y9Qshmn8CTQsgPQCiY8liCf/ZnX9Jn4R4zTfuWiGzkoj5f8yIJLZKlNOEEP7GKNKKspsxzHdtEz1jlV3cZBRu5NzaoO023b9S0uXYW6cjFq4SQnElN1PUMOIBSgEZkTpopAG+Jbt26/jltqJjEK1aFIaRQNOs2bFXEwkycmpgWI3KyAsTZCMCYIwVJHuHKjxprrTuzRgsbiTLRq4885Zpc+6ZnNbSTeVepmFbJOjfO05SSlIaeCMHKg41p1rCk8X7lCFqT7hAkrZ4xtbJJ82VreD+xbb3r2rFIo6Kxagm0HA07oT84bLbT+CG8TBkQBEFYW/+KcvgYX8inqyb/SG4YQBby2a1O3ORD9D4faXANNOWljwiYxSlbG1BESc04T6+mvlES4Cc069il9ZCy0eIfgsxXhUKHjVQ4apYxK7p3P/p1Vyrrma0cKoUa4XKDGtygSfpCrGYO6SbCwKYZbal/DpkT55uVbrSL9yEiegfVbAzKZ1WlKqiDXTYau4gQBAID2RamreE6slwzMv2apy6tm6KrBCKJYH6Z7Ys3NUrYyqMp0o6tL8qzXy64ykOa7ATrDfSBLDzFNJ/Ay6DUy4jCf1BBdQoJdaGGQ1lWK2iN86QUes1cEGxZFEdTc+bmDQsDlJeRBepkjBYj4SsMt6lgVYDAsVTdNIdxitcEjwpSoa7qfnTQmgmmmHbnn+3WJwiebhSNv5ST4tIt+KDSmtApGTTexQdNVBeqtQTVbYZfK5XtK6T8mkaHvznxgrrMpiiP4QgvNbrq3PSUK29b48qa9UmcrXKkV9/lutY8ICxpXgg/VBhfa1TWosSHXbt2PqJ9c13FJ4SgICSV/J4iPnbgX5Lw3isSwkR7xugqAaEj2RQfWIS1BBin8vIP5BYqUbNWa7UrWN48ymGvjkmZuvQX6xRDNKFhR0pWQfOqbNPO6shIwXIi3kwguAl4bssCmxnMisk4iN4SqI5QAtQNxcJbX+sTY6VcpsDSIl21KdHSciCtMmYpfNMV8EImGinBKS/PaCT3sCm8CEGcVIKdDWGfmFA3mhx5CvM9VidOJErutjzpWlfeLdMutOQIy+XVoWljrQBq8tEaQNfmp1zXqj9pU6roZcuedSVqQiM011JaI7S78Ua2yBhZC5AF2o+FJ5547iX9/PsivZBxHN/56SvYfjRaDAhaK1ULkcASNnVrFKiohA3TdWS2LdBs3VwtS0iDwUUn+0pW+WARpcWgplXObXxKiyH6upcmQuBZWrtcEprjd9oskcsJF98veJSUgTwJWZPUpsddUmsGMBShl7TLbGoeofyoCdJ5lJKcPqB+1n1J0Bl1F2k5pFlZCwvSFssJU4kwocuxSg7TyJJNpVIcJeClszpJHiNdV8vPs47IKXggVXxSMKdPOHu+CYbqwGowdGNnUOW4c9zOVX9x8baXlFndgyaEKsXXzoU/dXv0smnV5PNdomy48ktpVVksvdV1rX7ctb34U821rBNcKYjglwixVi1oVU84T3mxGoGVEw7sKZQCLELWhhRxOhg8t3/kIx9JXXTRBfcPGZI4Lkz0V0jjUOtkWlYAjVjMiuhL5na75uf/VxJh1klMEwL0z7SyXGqPy+1a7ko7t6nleWRw2PRqotYIjrf+u1XOW6Jtg2b+WBlTWbXyrtoGN+T4K224x4qj7c8zZMIWL1MubW964X9cZtGPNOcNikw36yUUKUDZFH1SrnSMwEkJpKjW8JQHU5pUns7nb9BCqhwmkWDD30DgJlRlxq9ISSlKp77PDTrqA74Ppn4J3wRKfkkhNOVWnGQkE3AH0aJ0dgYHCYMgVdJZPMx2qG66S+Vi9FQ11lUffalreep7rlLm3/ZECI+SXLPLLPmphs/3a0p8oqRV60cIzXKEtfybFBwUhobFxpROdQ9lk9+mHViaNmclCt4EgQmgtrau+5F1GIcC4HoaC3fs2H1PXV3t1TLXenXdi9kTZMmWCUJsLV8VGZGaoCnd+IhatYQTMAaiMan0+TDBlnh1gT8pTV3G6k9w5WPPlMnTx58bH5IoqEUZlM4CTOm416qOaqWrhVq/HCqdzwOj2QxZdsTJrnXpb7WKp+8KKJ/1702rXWrrQlfeMEFRwlGza6YEgbRyWiAp7ZKvEttjokjAfIH1QQKTQBBVXP1xPKbvHqtbMB/CGrIXsF8XAF0vTCMMAMYzzze8Ddiah00doC8+sWpo3ZOUFp6gJgx9y8e/Wd2dusSFt7tK9f0oG40lrqF2rqNRk65rpecsE2t6XN58DtxEI7Ds83ddksi40zQr+A4zmsC14ag0HZnpZd0MMhbgfABLvAQj76677npOmV7kJYreQdgjVPWP0EL/zXQmDktOTpp9Z1d7zWMyMzANftsIQQzOBc5YSh5b18jTXK2GjewPzOxYrE+ELbeWacjKaUxrr1vZ6NMFGzHAYNAz3hmjrJWJaQxxEjXj9TH8CbpniViRYkoyrm/qbZqn+uWA4qMQD476M6arnLarKEoiwpmiK8OsS1K0fA5MA5svwp06oRFlOKa9WMIKnIQb3jVDTgkV4VNTNKDUxMKpmBqKnCFTAPgHw607Ud20dlYJqad62vtd5Qmfdm2VY80niMuJ1W4Ucqvbk++SrLA3pNin4KfllaK6U7Eql536Vg3JPye7rresVavamvLAQxlTWVhki4wtIjhhAciBd5G55ppruj70ocvurKtLHBuk+wsYB+R1KGsSb1bMNnOvymV8LNVau1Uqso3vtFwZPZY4qxpcxdizXM0kmWfth4vLiWtd95Qshz4vU6KNC+TDOtTMkFesoZz6fYNnGERZqwrUWmysn9Cu2LGvde0aLpXSEqR1ENO+ZanraFqrj05Wu3Z5fRkmRLQ8i1UDpsGVoK1fNvg6qQrrk1EMQeFjEiw9ozQk0pKA057T6+TK63Pp24CMt+GP0n0AV2oIFEKPJeo6O9Snl2iZ2UZOsnldJVr5U0NBCbKyNNZSlS8lWKUT3qLR22TX/NLvNDx+wiW0oloih9emjlVNhroyWhBT40qXaINI/ZGuQsIvHfVa4aHJNVkYcMK6+CBspTytrR13IuMwVlftI/IBRTBK+aT41KnTntcbuP6L4WIaZpEQl9PUvvMFrdYxfBOJRCNpT7MejLWwS3+KFgZxOXRx28E6TPMC6r98IWtpnbsWacS4x1qhbSZRS05UjdMiyEQV9porMAXBhEgrJSBY7Yfr3LVCjNSQT/GmeBStkyJpLr1ry7PqIjT1bF2AyllRrh4GTPJ88mdMqXouVECKKFw0PLMM4nlKi1vZXUsECpMKy1RfWZ026M40HjH5Be0EW/RhphAro93UHZrljNnIhS6URqGvoA/RwhYtVw406kK9cfYSAEX1MYTLtKzTNPdizZ5u0GKZVkm1xCvPQBuNql2Jxvslw6a7ssFTXEq00uSZTJJeGBahAjD505VKtyxb9tJxkc/Fg2iZx1b16oEDf0CvWK2/s75++CV8MhWOen8A4CKYIZLMM1OOcAYAxjq78Y4OkcQRBRLWP1l/B5n80X6USnciSrEkKAvxtpdOptKX1qXPYBUqlaGoRhNiNgHGmwAFA0aGr6bbBBVCDxEzfYcW4BBIUAnowiyDl6wQczDGGgnJ/B9TJMUELV4uq7ehErQRCyTTQsHln3woDP6IaPQdKHlUzKwcLRvafV6PJ09YVV0x+6YNumdERHdKGjiKdls0s26IEtBCWY7uBsT7j9r+/9vhw8e8UwlhQFhqQj6QO5Ce5mS277pVvxn0Dmmq1nEA5plkdxqAWq9m9HnEqdByWF4P0FDRiTIES5cA+CMYLMaoKuP7KqaKfRqkhHVa5uBU0PoDOEDKyGu26eNAkUyLxSCUzyy48lhfaMiAlJ5NgdVCA0vQXR/p3uxDjiUbXeCmcuoW4IBNSRuWCAJ8Ac4hCgtgEichMzGhtG6xhDUqf74i1UE1dgp4isOoGJTElAmX2ZQPeMopxewOPs6XBycslf1gRA6ZduezOzKkOIUhrwTf+973H9Jv9DzJy5leGGTjAEFlAxkjNizKkw4lR48wtecVGo1OlYIwQHniiO2uy3c9YW4YG+AQlA7h+rKACZhi8HkywPl4nz/MIytGhCkCpHMoGHOpJxLAMV8ntNICldUOnUgvyBOWDeNDvMP46BUssKihbYimRe492hZhapSv02MGlMJAjJbq9eKpPun7JDKNpIOQQYyW4x6LgP3Vl7YXv1tf5PhliiFTpPKgnHJEi1LiQARgFlS2l0ApG+AlpENIZnVCdBVpucLnfC6qykcW1FtoeXySN/MqkW/tBUUOkQfNe+i19bWrV79n8rSjfhVBCqcf02HqHsbDFw5T/7lzn/yDrMDzaFBhgEnFGVWYb+BPITP3T/jUF8FLgkE4JqBINFkKZUZieAwc5zzsARahEXXTGRSC2/0FK9NfhmJpAPVHWVmJvuS+5/m5857+QyQnxIaZohyzLCRGrYB+OrZBPx3rJxoKGdcNMlIxq0IAAAkoSURBVGwh4bU7ZWB3+1puQNBhov7ClprvbgdUuDvTQcVR1ewrXt0YAgO50u+j0nJZtcOocc3ad0+edvSvI/nyrZ+4Hp2daUY+fs6cub/X7wE9VqYvgRB8BXZbcDITq5iQyQWJA3iw8uC+DyGPE4I2Bngg+XuYEdHcyO1e1RaFsVcFB5iZlrc3IU9fpBB8tJ3ZuvLraLt3735szkPzfl+QxT/kuV2sXuLyVoCfIJ84YcJsgdYviAeOkgHx2ubhUaSnLvmUf9QzAjrYSlOct94CqPrM6jWN5x955GvmRPLZhJ+e84IspgDkRwHyrvHGDWt+PnLUyPe26ydUaGSeMBnWSOnuIRzFw0CGSCaLRnFCBYymAy+IF2D+igVfPylROJGcykAKOBbiZ7GRjNxG6++R1OsR/GCJyghUcez6gpfnd0GdYOQDAP2T52Nx6GHu6LU3DP2qqj6+rW85/mL06Anvi+SlhTLUNyc/jO+r2TIQRgksrFy14stNTbu3s5zYJ+PzAgGl8IDwEEWI4j6MK8asaF5lLRIKTXgIM6xPV0WRxyuTj2fg5kMkXz6uSCUFUb5MXjlVrnvVbyDwyAObQ1yZnvJKmq/GFIt8BPINNDD4VrChuecrMpLzvn3VqpVf7gEF4UcnDSy5v9pQALBCGdyKVUs+MaFh/Pftp1mJOBwOOQ6g+HzqVl9Z/+TkyTN+EEEQ4SPrXgrQlwWgLJnDgm7OA9fdsn37tgf8h5tJPhwONQ6UlVVqFnfbA3PmXHdLD9yKtn7y9GcBSC/oN55++tFp06fPeLSiomwY3wg+HA4dDvCzfPqRqu1Lly4546STzsjv+BGGBf5cT4z7swDkDb0XNMgBWM7F53j969XxcMHicOjJAWSBTJBND+GHzkcox55FBzR2w2vMdwXTph11+5Yt227lE+uHw6HBAWSBTJBND4xo/f2a6pezACE8gORHBc8997fP7dixbR6fWz0cXl0OIANkgUx6YFIw49cjLf/4cj5APqNuCkYF8+b9bfLMmUf+taZm0Fh+4OlweOU5YCt9Tc3rFi9edO7pp5+zIoJBaLH7bf3k3xsFID+bBQFqfcqCBc+dNWnShHv1W/Y1vd8oIvvhcLA4wB4/fUm9aeXK1Rcfc8zxj0TqQaa0/ujWr0hy4e1Au4CwFP4AlsAUh4r1jtkV+t5MileODodXhgPwGp7D+z6EXzDb1x9We2sBgIXSIO28hq1cufSjo0ePulHbyeN9f2WEoofD/nLAf90jl9VvN3180qTpN/eA12uuv0d6r8e9tQAAwPwzO0hlFkBk3br1n9VQRJuFbcQYJh2+HkAOBMLPwes+hI9s+hzyFUNlXxQAOCgAFeWVYMqUmd8TYp+REmTtJ1/JdTgcMA7AU3gLj+F1D8DIIT9t3yOt38d96QKiAMOOP+9trl699KP6+dgbSrQqcdgxjLJq3+9x+OjzN23a9KkJE3qZ/V4y2Jua9tUChHWEgs/bfRBctarxA3iovbeThcUOXwfKAXgIL+FpEeGHfA/lMFCw+Xz7awFCQL20UEPEsxsaxt2ueYIGfu/ncNh7DjDJo5/Fk7PfeLm8/Yd7QOjF8x7pA3rcXwsQVhJqYN4nAOElSxa9Xu+iP6pPkh5eOwg5NYArc/vwDN7BwyLCh8803pDvA4BaPMuBUgCggwyOSF4JTj317OVz5953ofquW/g4AX3Z4dA/B+ARvIJn8A4e9igBE+HzgMf6PcoXPB6oLiAKlH6JAwRB1MKKFUv+ST+d/q3q6up6e+UsTDh8zXOAVt/S0rJty5YtV2tDx0/yCf4GWWH2w2F4j+R9ezyQFiDEgCEi1gBNzcOHoIULXzpbCxezcWw0Sgjz/8Nf4QU8gTfwqIjw4SP8hLccByzkBXTAIHpAaCkWACmHnio/7rjkkkve96Y1a9Z9SgtIW//RfYOwr4cX8ATewCPPwvwZ/sFH+LlXkzx5CP3cHIwuoGd1IB86LPkugdXEKVOmfEVdwnv1C6RxVhSL7XXvCezv4RnB0+L1I5JZmfxfLF++/Ks9VvNCMkOn6YD09yHQ6PWVUADqw9KgCL1M2LJlL75+2LDh/zFoUNVZTHX+vS8tI3jWS5qbWx/Zvn3r16dOPfoBGNQj9MmvHvn2+/FgdQE9EQu7BOpDq/OKBwPe/vZLz1u/fvN7mptbnsEL5jeJaSV/L8Gbev2uj2iDRmiF5j6ED39CJ/qA9vfF+Jnvn4slHoS4sA8LTZt1CWvWrMlef/0NC8vLq346YcL4xXq34wg5RuOYCLGPKvE2yP/BkNAHMPi1c36eRS3+sa1bt33h5pt/fPXb3vb2+dDcgyRkAV+I3+/xfQ/YfT6+ms2MLgGLALG9mLFkycLX1dfX/bOswQVVVdWD+FQcP3B9qPsJtHZ+mJl39FpbW5rVz9+/bdvOH82YcdSDorNYi4YHCB8tf8UEr7osvJoKAALUjyIQYE5PRXDz5z85dfjwEZfoA5aX6LtFx1ZWVuuDGvrOl75p3NeHrQ3aK3gKJ7kQeltbi35CKTVfH2T+7datW3577LGnLOsDlVDwJCP4V8XMvdoKEPImyoyiinDFFVckr7rqEycOGTL4YjlS56uVHVlZWWkfL+CHGTm0XBrCO6hXPnvLrpxwF1RbW1unrNMiObCz9Tb1vddd94Nnbr311r4895el9aAi3wP4oaIAIVpRi4A1KGYy3axZs0puuun66RpCnlVVVXm2+toTtPo8rrKyIulfj9an6/jAk7xt+0HHffQhMOe0bkYnfGUTg4X10e/tpbQ626gfsHi2tbXtYQ3lHrnyyk8vfeihh/oz4QBA+ISiSu6TXtnzoaYAIfXg5TnuTSMM67N533HHHVUnnXTsRHUTx1RUlL9Gb8nMlFJMkNBGSIi1shbyKf03+QCDUqAc4fY1BOyFjHwQMr9vlLafVpPPsUfKtEXCXq23oRa3t3e8IPO+4Omn56+67LLL+OmT/sJe0dEfoIOVdqgqQJRepBKOGga8/1wfRCy98MIL6yoqEsNra2uO0Jp6fXV15aS1azccL6FOGTFi+Kj6+mH6uJ7jE2pN/JCylGV5Q8Po51pa2lZqp/O2PXuaNvPTavfdd99OwcvvgYwi18/9Kzqc6wePfpP+P6jmcGk422eDAAAAAElFTkSuQmCC" alt="Agent Baltic" width="46" height="46">
      <span>By <b>Agent Baltic</b><br><span class="chan">youtube.com/@agentbaltic</span></span>
    </a>
  </div>

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
    <div>Mac STL Repair &middot; free for Mac &middot; no size limit</div>
    <div class="credit">By <a href="https://youtube.com/@agentbaltic" target="_blank" rel="noopener"><b style="color:var(--amber)">Agent Baltic</b></a>
      &middot; <a href="https://youtube.com/@agentbaltic" target="_blank" rel="noopener">youtube.com/@agentbaltic</a>
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
                '<div class="progress"><div class="bar"><i></i></div>'+
                '<div class="hint">More complex models take longer to repair. '+
                'The status bar may not move during repair.</div></div>';
  list.prepend(row);
  const badge=row.querySelector('.badge'), bar=row.querySelector('.bar>i'),
        prog=row.querySelector('.progress');
  const x=new XMLHttpRequest();
  x.open('POST','/repair');
  x.setRequestHeader('X-Filename',encodeURIComponent(file.name));
  x.upload.onprogress=e=>{ if(e.lengthComputable) bar.style.width=(e.loaded/e.total*92)+'%' };
  x.upload.onload=()=>{ bar.style.width='96%'; };
  x.onload=()=>{
    prog.remove();
    let r; try{ r=JSON.parse(x.responseText) }catch(_){ r={ok:false,error:'bad response'} }
    render(row,badge,r); busy=false; pump();
  };
  x.onerror=()=>{ prog.remove(); badge.className='badge b-open';
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

    global LAST_OUTPUT
    LAST_OUTPUT = dst

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
            # "open <folder>" leaves whatever Finder had selected before still
            # selected, which after a repair is usually the ORIGINAL file - the
            # opposite of what you want. "open -R <file>" reveals and selects
            # the repaired file instead. Fall back to the plain folder when
            # nothing has been repaired yet this session.
            if LAST_OUTPUT and Path(LAST_OUTPUT).exists():
                subprocess.run(["open", "-R", str(LAST_OUTPUT)])
            else:
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
