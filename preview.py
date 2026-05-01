#!/usr/bin/env python3
"""Backdrop preview server. Browse and preview upscaled, colorized CDE backdrops."""

import io
import re
import tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlencode

from PIL import Image

from generate import parse_xpm, get_slot_colors, scalex

ASSETS = Path("assets")
BACKDROPS = ASSETS / "backdrops"
PALETTES = ASSETS / "palettes"
PORT = 8089

RESOLUTIONS = {
    "1080p": (1920, 1080),
    "2K": (2560, 1440),
    "4K": (3840, 2160),
    "5K": (5120, 2880),
    "6K": (6016, 3384),
    "8K": (7680, 4320),
}


def list_backdrops():
    return sorted(p.stem for p in BACKDROPS.glob("*.pm"))


def list_palettes():
    return sorted(p.stem for p in PALETTES.glob("*.dp"))


def upscale(img: Image.Image, scale: int) -> Image.Image:
    if scale == 1:
        return img
    with tempfile.NamedTemporaryFile(suffix=".png") as src:
        img.save(src.name, "PNG")
        if scale == 2:
            with tempfile.NamedTemporaryFile(suffix=".png") as dst:
                scalex(src.name, dst.name, 2)
                return Image.open(dst.name).copy()
        elif scale == 4:
            with tempfile.NamedTemporaryFile(suffix=".png") as dst:
                scalex(src.name, dst.name, 4)
                return Image.open(dst.name).copy()
        elif scale == 8:
            with tempfile.NamedTemporaryFile(suffix=".png") as mid, \
                 tempfile.NamedTemporaryFile(suffix=".png") as dst:
                scalex(src.name, mid.name, 4)
                scalex(mid.name, dst.name, 2)
                return Image.open(dst.name).copy()
    return img


def make_tile(backdrop: str, palette: str | None, slot: int, scale: int) -> Image.Image:
    pm_path = BACKDROPS / f"{backdrop}.pm"
    colors = get_slot_colors(str(PALETTES / f"{palette}.dp"), slot) if palette else None
    img = parse_xpm(str(pm_path), colors)
    return upscale(img, scale)


def render_tile_png(backdrop: str, palette: str | None, slot: int, scale: int) -> bytes:
    img = make_tile(backdrop, palette, slot, scale)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def render_tiled_wallpaper(backdrop: str, palette: str | None, slot: int, scale: int, res: str) -> bytes:
    tile = make_tile(backdrop, palette, slot, scale)
    tw, th = tile.size
    dw, dh = RESOLUTIONS[res]
    desktop = Image.new("RGB", (dw, dh))
    for y in range(0, dh, th):
        for x in range(0, dw, tw):
            desktop.paste(tile, (x, y))
    buf = io.BytesIO()
    desktop.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def xpm_dimensions(backdrop: str) -> tuple[int, int]:
    pm_path = BACKDROPS / f"{backdrop}.pm"
    with open(pm_path) as f:
        header = re.findall(r'"([^"]*)"', f.read(2048))[0].split()
    return int(header[0]), int(header[1])


def build_url(backdrop=None, palette=None, slot=3, scale=2, res="4K", extra=None):
    params = {}
    if backdrop:
        params["b"] = backdrop
    if palette:
        params["p"] = palette
    if slot != 3:
        params["s"] = str(slot)
    if scale != 2:
        params["x"] = str(scale)
    if res != "4K":
        params["r"] = res
    if extra:
        params.update(extra)
    return "/?" + urlencode(params) if params else "/"


def render_page(backdrop: str | None, palette: str | None, slot: int, scale: int, res: str = "4K") -> str:
    backdrops = list_backdrops()
    palettes = list_palettes()

    sidebar_items = []
    for b in backdrops:
        active = ' class="active"' if b == backdrop else ""
        href = build_url(b, palette, slot, scale, res)
        sidebar_items.append(f'<a href="{href}"{active}>{b}</a>')

    palette_options = ['<option value="">-- no palette --</option>']
    for p in palettes:
        sel = " selected" if p == palette else ""
        palette_options.append(f'<option value="{p}"{sel}>{p}</option>')

    slot_options = []
    for s in range(1, 9):
        sel = " selected" if s == slot else ""
        slot_options.append(f'<option value="{s}"{sel}>{s}</option>')

    scale_options = []
    for x in [2, 4, 8]:
        sel = " selected" if x == scale else ""
        scale_options.append(f'<option value="{x}"{sel}>{x}x</option>')

    bg_style = ""
    if backdrop:
        tile_url = build_url(backdrop, palette, slot, scale, res, {"tile": "1"})
        w, h = xpm_dimensions(backdrop)
        # Scale CSS size so each image pixel maps 1:1 to device pixels on 2x retina.
        # At 2x: original size (retina-perfect). At 4x/8x: proportionally larger tiles.
        css_w, css_h = w * scale // 2, h * scale // 2
        bg_style = f'style="background: url(\'{tile_url}\') repeat; background-size: {css_w}px {css_h}px;"'

    res_options = []
    for r in RESOLUTIONS:
        w, h = RESOLUTIONS[r]
        sel = " selected" if r == res else ""
        res_options.append(f'<option value="{r}"{sel}>{r} ({w}x{h})</option>')

    download_btns = ""
    if backdrop:
        dl_url = build_url(backdrop, palette, slot, scale, res, {"dl": "1"})
        download_btns = f'<a class="dlbtn" href="{dl_url}" download>Download {scale}x tile</a>'
        download_btns += '<a class="dlbtn dlbtn-tiled" id="dltiled" href="#" download>Download tiled wallpaper</a>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="icon" type="image/png" href="/favicon.png">
<title>remotif</title>
<style>
@import url('https://cdn.jsdelivr.net/fontsource/fonts/dejavu-serif@latest/latin-400-normal.css');
@import url('https://fonts.googleapis.com/css2?family=Uncial+Antiqua&display=swap');
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ display: flex; height: 100vh; font-family: 'DejaVu Serif', serif; font-size: 13px; }}
#sidebar {{
    width: 240px; min-width: 240px; background: #2b2b2b; color: #ccc;
    display: flex; flex-direction: column; border-right: 2px solid #444;
}}
#controls {{ padding: 8px; border-bottom: 1px solid #444; }}
#controls label {{ display: block; margin: 4px 0 2px; color: #999; }}
#controls select {{ width: 100%; background: #1a1a1a; color: #ccc; border: 1px solid #555; padding: 3px; font-family: 'DejaVu Serif', serif; }}
#controls .row {{ display: flex; gap: 8px; }}
#controls .row > div {{ flex: 1; }}
.dlbtn {{
    display: block; margin: 8px 8px 0; padding: 5px 6px; text-align: center;
    background: #6a6a6a; color: #fff; text-decoration: none; font-size: 12px;
    border-top: 2px solid #999; border-left: 2px solid #999;
    border-bottom: 2px solid #333; border-right: 2px solid #333;
}}
.dlbtn:hover {{ background: #7a7a7a; }}
.dlbtn:active {{ border-top-color: #333; border-left-color: #333; border-bottom-color: #999; border-right-color: #999; }}
.dlbtn-tiled {{ background: #5a6a5a; }}
.dlbtn-tiled:hover {{ background: #6a7a6a; }}
#list {{ flex: 1; overflow-y: auto; scrollbar-width: thin; scrollbar-color: #555 #2b2b2b; }}
#list::-webkit-scrollbar {{ width: 10px; }}
#list::-webkit-scrollbar-track {{ background: #2b2b2b; }}
#list::-webkit-scrollbar-thumb {{ background: #555; border: 1px solid #333; }}
#list a {{
    display: block; padding: 4px 8px; color: #aaa; text-decoration: none;
    border-bottom: 1px solid #333;
}}
#list a:hover {{ background: #3a3a3a; color: #fff; }}
#list a.active {{ background: #4a6a8a; color: #fff; }}
#main {{ flex: 1; }}
#empty {{ display: flex; align-items: center; justify-content: center; height: 100%; color: #666; font-size: 16px; }}
#title {{ padding: 10px 8px 6px; text-align: center; font-family: 'Uncial Antiqua', serif; font-size: 20px; color: #8aa; border-bottom: 1px solid #444; letter-spacing: 2px; }}
#keys {{ padding: 6px 8px; border-top: 1px solid #444; color: #666; font-size: 11px; line-height: 1.6; }}
#keys kbd {{ background: #3a3a3a; padding: 1px 4px; border-radius: 2px; color: #aaa; }}
</style>
</head>
<body>
<div id="sidebar">
    <div id="title">remotif</div>
    <div id="controls">
        <label>Palette</label>
        <select id="palette">{"".join(palette_options)}</select>
        <div class="row">
            <div><label>Slot</label><select id="slot">{"".join(slot_options)}</select></div>
            <div><label>Scale</label><select id="scale">{"".join(scale_options)}</select></div>
        </div>
        <label>Resolution</label>
        <select id="res">{"".join(res_options)}</select>
        {download_btns}
    </div>
    <div id="list">{"".join(sidebar_items)}</div>
    <div id="keys">keys: <kbd>&uarr;&darr;</kbd> <kbd>&larr;&rarr;</kbd> <kbd>1-8</kbd></div>
</div>
<div id="main" {bg_style}>
    {"" if backdrop else '<div id="empty">select a backdrop</div>'}
</div>
<script>
function go() {{
    var b = document.querySelector('#list a.active');
    var p = document.getElementById('palette').value;
    var s = document.getElementById('slot').value;
    var x = document.getElementById('scale').value;
    var r = document.getElementById('res').value;
    var params = new URLSearchParams();
    if (b) params.set('b', b.textContent);
    if (p) params.set('p', p);
    if (s !== '3') params.set('s', s);
    if (x !== '2') params.set('x', x);
    if (r !== '4K') params.set('r', r);
    window.location = '/?' + params.toString();
}}
document.getElementById('palette').onchange = go;
document.getElementById('slot').onchange = go;
document.getElementById('scale').onchange = go;
var active = document.querySelector('#list a.active');
if (active) active.scrollIntoView({{block: 'center'}});

var dltiled = document.getElementById('dltiled');
if (dltiled) {{
    function updateTiledHref() {{
        var params = new URLSearchParams(window.location.search);
        params.set('dlwall', '1');
        params.set('res', document.getElementById('res').value);
        dltiled.href = '/?' + params.toString();
    }}
    updateTiledHref();
    document.getElementById('res').onchange = updateTiledHref;
}}

document.addEventListener('keydown', function(e) {{
    if (e.target.tagName === 'SELECT') return;
    var items = Array.from(document.querySelectorAll('#list a'));
    var palSel = document.getElementById('palette');
    var palOpts = Array.from(palSel.options);
    var idx = items.findIndex(function(a) {{ return a.classList.contains('active'); }});
    var palIdx = palSel.selectedIndex;

    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {{
        e.preventDefault();
        var next = e.key === 'ArrowDown' ? idx + 1 : idx - 1;
        if (next >= 0 && next < items.length) items[next].click();
    }} else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {{
        e.preventDefault();
        var next = e.key === 'ArrowRight' ? palIdx + 1 : palIdx - 1;
        if (next >= 0 && next < palOpts.length) {{ palSel.selectedIndex = next; go(); }}
    }} else if (e.key >= '1' && e.key <= '8') {{
        document.getElementById('slot').value = e.key;
        go();
    }}
}});
</script>
</body>
</html>"""


FAVICON = Path("favicon.png").read_bytes() if Path("favicon.png").exists() else b""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/favicon.png", "/favicon.ico"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(FAVICON)
            return

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/" and not params:
            self.send_response(302)
            self.send_header("Location", "/?b=ArtDeco&p=Broica")
            self.end_headers()
            return

        backdrop = params.get("b", [None])[0]
        palette = params.get("p", [None])[0]
        slot = int(params.get("s", ["3"])[0])
        scale = int(params.get("x", ["2"])[0])
        res = params.get("r", params.get("res", ["4K"]))[0]
        is_tile = "tile" in params
        is_download = "dl" in params
        is_wallpaper = "dlwall" in params

        if is_wallpaper and backdrop:
            try:
                data = render_tiled_wallpaper(backdrop, palette, slot, scale, res)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                parts = [backdrop]
                if palette:
                    parts.append(f"{palette}_s{slot}")
                parts.append(f"{scale}x")
                w, h = RESOLUTIONS[res]
                parts.append(f"{w}x{h}")
                filename = "_".join(parts) + ".png"
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_error(500, str(e))
        elif (is_tile or is_download) and backdrop:
            try:
                data = render_tile_png(backdrop, palette, slot, scale)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                if is_download:
                    parts = [backdrop]
                    if palette:
                        parts.append(f"{palette}_s{slot}")
                    parts.append(f"{scale}x")
                    filename = "_".join(parts) + ".png"
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                else:
                    self.send_header("Cache-Control", "public, max-age=60")
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_error(500, str(e))
        else:
            html = render_page(backdrop, palette, slot, scale, res)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

    def log_message(self, format, *args):
        print(f"  {args[0]}")


if __name__ == "__main__":
    print(f"Serving on http://localhost:{PORT}")
    HTTPServer(("", PORT), Handler).serve_forever()
