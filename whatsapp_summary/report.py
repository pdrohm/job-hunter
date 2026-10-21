"""
The HTML page: every run, newest first, one card per chat. One self-contained
file (no network), light and dark mode, with a search box.
"""

from datetime import datetime
from html import escape

CSS = """
:root {
  --bg: #f4f1ea; --card: #fffdf8; --ink: #1d2a24; --muted: #6b756f; --line: #e3ddd0;
  --accent: #128c5e; --accent-soft: #e2f3ea; --warn: #9a5b00; --warn-soft: #fbefd9; --me: #dff4e6;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0f1613; --card: #17211c; --ink: #e6ece8; --muted: #93a19a; --line: #26332c;
    --accent: #3fd18f; --accent-soft: #173326; --warn: #f2b45c; --warn-soft: #33270f; --me: #1c3427;
  }
}
:root[data-theme="dark"] {
  --bg: #0f1613; --card: #17211c; --ink: #e6ece8; --muted: #93a19a; --line: #26332c;
  --accent: #3fd18f; --accent-soft: #173326; --warn: #f2b45c; --warn-soft: #33270f; --me: #1c3427;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.wrap { max-width: 980px; margin: 0 auto; padding: 28px 16px 64px; }
header { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; justify-content: space-between; margin-bottom: 22px; }
h1 { margin: 0; font-size: 26px; letter-spacing: -.02em; }
h1 span { color: var(--accent); }
.sub { color: var(--muted); font-size: 13px; }
input[type=search] { flex: 1 1 240px; max-width: 340px; padding: 9px 12px; border-radius: 10px;
  border: 1px solid var(--line); background: var(--card); color: var(--ink); font: inherit; }
details.run { margin-bottom: 18px; }
details.run > summary { cursor: pointer; list-style: none; color: var(--muted); font-size: 13px;
  text-transform: uppercase; letter-spacing: .06em; padding: 6px 0; }
details.run > summary::before { content: "▸ "; }
details.run[open] > summary::before { content: "▾ "; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 18px 20px; margin: 10px 0 14px; }
.card h2 { margin: 0 0 2px; font-size: 18px; }
.meta { color: var(--muted); font-size: 13px; margin-bottom: 12px; }
.resumo { margin: 0 0 12px; }
.box { border-radius: 10px; padding: 10px 14px; margin: 10px 0; }
.box h3 { margin: 0 0 4px; font-size: 13px; text-transform: uppercase; letter-spacing: .05em; }
.box ul { margin: 0; padding-left: 18px; }
.mine { background: var(--warn-soft); } .mine h3 { color: var(--warn); }
.dec { background: var(--accent-soft); } .dec h3 { color: var(--accent); }
.plain h3 { color: var(--muted); } .plain { padding-left: 0; }
.ctx { margin: 0 0 12px; color: var(--muted); }
.ctx b { color: var(--ink); }
.tom { color: var(--muted); font-style: italic; font-size: 14px; }
details.chat { margin-top: 12px; border-top: 1px solid var(--line); padding-top: 10px; }
details.chat > summary { cursor: pointer; color: var(--accent); font-size: 14px; }
.msgs { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }
.msg { padding: 7px 11px; border-radius: 10px; border: 1px solid var(--line); max-width: 92%; overflow-wrap: anywhere; white-space: pre-wrap; }
.msg.out { align-self: flex-end; background: var(--me); }
.msg b { font-size: 13px; } .msg time { color: var(--muted); font-size: 12px; margin-left: 6px; }
.msg .a { color: var(--muted); }
.msg .q { display: block; color: var(--muted); font-size: 13px; border-left: 3px solid var(--accent); padding-left: 8px; margin: 2px 0 4px; }
.empty { color: var(--muted); padding: 40px 0; text-align: center; }
"""

JS = """
const q = document.getElementById('q');
q.addEventListener('input', () => {
  const t = q.value.toLowerCase();
  for (const c of document.querySelectorAll('.card')) c.hidden = t && !c.textContent.toLowerCase().includes(t);
  if (t) for (const d of document.querySelectorAll('details.run')) d.open = true;
});
"""


def _fmt(iso: str, fmt: str = "%d/%m %H:%M") -> str:
    try:
        return datetime.fromisoformat(iso).strftime(fmt)
    except (TypeError, ValueError):
        return ""


def _list(title: str, items: list, cls: str) -> str:
    if not items:
        return ""
    lis = "".join(f"<li>{escape(str(x))}</li>" for x in items)
    return f'<div class="box {cls}"><h3>{escape(title)}</h3><ul>{lis}</ul></div>'


def _card(chat: dict) -> str:
    s = chat.get("summary") or {}
    msgs = "".join(
        f'<div class="msg{" out" if m.get("out") else ""}"><b>{escape(m.get("author", ""))}</b>'
        f'<time>{_fmt(m.get("when", ""))}</time>\n'
        + (f'<span class="q">↪ {escape(" / ".join(m["quote"].splitlines()))}</span>\n' if m.get("quote") else "")
        + ('<span class="a">🎤 </span>' if m.get("audio") else "")
        + f'{escape(m.get("text") or ("(áudio sem transcrição)" if m.get("audio") else ""))}</div>'
        for m in chat.get("messages", []))
    resumo = s.get("resumo") or "Sem resumo (veja a conversa abaixo)."
    return (
        f'<article class="card"><h2>{escape(chat.get("name", ""))}</h2>'
        f'<div class="meta">{_fmt(chat.get("since", ""))} → {_fmt(chat.get("until", ""))} · '
        f'{chat.get("count", 0)} mensagens · {chat.get("audios", 0)} áudios</div>'
        f'<p class="resumo">{escape(resumo)}</p>'
        + (f'<p class="ctx"><b>Contexto:</b> {escape(s["contexto"])}</p>' if s.get("contexto") else "")
        + _list("Para você", s.get("para_mim", []), "mine")
        + _list("Decisões", s.get("decisoes", []), "dec")
        + _list("Assuntos", s.get("pontos", []), "plain")
        + (f'<p class="tom">{escape(s["tom"])}</p>' if s.get("tom") else "")
        + (f'<details class="chat"><summary>Conversa completa</summary><div class="msgs">{msgs}</div></details>'
           if msgs else "")
        + "</article>")


def render(runs: list[dict], panel: str = "", css: str = "", script: str = "",
           empty: str = 'Nada ainda. Rode: python -m whatsapp_summary.summary --chat "Nome"') -> str:
    """`runs` newest first, as saved in runs/*.json. The web page (web.py)
    adds its control `panel` above the cards, with its own `css` and `script`."""
    if runs:
        body = "".join(
            f'<details class="run"{" open" if i == 0 else ""}><summary>{_fmt(r.get("created", ""), "%d/%m/%Y %H:%M")}'
            f' · {len(r.get("chats", []))} conversa(s)</summary>{"".join(_card(c) for c in r.get("chats", []))}</details>'
            for i, r in enumerate(runs))
    else:
        body = f'<p class="empty">{escape(empty)}</p>'
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WhatsApp Resumo</title><style>{CSS}{css}</style></head>
<body><div class="wrap">
<header><div><h1>WhatsApp <span>Resumo</span></h1>
<div class="sub">Atualizado em {datetime.now().strftime("%d/%m/%Y %H:%M")}</div></div>
<input id="q" type="search" placeholder="Buscar conversa, pessoa ou assunto"></header>
{panel}
<div id="cards">{body}</div>
</div><script>{JS}{script}</script></body></html>
"""
