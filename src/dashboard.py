"""
Molten Musicbot — Web Dashboard
════════════════════════════════
Enable by adding to your .env:

    DASHBOARD_ENABLED=true
    DASHBOARD_SECRET=your_strong_password_here
    DASHBOARD_PORT=8080          # optional, default 8080
    DASHBOARD_HOST=0.0.0.0       # optional, default 0.0.0.0

The dashboard will be available at http://<host>:<port>/
Stats are persisted to data/dashboard_stats.json so history
survives bot restarts.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from music_bot import Bot

logger = logging.getLogger("dashboard")

STATS_FILE = "data/dashboard_stats.json"
_save_lock = asyncio.Lock()


# ── Persistence ──────────────────────────────────────────────────────────────

def _load_stats() -> dict:
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load dashboard stats: %s", e)
    return {}


def _save_stats_sync(data: dict) -> None:
    os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


async def _save_stats_async(data: dict) -> None:
    async with _save_lock:
        await asyncio.to_thread(_save_stats_sync, data)


# ── Auth ─────────────────────────────────────────────────────────────────────

def _make_token(secret: str) -> str:
    return hmac.new(
        secret.encode(), b"molten-dashboard-v1", hashlib.sha256
    ).hexdigest()


def _verify_token(token: str, secret: str) -> bool:
    try:
        return hmac.compare_digest(token, _make_token(secret))
    except Exception:
        return False


# ── Formatting ───────────────────────────────────────────────────────────────

def _fmt_playtime(ms: int) -> str:
    s = ms // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def _fmt_uptime(delta: timedelta) -> str:
    days = delta.days
    h, rem = divmod(delta.seconds, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if h or days:
        parts.append(f"{h}h")
    if m or h or days:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


# ── Embedded HTML ─────────────────────────────────────────────────────────────

_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Molten Dashboard · Login</title>
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    :root{
      --bg:#0b0c10;--surface:#13141e;--accent:#8b6cc8;
      --accent-glow:rgba(139,108,200,.35);--text:#e2e3ea;
      --text-muted:#7b7d8d;--border:#1e2030;--red:#ed4245;
    }
    body{background:var(--bg);color:var(--text);
      font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
      min-height:100vh;display:flex;align-items:center;justify-content:center;
      background-image:radial-gradient(ellipse at 60% 20%,rgba(139,108,200,.08) 0%,transparent 60%);
    }
    .box{
      width:360px;background:var(--surface);border:1px solid var(--border);
      border-radius:18px;padding:44px 38px;text-align:center;
      box-shadow:0 20px 60px rgba(0,0,0,.5);
    }
    .logo{font-size:3rem;margin-bottom:10px;display:block}
    h1{font-size:1.4rem;font-weight:700;margin-bottom:4px}
    .sub{color:var(--text-muted);font-size:.82rem;margin-bottom:34px;display:block}
    input[type=password]{
      width:100%;padding:12px 16px;background:var(--bg);
      border:1px solid var(--border);border-radius:9px;
      color:var(--text);font-size:.95rem;margin-bottom:14px;outline:none;
      transition:border-color .2s,box-shadow .2s;
    }
    input[type=password]:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow)}
    button{
      width:100%;padding:12px;background:var(--accent);color:#fff;
      border:none;border-radius:9px;font-size:.95rem;font-weight:700;
      cursor:pointer;letter-spacing:.03em;transition:opacity .2s,box-shadow .2s;
    }
    button:hover{opacity:.9;box-shadow:0 0 22px var(--accent-glow)}
    .err{color:var(--red);font-size:.82rem;margin-top:14px;min-height:18px}
  </style>
</head>
<body>
<div class="box">
  <span class="logo">🔥</span>
  <h1>Molten Dashboard</h1>
  <span class="sub">Enter your dashboard password to continue</span>
  <form method="POST" action="/login">
    <input type="password" name="password" placeholder="Password"
           autofocus autocomplete="current-password">
    <button type="submit">Sign In</button>
  </form>
  {{ERROR}}
</div>
</body>
</html>"""

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Molten Musicbot · Dashboard</title>
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    :root{
      --bg:#0b0c10;--surf:#13141e;--surf2:#1a1b27;--surf3:#21233a;
      --accent:#8b6cc8;--accent-glow:rgba(139,108,200,.28);
      --green:#3ba55c;--green-bg:rgba(59,165,92,.12);--green-border:rgba(59,165,92,.28);
      --red:#ed4245;--red-bg:rgba(237,66,69,.1);--red-border:rgba(237,66,69,.25);
      --yellow:#faa61a;--yellow-bg:rgba(250,166,26,.1);--yellow-border:rgba(250,166,26,.22);
      --text:#e2e3ea;--muted:#7b7d8d;--dim:#464858;
      --border:#1e2030;--border2:#2a2c40;
    }
    body{background:var(--bg);color:var(--text);
      font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
      font-size:13.5px;line-height:1.5;min-height:100vh;
    }

    /* Notification */
    #notif{
      position:fixed;top:18px;right:18px;z-index:9999;
      padding:11px 20px;border-radius:10px;font-weight:600;font-size:.82rem;
      transform:translateY(-60px);opacity:0;transition:transform .28s,opacity .28s;
      pointer-events:none;
    }
    #notif.show{transform:translateY(0);opacity:1}
    #notif.success{background:var(--green);color:#fff}
    #notif.error{background:var(--red);color:#fff}

    /* Header */
    header{
      position:sticky;top:0;z-index:100;
      background:rgba(11,12,16,.92);backdrop-filter:blur(14px);
      border-bottom:1px solid var(--border);
      padding:0 24px;height:60px;
      display:flex;align-items:center;gap:20px;
    }
    .brand{display:flex;align-items:center;gap:10px;min-width:180px}
    .brand-icon{font-size:1.5rem;line-height:1}
    .brand-text h1{font-size:.95rem;font-weight:700;letter-spacing:.01em}
    .brand-text span{font-size:.68rem;color:var(--muted);letter-spacing:.06em;text-transform:uppercase}

    .h-pills{display:flex;align-items:center;gap:7px;flex:1;flex-wrap:wrap}
    .pill{
      display:flex;align-items:center;gap:5px;
      background:var(--surf);border:1px solid var(--border);
      border-radius:999px;padding:4px 12px;font-size:.75rem;color:var(--muted);
      white-space:nowrap;
    }
    .pill b{color:var(--text);font-weight:600}
    .dot{width:7px;height:7px;border-radius:50%;background:var(--dim);flex-shrink:0}
    .dot.g{background:var(--green);box-shadow:0 0 5px rgba(59,165,92,.5)}
    .dot.r{background:var(--red)}
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
    .dot.pulse{animation:pulse 2s ease-in-out infinite}

    .h-right{display:flex;align-items:center;gap:10px;margin-left:auto}
    #h-refresh{font-size:.7rem;color:var(--dim);white-space:nowrap}
    .btn-logout{
      padding:5px 13px;border-radius:7px;
      background:var(--surf3);border:1px solid var(--border);
      color:var(--muted);font-size:.75rem;text-decoration:none;
      transition:color .2s,border-color .2s;
    }
    .btn-logout:hover{color:var(--text);border-color:var(--muted)}

    /* Main */
    main{padding:24px 24px;max-width:1440px;margin:0 auto}
    .sec-title{
      font-size:.65rem;font-weight:700;letter-spacing:.1em;
      text-transform:uppercase;color:var(--dim);margin-bottom:14px;
    }

    /* Grid */
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}

    /* Card */
    .card{
      background:var(--surf);border:1px solid var(--border);border-radius:14px;
      display:flex;flex-direction:column;overflow:hidden;
      transition:border-color .2s,box-shadow .15s;
    }
    .card:hover{border-color:var(--border2);box-shadow:0 4px 20px rgba(0,0,0,.3)}
    .card.playing{border-color:var(--green-border);box-shadow:0 0 0 1px var(--green-border)}

    /* Card header */
    .c-head{
      display:flex;align-items:center;gap:11px;
      padding:14px 15px 12px;border-bottom:1px solid var(--border);
    }
    .c-icon{
      width:42px;height:42px;border-radius:11px;object-fit:cover;
      flex-shrink:0;background:var(--surf3);
    }
    .c-icon-ph{
      width:42px;height:42px;border-radius:11px;background:var(--surf3);
      display:flex;align-items:center;justify-content:center;
      font-size:1.2rem;flex-shrink:0;
    }
    .c-meta{flex:1;min-width:0}
    .c-name{
      font-weight:700;font-size:.9rem;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
    }
    .c-members{color:var(--muted);font-size:.72rem;margin-top:1px}
    .sbadge{
      padding:3px 9px;border-radius:999px;font-size:.67rem;
      font-weight:700;letter-spacing:.05em;white-space:nowrap;flex-shrink:0;
    }
    .sb-play{background:var(--green-bg);color:var(--green);border:1px solid var(--green-border)}
    .sb-idle{background:var(--surf3);color:var(--dim);border:1px solid var(--border)}

    /* Now Playing */
    .np{padding:11px 15px;border-bottom:1px solid var(--border);min-height:54px}
    .np-lbl{
      font-size:.62rem;font-weight:700;letter-spacing:.08em;
      text-transform:uppercase;color:var(--dim);margin-bottom:4px;
    }
    .np-track{
      color:var(--text);font-weight:600;font-size:.84rem;
      text-decoration:none;display:block;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
      transition:color .18s;
    }
    .np-track:hover{color:var(--accent)}
    .np-none{color:var(--dim);font-style:italic;font-size:.82rem}
    .eq{display:flex;gap:2px;align-items:flex-end;height:11px;margin-top:5px}
    .eq span{
      display:block;width:3px;background:var(--green);border-radius:2px;
      animation:eq 1.2s ease-in-out infinite;
    }
    .eq span:nth-child(1){height:4px;animation-delay:0s}
    .eq span:nth-child(2){height:9px;animation-delay:.2s}
    .eq span:nth-child(3){height:6px;animation-delay:.4s}
    .eq span:nth-child(4){height:11px;animation-delay:.1s}
    .eq span:nth-child(5){height:5px;animation-delay:.3s}
    @keyframes eq{0%,100%{transform:scaleY(1)}50%{transform:scaleY(.25)}}

    /* Stats grid */
    .c-stats{
      padding:11px 15px;border-bottom:1px solid var(--border);
      display:grid;grid-template-columns:1fr 1fr;gap:7px;
    }
    .si{display:flex;align-items:center;gap:6px}
    .si-ico{font-size:.85rem;width:17px;text-align:center;flex-shrink:0}
    .si-txt{color:var(--muted);font-size:.77rem;min-width:0;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .si-txt b{color:var(--text);font-weight:600}

    /* Badges */
    .c-badges{
      padding:9px 15px;border-bottom:1px solid var(--border);
      display:flex;gap:5px;flex-wrap:wrap;min-height:36px;align-items:center;
    }
    .badge{
      padding:2px 8px;border-radius:4px;
      font-size:.67rem;font-weight:700;letter-spacing:.04em;
    }
    .b247{background:var(--yellow-bg);color:var(--yellow);border:1px solid var(--yellow-border)}
    .bdj{background:var(--accent-glow);color:var(--accent);border:1px solid rgba(139,108,200,.3)}
    .bch{background:var(--surf3);color:var(--muted);border:1px solid var(--border)}
    .no-b{color:var(--dim);font-size:.72rem;font-style:italic}

    /* Footer */
    .c-foot{padding:11px 15px;display:flex;align-items:center;gap:8px}
    .lt{flex:1;min-width:0}
    .lt-lbl{font-size:.62rem;color:var(--dim);text-transform:uppercase;letter-spacing:.05em}
    .lt-name{
      font-size:.76rem;color:var(--muted);
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
    }
    .btn-leave{
      padding:6px 13px;border-radius:8px;
      background:var(--red-bg);border:1px solid var(--red-border);
      color:var(--red);font-size:.75rem;font-weight:600;
      cursor:pointer;white-space:nowrap;flex-shrink:0;
      transition:background .18s,border-color .18s;
    }
    .btn-leave:hover{background:rgba(237,66,69,.2);border-color:rgba(237,66,69,.5)}
    .btn-leave:disabled{opacity:.45;cursor:not-allowed}

    /* States */
    .loading,.empty{
      grid-column:1/-1;text-align:center;
      padding:80px 24px;color:var(--muted);
    }
    .spinner{
      width:34px;height:34px;border:3px solid var(--border);
      border-top-color:var(--accent);border-radius:50%;
      animation:spin 1s linear infinite;margin:0 auto 14px;
    }
    @keyframes spin{to{transform:rotate(360deg)}}
    .e-ico{font-size:2.5rem;margin-bottom:10px}
    .e-txt{font-size:.88rem}

    @media(max-width:640px){
      header{height:auto;flex-wrap:wrap;padding:10px 14px;gap:10px}
      main{padding:14px}
      .grid{grid-template-columns:1fr}
    }
  </style>
</head>
<body>

<div id="notif"></div>

<header>
  <div class="brand">
    <span class="brand-icon">🔥</span>
    <div class="brand-text">
      <h1>Molten Musicbot</h1>
      <span>Dashboard</span>
    </div>
  </div>

  <div class="h-pills">
    <div class="pill">⏱️ Uptime: <b id="h-uptime">…</b></div>
    <div class="pill">
      <span id="h-ll-dot" class="dot"></span>
      Lavalink: <b id="h-ll-lbl">…</b>
    </div>
    <div class="pill" id="h-ll-addr-pill" style="display:none">
      🔗 <b id="h-ll-addr">…</b>
    </div>
    <div class="pill">🏠 Servers: <b id="h-guilds">…</b></div>
  </div>

  <div class="h-right">
    <span id="h-refresh">–</span>
    <a href="/logout" class="btn-logout">Logout</a>
  </div>
</header>

<main>
  <p class="sec-title" id="sec-lbl">Servers</p>
  <div class="grid" id="grid">
    <div class="loading"><div class="spinner"></div><p>Connecting…</p></div>
  </div>
</main>

<script>
(function(){
'use strict';

const $=id=>document.getElementById(id);
let busy=false,firstLoad=true;

// ── Fetch loop ────────────────────────────────────────────────────────────────
async function refresh(){
  if(busy)return;busy=true;
  try{
    const r=await fetch('/api/stats');
    if(r.status===401){location.href='/login';return;}
    if(!r.ok)throw new Error('HTTP '+r.status);
    const d=await r.json();
    render(d);
    $('h-refresh').textContent='Updated '+new Date().toLocaleTimeString();
    firstLoad=false;
  }catch(e){
    if(firstLoad)renderGrid([]);
    notify('⚠️ '+e.message,'error');
  }finally{busy=false;}
}

// ── Render ────────────────────────────────────────────────────────────────────
function render(d){
  $('h-uptime').textContent=d.uptime;
  $('h-guilds').textContent=d.guild_count;
  $('sec-lbl').textContent='Servers ('+d.guild_count+')';

  const dot=$('h-ll-dot'),lbl=$('h-ll-lbl'),ap=$('h-ll-addr-pill');
  if(d.lavalink_connected){
    dot.className='dot g pulse';lbl.textContent='Connected';
    $('h-ll-addr').textContent=d.lavalink_host+':'+d.lavalink_port;
    ap.style.display='';
  }else{
    dot.className='dot r';lbl.textContent='Disconnected';ap.style.display='none';
  }
  renderGrid(d.guilds);
}

function renderGrid(guilds){
  const grid=$('grid');
  if(!guilds.length){
    grid.innerHTML='<div class="empty"><div class="e-ico">🎵</div><p class="e-txt">No servers yet.</p></div>';
    return;
  }
  grid.innerHTML='';
  guilds.forEach(g=>grid.appendChild(card(g)));
}

// ── Card ──────────────────────────────────────────────────────────────────────
function card(g){
  const el=document.createElement('div');
  el.className='card'+(g.is_playing?' playing':'');

  const iconHtml=g.icon_url
    ?`<img class="c-icon" src="${x(g.icon_url)}" alt="" loading="lazy">`
    :`<div class="c-icon-ph">🎵</div>`;

  const sBadge=g.is_playing
    ?'<span class="sbadge sb-play">▶ Playing</span>'
    :'<span class="sbadge sb-idle">⏸ Idle</span>';

  let npHtml;
  if(g.now_playing){
    const href=g.now_playing_url?`href="${x(g.now_playing_url)}" target="_blank" rel="noopener"`:'';
    npHtml=`<a class="np-track" ${href}>${x(g.now_playing)}</a>
            <div class="eq"><span></span><span></span><span></span><span></span><span></span></div>`;
  }else{
    npHtml='<span class="np-none">Nothing playing</span>';
  }

  const voiceTxt=g.voice_channel
    ?`<b>${g.voice_members}</b> listener${g.voice_members!==1?'s':''} · <b>#${x(g.voice_channel)}</b>`
    :'Not in voice';

  let badges='';
  if(g.stay_247)badges+='<span class="badge b247">24/7</span>';
  if(g.has_dj_role)badges+='<span class="badge bdj">🎧 DJ Role</span>';
  if(g.setup_channel)badges+=`<span class="badge bch">#${x(g.setup_channel)}</span>`;
  if(!badges)badges='<span class="no-b">No special modes active</span>';

  const lastTxt=g.last_played_at?fmtRel(g.last_played_at):'never';
  const ltHtml=g.last_track
    ?`<div class="lt">
        <div class="lt-lbl">Last played · ${lastTxt}</div>
        <div class="lt-name">${x(g.last_track)}</div>
      </div>`
    :`<div class="lt"></div>`;

  el.innerHTML=`
    <div class="c-head">
      ${iconHtml}
      <div class="c-meta">
        <div class="c-name">${x(g.name)}</div>
        <div class="c-members">👥 ${fmt(g.member_count)} members</div>
      </div>
      ${sBadge}
    </div>

    <div class="np">
      <div class="np-lbl">Now Playing</div>
      ${npHtml}
    </div>

    <div class="c-stats">
      <div class="si"><span class="si-ico">🎤</span><span class="si-txt">${voiceTxt}</span></div>
      <div class="si"><span class="si-ico">📋</span><span class="si-txt"><b>${g.queue_length}</b> in queue</span></div>
      <div class="si"><span class="si-ico">⏱️</span><span class="si-txt"><b>${g.total_playtime_formatted}</b> total play</span></div>
      <div class="si"><span class="si-ico">🎵</span><span class="si-txt"><b>${fmt(g.total_tracks_played)}</b> tracks played</span></div>
      <div class="si"><span class="si-ico">📅</span><span class="si-txt">Joined <b>${g.joined_at?fmtDate(g.joined_at):'unknown'}</b></span></div>
      <div class="si"><span class="si-ico">🕐</span><span class="si-txt">Last active <b>${lastTxt}</b></span></div>
    </div>

    <div class="c-badges">${badges}</div>

    <div class="c-foot">
      ${ltHtml}
      <button class="btn-leave" data-gid="${g.id}" data-gname="${x(g.name)}">
        🚪 Leave
      </button>
    </div>`;
  return el;
}

// ── Actions ───────────────────────────────────────────────────────────────────
async function leaveServer(id,name,btn){
  if(!confirm('Leave "'+name+'"?\\n\\nThe bot will disconnect from voice and the queue will be cleared.'))return;
  btn.disabled=true;btn.textContent='⌛ Leaving…';
  try{
    const r=await fetch('/api/leave/'+id,{method:'POST'});
    const d=await r.json();
    if(d.success){notify('✅ Left '+name);setTimeout(refresh,1200);}
    else{notify('❌ '+(d.error||'Unknown error'),'error');btn.disabled=false;btn.textContent='🚪 Leave';}
  }catch(e){
    notify('❌ '+e.message,'error');btn.disabled=false;btn.textContent='🚪 Leave';
  }
};

// ── Utils ─────────────────────────────────────────────────────────────────────
function x(s){const d=document.createElement('div');d.appendChild(document.createTextNode(String(s)));return d.innerHTML;}
function fmt(n){return(n??0).toLocaleString();}
function fmtDate(iso){
  try{return new Date(iso).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});}
  catch{return '–';}
}
function fmtRel(iso){
  try{
    const diff=(Date.now()-new Date(iso))/1000;
    if(diff<60)return 'just now';
    if(diff<3600)return Math.floor(diff/60)+'m ago';
    if(diff<86400)return Math.floor(diff/3600)+'h ago';
    return Math.floor(diff/86400)+'d ago';
  }catch{return '–';}
}
function notify(msg,type='success'){
  const n=$('notif');n.textContent=msg;n.className='show '+type;
  clearTimeout(n._t);n._t=setTimeout(()=>{n.className='';},3500);
}

// ── Init ──────────────────────────────────────────────────────────────────────
// Delegated click handler — avoids all inline-onclick escaping issues
document.addEventListener('click',function(e){
  const btn=e.target.closest('.btn-leave');
  if(!btn||btn.disabled)return;
  leaveServer(btn.dataset.gid,btn.dataset.gname,btn);
});
refresh();
setInterval(refresh,5000);
})();
</script>
</body>
</html>"""


# ── Dashboard class ───────────────────────────────────────────────────────────

class Dashboard:
    """
    Web dashboard for Molten Musicbot.

    Lifecycle:
        await dashboard.start()   — call once during bot startup
        await dashboard.stop()    — call during bot shutdown

    Stats hooks (call from your event cog):
        dashboard.record_track_start(guild_id, title)
        dashboard.record_track_end(guild_id)
        dashboard.record_guild_join(guild_id)
    """

    def __init__(
        self,
        bot: "Bot",
        secret: str,
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        self.bot = bot
        self.secret = secret
        self.host = host
        self.port = port
        self.stats: dict = _load_stats()
        # guild_id (int) -> unix timestamp of track start
        self._track_start: dict[int, float] = {}
        self._runner: web.AppRunner | None = None
        self.app = web.Application()
        self._setup_routes()

    # ── Routes ────────────────────────────────────────────────────────────────

    def _setup_routes(self) -> None:
        r = self.app.router
        r.add_get("/", self._handle_dashboard)
        r.add_get("/login", self._handle_login_page)
        r.add_post("/login", self._handle_login)
        r.add_get("/logout", self._handle_logout)
        r.add_get("/api/stats", self._handle_api_stats)
        r.add_post("/api/leave/{guild_id}", self._handle_leave)

    def _authed(self, request: web.Request) -> bool:
        token = request.cookies.get("dashboard_token", "")
        return bool(token) and _verify_token(token, self.secret)

    # ── Page handlers ─────────────────────────────────────────────────────────

    async def _handle_dashboard(self, req: web.Request) -> web.Response:
        if not self._authed(req):
            return web.HTTPFound("/login")
        return web.Response(text=_DASHBOARD_HTML, content_type="text/html")

    async def _handle_login_page(self, req: web.Request) -> web.Response:
        if self._authed(req):
            return web.HTTPFound("/")
        err = req.rel_url.query.get("error", "")
        err_html = f'<p class="err">{err}</p>' if err else ""
        html = _LOGIN_HTML.replace("{{ERROR}}", err_html)
        return web.Response(text=html, content_type="text/html")

    async def _handle_login(self, req: web.Request) -> web.Response:
        data = await req.post()
        password = data.get("password", "")
        if password == self.secret:
            token = _make_token(self.secret)
            resp = web.HTTPFound("/")
            resp.set_cookie(
                "dashboard_token", token,
                httponly=True, samesite="Strict",
                max_age=86400 * 7,
            )
            return resp
        return web.HTTPFound("/login?error=Invalid+password")

    async def _handle_logout(self, req: web.Request) -> web.Response:
        resp = web.HTTPFound("/login")
        resp.del_cookie("dashboard_token")
        return resp

    # ── API handlers ──────────────────────────────────────────────────────────

    async def _handle_api_stats(self, req: web.Request) -> web.Response:
        if not self._authed(req):
            return web.json_response({"error": "Unauthorized"}, status=401)

        bot = self.bot
        uptime_delta = datetime.now(timezone.utc) - bot.start_time

        lavalink_connected = bot.is_lavalink_connected()
        lavalink_host = os.getenv("LAVALINK_HOST", "localhost")
        lavalink_port = os.getenv("LAVALINK_PORT", "2333")
        lavalink_last_ready = (
            bot.lavalink_last_ready_at.isoformat()
            if bot.lavalink_last_ready_at else None
        )

        guilds_data = []
        for guild in bot.guilds:
            g_stats = self.stats.get(str(guild.id), {})
            player = bot.get_player(guild.id)

            # Voice state
            vc = guild.voice_client
            voice_members = 0
            voice_channel_name = None
            if vc and vc.channel:
                voice_channel_name = vc.channel.name
                voice_members = sum(1 for m in vc.channel.members if not m.bot)

            # Now playing
            now_playing = None
            now_playing_url = None
            if player and player.current:
                now_playing = (
                    getattr(player.current, "title", None) or "Unknown"
                )
                now_playing_url = getattr(player.current, "uri", None)

            # Setup channel
            setup_data = bot.setup_channels.get(guild.id, {})
            ch_id = setup_data.get("channel")
            setup_channel_name = None
            if ch_id:
                ch = guild.get_channel(ch_id)
                setup_channel_name = ch.name if ch else None

            # Flags
            stay_247 = setup_data.get("stay_247", False)
            dj_role_id = setup_data.get("dj_role")
            has_dj_role = bool(dj_role_id and guild.get_role(dj_role_id))

            # Persistent stats + live session offset
            total_ms = g_stats.get("total_playtime_ms", 0)
            session_extra = 0
            if guild.id in self._track_start:
                session_extra = int(
                    (time.time() - self._track_start[guild.id]) * 1000
                )

            guilds_data.append({
                "id": str(guild.id),
                "name": guild.name,
                "icon_url": str(guild.icon.url) if guild.icon else None,
                "member_count": guild.member_count or 0,
                "voice_members": voice_members,
                "voice_channel": voice_channel_name,
                "now_playing": now_playing,
                "now_playing_url": str(now_playing_url) if now_playing_url else None,
                "queue_length": len(player.queue) if player else 0,
                "stay_247": stay_247,
                "has_dj_role": has_dj_role,
                "setup_channel": setup_channel_name,
                "joined_at": g_stats.get("joined_at"),
                "total_playtime_ms": total_ms + session_extra,
                "total_playtime_formatted": _fmt_playtime(total_ms + session_extra),
                "total_tracks_played": g_stats.get("total_tracks_played", 0),
                "last_played_at": g_stats.get("last_played_at"),
                "last_track": g_stats.get("last_track"),
                "is_playing": bool(now_playing),
            })

        return web.json_response({
            "uptime": _fmt_uptime(uptime_delta),
            "uptime_seconds": int(uptime_delta.total_seconds()),
            "lavalink_connected": lavalink_connected,
            "lavalink_host": lavalink_host,
            "lavalink_port": lavalink_port,
            "lavalink_last_ready": lavalink_last_ready,
            "guild_count": len(guilds_data),
            "guilds": guilds_data,
        })

    async def _handle_leave(self, req: web.Request) -> web.Response:
        if not self._authed(req):
            return web.json_response({"error": "Unauthorized"}, status=401)

        guild_id_str = req.match_info.get("guild_id", "")
        try:
            guild_id = int(guild_id_str)
        except ValueError:
            return web.json_response({"error": "Invalid guild ID"}, status=400)

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return web.json_response({"error": "Guild not found"}, status=404)

        try:
            player = self.bot.get_player(guild_id)
            if player:
                self.record_track_end(guild_id)
                player.queue.clear()
                await player.stop()
            if guild.voice_client:
                await guild.voice_client.disconnect(force=True)
            logger.info("Dashboard: left guild %s (%s)", guild.name, guild_id)
            return web.json_response({"success": True, "message": f"Left {guild.name}"})
        except Exception as e:
            logger.error("Dashboard leave failed for %s: %s", guild_id, e)
            return web.json_response({"error": str(e)}, status=500)

    # ── Stats tracking ────────────────────────────────────────────────────────

    def record_track_start(self, guild_id: int, track_title: str) -> None:
        """Call when a new track begins. Finalises any previous track first."""
        # Finalise previous track if already tracking
        self.record_track_end(guild_id)

        self._track_start[guild_id] = time.time()
        g = self.stats.setdefault(str(guild_id), {})
        g["last_played_at"] = datetime.now(timezone.utc).isoformat()
        g["last_track"] = track_title
        g["total_tracks_played"] = g.get("total_tracks_played", 0) + 1
        asyncio.create_task(_save_stats_async(self.stats))

    def record_track_end(self, guild_id: int) -> None:
        """Call when the current track ends (queue end, disconnect, etc.)."""
        start = self._track_start.pop(guild_id, None)
        if start is None:
            return
        elapsed_ms = int((time.time() - start) * 1000)
        g = self.stats.setdefault(str(guild_id), {})
        g["total_playtime_ms"] = g.get("total_playtime_ms", 0) + elapsed_ms
        asyncio.create_task(_save_stats_async(self.stats))

    def record_guild_join(self, guild_id: int) -> None:
        """Call when the bot joins a guild (or on startup to backfill)."""
        g = self.stats.setdefault(str(guild_id), {})
        if "joined_at" not in g:
            g["joined_at"] = datetime.now(timezone.utc).isoformat()
            asyncio.create_task(_save_stats_async(self.stats))

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info(
            "🌐 Dashboard running → http://%s:%d", self.host, self.port
        )

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            logger.info("Dashboard stopped.")