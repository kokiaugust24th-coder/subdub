"""同期再生プレイヤーの生成と、それを配信するHTTPサーバ。

`python -m http.server` は HTTP Range に非対応で、ブラウザが音声をシークできない
（`currentTime` の設定が反映されず同期が破綻する）ため、Range対応の実装を持つ。
"""

from __future__ import annotations

import os
import re
import webbrowser
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

__all__ = ["write_player", "serve", "RangeHandler"]

_TMPL = """<!doctype html>
<html lang="ja"><meta charset="utf-8">
<title>subdub — {title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{ color-scheme: dark; --bg:#0f0f0f; --fg:#eee; --dim:#888; --pill:#222; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
         font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:16px; }}
  h1 {{ font-size:15px; font-weight:600; margin:0 0 12px; color:var(--dim); }}
  #player {{ width:100%; aspect-ratio:16/9; background:#000; border-radius:8px; }}
  .bar {{ display:flex; gap:14px; align-items:center; flex-wrap:wrap;
          margin-top:12px; font-size:14px; }}
  .pill {{ background:var(--pill); border-radius:999px; padding:6px 14px; }}
  .ok {{ color:#5cd85c; }} .warn {{ color:#ffb454; }}
  label {{ display:flex; gap:6px; align-items:center; cursor:pointer; }}
  .hint {{ margin-top:14px; font-size:12px; color:var(--dim); line-height:1.7; }}
</style>
<div class="wrap">
  <h1>subdub — 吹き替え音声 同期再生</h1>
  <div id="player"></div>
  <audio id="dub" src="{audio}" preload="auto"></audio>
  <div class="bar">
    <span class="pill">ズレ <b id="drift">--</b></span>
    <label>音量 <input id="vol" type="range" min="0" max="1" step="0.05" value="1"></label>
    <label><input id="orig" type="checkbox"> 元音声も鳴らす</label>
    <span class="pill" id="state">読み込み中</span>
  </div>
  <p class="hint">
    動画は自動でミュートされ、生成した音声が同期再生されます。<br>
    シーク・一時停止・再生速度の変更に追従し、ズレが {tol} 秒を超えると自動補正します。
  </p>
</div>
<script src="https://www.youtube.com/iframe_api"></script>
<script>
const AUDIO=document.getElementById('dub'), DRIFT=document.getElementById('drift'),
      STATE=document.getElementById('state'), TOL={tol};
let yt=null, ready=false;

function onYouTubeIframeAPIReady(){{
  yt=new YT.Player('player',{{
    videoId:'{video}', playerVars:{{rel:0,modestbranding:1}},
    events:{{onReady:onReady,onStateChange:onState}}
  }});
}}
function onReady(){{
  ready=true;
  if(!document.getElementById('orig').checked) yt.mute();
  STATE.textContent='準備完了';
}}
function onState(e){{
  if(!ready) return;
  if(e.data===YT.PlayerState.PLAYING){{
    AUDIO.currentTime=yt.getCurrentTime();
    AUDIO.playbackRate=yt.getPlaybackRate();
    AUDIO.play().catch(()=>{{}});
    STATE.textContent='再生中';
  }} else {{
    AUDIO.pause();
    STATE.textContent = e.data===YT.PlayerState.ENDED ? '終了' : '一時停止';
  }}
}}
document.getElementById('vol').oninput=e=>{{AUDIO.volume=+e.target.value;}};
document.getElementById('orig').onchange=e=>{{
  if(ready) e.target.checked ? yt.unMute() : yt.mute();
}};
setInterval(()=>{{
  if(!ready||yt.getPlayerState()!==YT.PlayerState.PLAYING) return;
  const t=yt.getCurrentTime(), d=AUDIO.currentTime-t;
  DRIFT.textContent=(d>=0?'+':'')+d.toFixed(2)+' 秒';
  DRIFT.className=Math.abs(d)>TOL?'warn':'ok';
  if(Math.abs(d)>TOL) AUDIO.currentTime=t;
  const r=yt.getPlaybackRate();
  if(Math.abs(AUDIO.playbackRate-r)>0.01) AUDIO.playbackRate=r;
}},250);
</script>
</html>
"""


def write_player(path: str | Path, audio_name: str, video_id: str,
                 title: str = "", tol: float = 0.12) -> Path:
    p = Path(path)
    p.write_text(_TMPL.format(audio=audio_name, video=video_id,
                              title=title or video_id, tol=tol),
                 encoding="utf-8")
    return p


# --------------------------------------------------------------------------

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


class _Limited:
    """copyfile が読み過ぎないよう指定バイト数で打ち切るラッパ。"""

    def __init__(self, f, n: int):
        self.f, self.n = f, n

    def read(self, size: int = -1) -> bytes:
        if self.n <= 0:
            return b""
        if size is None or size < 0 or size > self.n:
            size = self.n
        data = self.f.read(size)
        self.n -= len(data)
        return data

    def close(self) -> None:
        self.f.close()


class RangeHandler(SimpleHTTPRequestHandler):
    """HTTP Range に対応した静的ファイルハンドラ。"""

    def send_head(self):
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()

        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None

        size = os.fstat(f.fileno()).st_size
        m = _RANGE.match(rng.strip())
        if not m:
            f.close()
            self.send_error(400, "Invalid Range")
            return None

        s, e = m.group(1), m.group(2)
        if s == "":
            length = min(int(e or 0), size)
            start, end = size - length, size - 1
        else:
            start = int(s)
            end = min(int(e) if e else size - 1, size - 1)

        if start >= size or start > end:
            f.close()
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None

        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        f.seek(start)
        return _Limited(f, end - start + 1)

    def send_response(self, code, message=None):
        super().send_response(code, message)
        if code == 200:
            self.send_header("Accept-Ranges", "bytes")

    def log_message(self, fmt, *args):
        pass


def serve(directory: str | Path, port: int = 8000, page: str = "player.html",
          open_browser: bool = True) -> None:
    root = str(Path(directory).resolve())
    srv = HTTPServer(("127.0.0.1", port), partial(RangeHandler, directory=root))
    url = f"http://localhost:{port}/{page}"
    print(f"\n  {url}\n  （Ctrl+C で停止）")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました。")
