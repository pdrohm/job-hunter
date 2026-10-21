#!/usr/bin/env python3
"""
A small local web page for the WhatsApp summary bot: pick a chat (or all
unread chats), the start time and the options, press "Resumir", and watch it
run. The summaries show below, on the same page.

Usage:
    python -m whatsapp_summary.web            # http://127.0.0.1:8765 (opens the browser)
    python -m whatsapp_summary.web --no-open

It only listens on this Mac (127.0.0.1). Each run is the command line bot
(python -m whatsapp_summary.summary ...) in a child process, one at a time,
because the WhatsApp Chrome profile can only be open once.

Config: WA_WEB_PORT (default 8765).
"""

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from shared import telegram
from whatsapp_summary import report, summary

REPO_DIR = summary.REPO_DIR
HOST = "127.0.0.1"
MAX_LOG_LINES = 300


class Job:
    """The one bot run (summary or login) that can be active."""

    def __init__(self):
        self.lock = threading.Lock()
        self.proc: Optional[subprocess.Popen] = None
        self.kind = ""
        self.lines: deque[str] = deque(maxlen=MAX_LOG_LINES)
        self.started = 0.0
        self.exit_code: Optional[int] = None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, kind: str, args: list[str]) -> bool:
        with self.lock:
            if self.running():
                return False
            self.kind, self.started, self.exit_code = kind, time.time(), None
            self.lines.clear()
            env = dict(os.environ, PYTHONUNBUFFERED="1")
            self.proc = subprocess.Popen([sys.executable, "-m", "whatsapp_summary.summary", *args],
                                         cwd=REPO_DIR, env=env, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, bufsize=1)
            threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
            return True

    def _read(self, proc: subprocess.Popen):
        for line in proc.stdout:
            self.lines.append(line.rstrip())
        self.exit_code = proc.wait()

    def stop(self):
        if self.running():
            self.proc.terminate()

    def status(self) -> dict:
        return {"running": self.running(), "kind": self.kind, "lines": list(self.lines),
                "seconds": int(time.time() - self.started) if self.started else 0, "exit_code": self.exit_code}


def build_args(body: dict) -> list[str]:
    """The form → command line options. Raises ValueError on a bad form."""
    args = ["--no-open"]
    if body.get("mode") == "unread":
        args += ["--unread", "--max-chats", str(max(1, min(int(body.get("max_chats") or 10), 30)))]
        if body.get("include_muted"):
            args.append("--include-muted")
    else:
        chat = (body.get("chat") or "").strip()
        if not chat:
            raise ValueError("Escreva o nome da conversa.")
        args += ["--chat", chat]
    since = (body.get("since") or "").strip()
    if since:
        summary.parse_since(since)  # a clear error now, not in the log
        args += ["--since", since]
    if not body.get("audio", True):
        args.append("--no-audio")
    if body.get("telegram"):
        args.append("--telegram")
    return args


PANEL_CSS = """
.panel { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 18px 20px; margin-bottom: 26px; }
.row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 14px; }
.row:last-child { margin-bottom: 0; }
.label { width: 100%; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin-bottom: -4px; }
.status { display: flex; align-items: center; gap: 8px; font-size: 14px; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--warn); }
.dot.on { background: var(--accent); }
.seg { display: inline-flex; background: var(--bg); border: 1px solid var(--line); border-radius: 11px; padding: 3px; flex-wrap: wrap; }
.seg button { border: 0; background: transparent; color: var(--muted); font: inherit; font-size: 14px; padding: 6px 12px; border-radius: 8px; cursor: pointer; }
.seg button.on { background: var(--card); color: var(--ink); box-shadow: 0 1px 2px rgba(0,0,0,.12); }
.panel input[type=text], .panel input[type=number] { padding: 9px 12px; border-radius: 10px; border: 1px solid var(--line);
  background: var(--bg); color: var(--ink); font: inherit; min-width: 0; }
#chat { flex: 1 1 260px; } #since { flex: 0 1 200px; } #max { width: 76px; }
.check { display: inline-flex; gap: 7px; align-items: center; font-size: 14px; cursor: pointer; }
.check input { accent-color: var(--accent); width: 16px; height: 16px; }
.check.off { opacity: .5; cursor: not-allowed; }
.btn { border: 0; border-radius: 11px; padding: 10px 18px; font: inherit; font-weight: 600; cursor: pointer; }
.btn.go { background: var(--accent); color: #fff; }
.btn.ghost { background: transparent; color: var(--ink); border: 1px solid var(--line); font-weight: 500; }
.btn:disabled { opacity: .5; cursor: default; }
.hint { color: var(--muted); font-size: 13px; }
.err { color: #d4483b; font-size: 14px; }
.log { margin-top: 14px; background: var(--bg); border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px;
  font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--muted); max-height: 220px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
.log:empty { display: none; }
.spin { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--line); border-top-color: var(--accent);
  border-radius: 50%; animation: s 0.8s linear infinite; vertical-align: -2px; }
@keyframes s { to { transform: rotate(360deg); } }
[hidden] { display: none !important; }
"""

PANEL_JS = """
const $ = (id) => document.getElementById(id);
let mode = 'chat', sinceMode = 'last', wasRunning = false;
function seg(id, cb) {
  for (const b of $(id).querySelectorAll('button')) b.onclick = () => {
    for (const x of $(id).querySelectorAll('button')) x.classList.toggle('on', x === b);
    cb(b.dataset.v);
  };
}
seg('mode', v => { mode = v; $('chatRow').hidden = v !== 'chat'; $('unreadRow').hidden = v !== 'unread'; });
seg('sinceSeg', v => { sinceMode = v; $('since').hidden = v !== 'custom'; if (v === 'custom') $('since').focus(); });
function sinceValue() { return sinceMode === 'custom' ? $('since').value.trim() : (sinceMode === 'last' ? '' : sinceMode); }
async function post(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || 'Erro ' + r.status);
  return j;
}
$('go').onclick = async () => {
  $('err').textContent = '';
  try {
    await post('/api/run', {mode, chat: $('chat').value, since: sinceValue(), max_chats: $('max').value,
      include_muted: $('muted').checked, audio: $('audio').checked, telegram: $('tg').checked});
    poll();
  } catch (e) { $('err').textContent = e.message; }
};
$('login').onclick = async () => { $('err').textContent = ''; try { await post('/api/login'); poll(); } catch (e) { $('err').textContent = e.message; } };
$('stop').onclick = () => post('/api/stop').catch(() => {});
async function poll() {
  const s = await fetch('/api/status').then(r => r.json());
  $('dot').classList.toggle('on', s.linked);
  $('linkedText').textContent = s.linked ? 'WhatsApp conectado' : 'WhatsApp não conectado';
  $('login').hidden = s.linked && !(s.job.running && s.job.kind === 'login');
  const run = s.job.running;
  $('go').disabled = run || !s.linked; $('stop').hidden = !run; $('busy').hidden = !run;
  $('busyText').textContent = run ? (s.job.kind === 'login' ? 'Escaneie o QR code na janela do Chrome…' : 'Lendo e resumindo… ' + s.job.seconds + 's') : '';
  const log = $('log'); const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
  // The log shows while a run is going, and after a failed one
  log.textContent = (run || s.job.exit_code) ? s.job.lines.join('\\n') : ''; if (atEnd) log.scrollTop = log.scrollHeight;
  if (wasRunning && !run) {
    if (s.job.exit_code === 0) { location.reload(); return; }
    $('err').textContent = s.job.kind === 'login' ? '' : 'Não terminou. Veja o log acima.';
  }
  wasRunning = run;
  if (run) setTimeout(poll, 1200);
}
for (const id of ['chat', 'since']) $(id).addEventListener('keydown', e => { if (e.key === 'Enter') $('go').click(); });
poll();
"""


def panel_html(recent: list[str], tg_ok: bool) -> str:
    options = "".join(f'<option value="{report.escape(n)}">' for n in recent)
    tg = ('<label class="check"><input id="tg" type="checkbox"> Mandar no Telegram</label>' if tg_ok else
          '<label class="check off" title="Configure TELEGRAM_BOT_TOKEN no .env"><input id="tg" type="checkbox" disabled>'
          ' Mandar no Telegram</label>')
    return f"""
<section class="panel">
  <div class="row" style="justify-content:space-between">
    <div class="status"><span id="dot" class="dot"></span><span id="linkedText">…</span></div>
    <button id="login" class="btn ghost" hidden>Conectar (QR code)</button>
  </div>
  <div class="row"><div class="seg" id="mode">
    <button class="on" data-v="chat">Uma conversa</button><button data-v="unread">Todas não lidas</button></div></div>
  <div class="row" id="chatRow">
    <input id="chat" type="text" list="recent" placeholder="Nome exato da conversa" autocomplete="off">
    <datalist id="recent">{options}</datalist>
  </div>
  <div class="row" id="unreadRow" hidden>
    <span class="hint">Até</span><input id="max" type="number" min="1" max="30" value="10"><span class="hint">conversas</span>
    <label class="check"><input id="muted" type="checkbox"> Incluir silenciadas</label>
  </div>
  <div class="row"><span class="label">Desde</span>
    <div class="seg" id="sinceSeg">
      <button class="on" data-v="last">Último resumo</button><button data-v="12h">12h</button>
      <button data-v="24h">24h</button><button data-v="2d">2 dias</button><button data-v="custom">Outro…</button></div>
    <input id="since" type="text" placeholder="ontem 20:54" hidden>
  </div>
  <div class="row">
    <label class="check"><input id="audio" type="checkbox" checked> Ouvir áudios</label>
    {tg}
  </div>
  <div class="row">
    <button id="go" class="btn go" disabled>Resumir</button>
    <button id="stop" class="btn ghost" hidden>Parar</button>
    <span id="busy" class="hint" hidden><span class="spin"></span> <span id="busyText"></span></span>
    <span id="err" class="err"></span>
  </div>
  <div id="log" class="log"></div>
  <p class="hint" style="margin:12px 0 0">Só lê: nunca escreve nem envia. A conversa aberta fica lida no celular, e os áudios ficam ouvidos.</p>
</section>"""


def load_runs(cfg: summary.Config) -> list[dict]:
    runs = []
    for p in sorted((cfg.home / "runs").glob("*.json"), reverse=True):
        try:
            runs.append(json.loads(p.read_text()))
        except (OSError, json.JSONDecodeError):
            pass
    return runs


def create_app() -> FastAPI:
    cfg = summary.Config.from_env()
    job = Job()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    port = int(os.environ.get("WA_WEB_PORT", "8765"))
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Other websites must not drive the bot: check Host (DNS rebinding)
        # and Origin (a page elsewhere posting to localhost)
        origin = request.headers.get("origin")
        if request.headers.get("host") not in allowed_hosts or (
                origin and origin.split("//", 1)[-1] not in allowed_hosts):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def index():
        recent = sorted(summary.load_state(cfg), key=str.lower)
        return report.render(load_runs(cfg), panel=panel_html(recent, telegram.is_configured()),
                             css=PANEL_CSS, script=PANEL_JS, empty="Nada ainda. Escolha uma conversa acima e toque em Resumir.")

    @app.get("/api/status")
    def status():
        return {"linked": summary.is_linked(cfg), "job": job.status()}

    @app.post("/api/run")
    async def run(request: Request):
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"error": "JSON only"}, status_code=415)
        try:
            args = build_args(await request.json())
        except (ValueError, TypeError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        if not job.start("summary", args):
            return JSONResponse({"error": "Já tem um resumo rodando."}, status_code=409)
        return {"ok": True}

    @app.post("/api/login")
    def login():
        if not job.start("login", ["--login"]):
            return JSONResponse({"error": "Espere o resumo atual terminar."}, status_code=409)
        return {"ok": True}

    @app.post("/api/stop")
    def stop():
        job.stop()
        return {"ok": True}

    return app


def main():
    import uvicorn

    load_dotenv(REPO_DIR / ".env")
    port = int(os.environ.get("WA_WEB_PORT", "8765"))
    if "--no-open" not in sys.argv:
        threading.Timer(1.5, webbrowser.open, args=[f"http://{HOST}:{port}"]).start()
    uvicorn.run(create_app(), host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
