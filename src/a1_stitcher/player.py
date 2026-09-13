"""Dependency-free guided sphere playback; camera motion remains editable data."""

import html
import json
from pathlib import Path
from urllib.parse import quote


def page(video_name, path):
    data = json.dumps(path, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")
    return (
        TEMPLATE.replace("__VIDEO__", html.escape(quote(video_name), quote=True))
        .replace("__PATH__", data)
        .encode()
    )


TEMPLATE = r"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>Pilot view · A1 Stitcher</title>
<style>body{margin:0;background:#101416;color:#e8eeef;font:16px system-ui}main{max-width:1400px;margin:auto;padding:20px}h1{font-size:24px}canvas{width:100%;aspect-ratio:16/9;background:#000;touch-action:none;border-radius:8px}video{display:none}button,input{font:inherit}button{padding:9px 14px;border:0;border-radius:6px;margin-right:8px}button[aria-pressed=true]{background:#b5f478}input{width:100%;margin:14px 0}p{color:#b5c4c8}.bar{display:flex;align-items:center;gap:10px}#status{margin-left:auto}</style>
<main><h1>Pilot view</h1><p>The full sphere stays available. Follow the recorded pilot view, or drag to look around.</p>
<canvas id="screen" aria-label="Interactive 360 video"></canvas>
<video id="video" src="__VIDEO__" preload="auto" playsinline></video>
<input id="seek" type="range" min="0" max="1" step="0.001" value="0" aria-label="Playback position">
<div class="bar"><button id="play">Play</button><button id="follow" aria-pressed="true">Follow pilot</button><button id="free" aria-pressed="false">Look around</button><span id="status">Loading…</span></div>
<p id="notice">Drag to look around. Scroll to zoom. Follow pilot smoothly returns to the recorded direction.</p></main>
<script id="path" type="application/json">__PATH__</script><script>
'use strict';
const path=JSON.parse(document.querySelector('#path').textContent),keys=path.samples;
const video=document.querySelector('#video'),canvas=document.querySelector('#screen'),gl=canvas.getContext('webgl'),seek=document.querySelector('#seek'),status=document.querySelector('#status');
let follow=true,base=[0,0,0,1],drag=null,yaw=0,pitch=0,fov=path.hfov_degrees,returnStart=null,returnFrom=null;
const norm=q=>{let n=Math.hypot(...q);return q.map(x=>x/n)};
function slerp(a,b,t){let d=a.reduce((v,x,i)=>v+x*b[i],0);if(d<0){b=b.map(x=>-x);d=-d}if(d>.9995)return norm(a.map((x,i)=>x+(b[i]-x)*t));let angle=Math.acos(Math.min(1,d)),s=Math.sin(angle);return a.map((x,i)=>(x*Math.sin((1-t)*angle)+b[i]*Math.sin(t*angle))/s)}
function at(t){let lo=0,hi=keys.length-1;while(lo+1<hi){let mid=(lo+hi)>>1;if(keys[mid].time<=t)lo=mid;else hi=mid}let a=keys[lo],b=keys[hi];return slerp(a.quaternion,b.quaternion,b.time===a.time?0:Math.max(0,Math.min(1,(t-a.time)/(b.time-a.time))))}
function multiply(a,b){let[x,y,z,w]=a,[X,Y,Z,W]=b;return [w*X+x*W+y*Z-z*Y,w*Y-x*Z+y*W+z*X,w*Z+x*Y-y*X+z*W,w*W-x*X-y*Y-z*Z]}
function current(){let q=follow?at(video.currentTime):multiply(base,multiply([0,Math.sin(yaw/2),0,Math.cos(yaw/2)],[Math.sin(pitch/2),0,0,Math.cos(pitch/2)]));if(returnStart!==null){let t=Math.min(1,(performance.now()-returnStart)/700);q=slerp(returnFrom,q,t*t*(3-2*t));if(t===1)returnStart=null}return q}
function mode(value){let q=current();follow=value;returnStart=null;if(value){returnFrom=q;returnStart=performance.now()}else{base=q;yaw=0;pitch=0}document.querySelector('#follow').setAttribute('aria-pressed',value);document.querySelector('#free').setAttribute('aria-pressed',!value)}
document.querySelector('#follow').onclick=()=>mode(true);document.querySelector('#free').onclick=()=>mode(false);
canvas.onpointerdown=e=>{mode(false);drag=[e.clientX,e.clientY,yaw,pitch];canvas.setPointerCapture(e.pointerId)};
canvas.onpointermove=e=>{if(drag){yaw=drag[2]-(e.clientX-drag[0])*.004;pitch=Math.max(-1.4,Math.min(1.4,drag[3]+(e.clientY-drag[1])*.004))}};
canvas.onpointerup=canvas.onpointercancel=()=>{drag=null};
canvas.onwheel=e=>{e.preventDefault();fov=Math.max(30,Math.min(120,fov+e.deltaY*.04))};
document.querySelector('#play').onclick=()=>{if(video.paused)video.play().catch(e=>status.textContent=e.message);else video.pause()};
video.onplay=()=>document.querySelector('#play').textContent='Pause';video.onpause=()=>document.querySelector('#play').textContent='Play';
video.onloadedmetadata=()=>{seek.max=video.duration};video.onerror=()=>status.textContent='Video could not load. Use a browser-compatible encode and a localhost server.';
seek.oninput=()=>{video.currentTime=Number(seek.value);returnStart=null};
if(!gl)throw Error('WebGL is required');
function shader(type,source){let s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s}
const program=gl.createProgram();
gl.attachShader(program,shader(gl.VERTEX_SHADER,'attribute vec2 p;varying vec2 v;void main(){v=p;gl_Position=vec4(p,0.,1.);}'));
gl.attachShader(program,shader(gl.FRAGMENT_SHADER,'precision highp float;varying vec2 v;uniform sampler2D tex;uniform vec4 q;uniform float scale;uniform float aspect;void main(){vec3 r=normalize(vec3(v.x*scale,-v.y*scale/aspect,1.));vec3 c=2.*cross(q.xyz,r);r=r+q.w*c+cross(q.xyz,c);vec2 uv=vec2(fract(atan(r.x,r.z)/6.28318530718+.5),asin(clamp(r.y,-1.,1.))/3.14159265359+.5);gl_FragColor=texture2D(tex,uv);}'));
gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));gl.useProgram(program);
let buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
let p=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(p);gl.vertexAttribPointer(p,2,gl.FLOAT,false,0,0);
let tex=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,tex);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
function draw(){let w=Math.round(canvas.clientWidth*devicePixelRatio),h=Math.round(w*9/16);if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;gl.viewport(0,0,w,h)}if(video.readyState>=2){try{gl.texImage2D(gl.TEXTURE_2D,0,gl.RGB,gl.RGB,gl.UNSIGNED_BYTE,video);gl.uniform4fv(gl.getUniformLocation(program,'q'),current());gl.uniform1f(gl.getUniformLocation(program,'scale'),Math.tan(fov*Math.PI/360));gl.uniform1f(gl.getUniformLocation(program,'aspect'),w/h);gl.drawArrays(gl.TRIANGLES,0,6);seek.value=video.currentTime;status.textContent=video.currentTime.toFixed(1)+' / '+video.duration.toFixed(1)+' s'}catch(e){status.textContent=e.message}}requestAnimationFrame(draw)}draw();
</script></html>"""


def sidecar_paths(output):
    return [Path(str(output) + ".viewport.json"), Path(str(output) + ".view.html")]


def serve(video, port=8778, progress=None):
    """Serve only the chosen video and its receipt-verified guided viewer."""
    import re
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import unquote, urlsplit

    from .errors import StitchError
    from .storage import digest, load_json

    video = Path(video).resolve(strict=True)
    sidecars = sidecar_paths(video)
    saved = load_json(str(video) + ".receipt.json")
    if saved.get("output_sha256") != digest(video):
        raise StitchError("Video differs from its receipt")
    for p in sidecars:
        if (
            p.is_symlink()
            or not p.is_file()
            or saved.get("viewport_files", {}).get(p.name) != digest(p)
        ):
            raise StitchError("Guided viewport sidecar is missing or differs from its receipt")
    assets = {
        "/": (sidecars[1], "text/html; charset=utf-8"),
        "/" + video.name: (video, "video/mp4" if video.suffix == ".mp4" else "video/quicktime"),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_HEAD(self):
            self.deliver(False)

        def do_GET(self):
            self.deliver(True)

        def deliver(self, body):
            item = assets.get(unquote(urlsplit(self.path).path))
            if item is None:
                self.send_error(404)
                return
            path, mime = item
            size = path.stat().st_size
            start, end, code = 0, size - 1, 200
            header = self.headers.get("Range")
            if header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
                if not match or not any(match.groups()):
                    self.send_error(416)
                    return
                a, b = match.groups()
                if a:
                    start, end = int(a), min(int(b) if b else end, end)
                else:
                    start = max(0, size - int(b))
                if start > end or start >= size:
                    self.send_error(416)
                    return
                code = 206
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("X-Content-Type-Options", "nosniff")
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if body:
                try:
                    with path.open("rb") as stream:
                        stream.seek(start)
                        left = end - start + 1
                        while left:
                            data = stream.read(min(left, 1024 * 1024))
                            if not data:
                                break
                            self.wfile.write(data)
                            left -= len(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

    if type(port) is not int or not 0 <= port <= 65535:
        raise StitchError("Invalid local viewer port")
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        if progress:
            progress(dict(status="serving", url=f"http://127.0.0.1:{server.server_port}/"))
        server.serve_forever()
