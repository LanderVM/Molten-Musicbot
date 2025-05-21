import asyncio
import json

import wavelink
from aiohttp import WSMsgType, web
from wavelink import Playable

_routes = web.RouteTableDef()

bot_instance = None
_current_tracks: dict[int, dict | None] = {}
_clients: set[web.WebSocketResponse] = set()


def _full_snapshot():
    """Return a list of all guild data + current track (or None) + connected state."""
    out = []
    for g in bot_instance.guilds:
        vc = g.voice_client
        connected = isinstance(vc, wavelink.Player) and vc.connected
        vc_member_count = 0
        if connected and vc.channel:
            vc_member_count = len(vc.channel.members)

        out.append(
            {
                "id": str(g.id),
                "name": g.name,
                "member_count": g.member_count,
                "icon": g.icon.url if g.icon else None,
                "connected": connected,
                "vc_member_count": vc_member_count,
                "current_track": _current_tracks.get(g.id),
            }
        )
    return out


@_routes.get("/")
async def index(request):
    html = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Molten Musicbot Dashboard</title>
  <style>
    /* Reset & body */
    *, *::before, *::after { box-sizing: border-box; margin:0; padding:0; }
    body {
      background: #2f3136;
      color: #dcddde;
      font-family: "Segoe UI", Roboto, sans-serif;
      line-height: 1.4;
      padding: 1rem;
    }
    h1 {
      margin-bottom: 1rem;
      color: #fff;
    }

    /* Grid of cards */
    #cards {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 1rem;
    }

    /* Card wrapper (Discord embed style) */
    .card {
      background: #36393f;
      border-radius: 8px;
      border-left: 4px solid #7289da;    /* accent bar */
      padding: 1rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }

    /* Header: icon + title */
    .card header {
      display: flex;
      align-items: center;
      margin-bottom: 0.75rem;
    }
    .card img.icon {
      width: 40px; height: 40px;
      border-radius: 50%;
      margin-right: 0.75rem;
    }
    .card header h2 {
      font-size: 1.1rem;
      font-weight: 500;
      color: #fff;
    }
    .card header span.members {
      margin-left: auto;
      font-size: 0.9rem;
      color: #b9bbbe;
    }

    /* Track section */
    .card .track {
      flex: 1;
      margin-bottom: 0.75rem;
    }
    .card img.thumb {
      width: 100%;
      max-height: 120px;
      object-fit: cover;
      border-radius: 4px;
      margin-bottom: 0.5rem;
    }
    .card .track p {
      margin: 0.25rem 0;
      font-size: 0.95rem;
    }
    .card .track a {
      color: #00b0f4;
      text-decoration: none;
    }
    .card .track a:hover {
      text-decoration: underline;
    }

    /* Footer: button */
    .card footer {
      text-align: right;
    }
    .card button {
      background: #4f545c;
      color: #fff;
      border: none;
      border-radius: 4px;
      padding: 0.5rem 0.75rem;
      font-size: 0.9rem;
      cursor: pointer;
      transition: background 0.2s;
    }
    .card button:hover {
      background: #646d7e;
    }
  </style>
</head>
<body>
  <h1>Molten Musicbot Dashboard</h1>
  <div id="cards"></div>

  <script>
    const cards = document.getElementById('cards');

    function renderGuild(g) {
      const div = document.createElement('div');
      div.className = 'card';

      // Header
      const icon = g.icon
        ? `<img class="icon" src="${g.icon}" alt="icon">`
        : '';
      const header = `
        <header>
          ${icon}
          <h2>${g.name}</h2>
          <span class="members">${g.member_count} members</span>
        </header>`;

      let vcStatus = '';
      if (g.connected) {
        if (g.vc_member_count <= 1) {
          vcStatus = `<p>🗣️ Alone in a call</p>`;
        } else {
          // subtract bot itself? If you want “with X others” where X excludes the bot:
          const others = g.vc_member_count - 1;
          vcStatus = `<p>🗣️ In a call with ${others} other${others === 1 ? '' : 's'}</p>`;
        }
      }

      // Track or placeholder
      let trackHTML = '';
      if (g.connected) {
        if (g.current_track) {
          const t = g.current_track;
          const thumb = t.thumbnail
            ? `<img class="thumb" src="${t.thumbnail}">`
            : '';
          trackHTML = `
            <div class="track">
              ${thumb}
              <p>🎶 <a href="${t.url}" target="_blank">${t.title}</a></p>
              ${vcStatus}
            </div>`;
        } else {
          trackHTML = `
            <div class="track">
              <p>⏸️ Connected (no song)</p>
              ${vcStatus}
            </div>`;
        }
      } else {
        trackHTML = `
          <div class="track">
            <p>🔌 Disconnected</p>
          </div>`;
      }

      // Footer with remove button
      const footer = `
        <footer>
          <button onclick="confirmRemove('${g.id}')">
            Remove from guild
          </button>
        </footer>`;

      div.innerHTML = header + trackHTML + footer;
      return div;
    }

    function refreshAll(data) {
      cards.innerHTML = '';
      data.forEach(g => cards.appendChild(renderGuild(g)));
    }

    function confirmRemove(gid) {
      if (!confirm("Make bot leave this guild?")) return;
      fetch(`/remove/${gid}`, { method: 'POST' })
        .then(r => r.json())
        .then(res => {
          if (!res.success) alert("Failed to remove");
        });
    }

    // WebSocket live updates
    const ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onmessage = e => {
      const data = JSON.parse(e.data);
      refreshAll(data);
    };
  </script>
</body>
</html>
"""
    return web.Response(text=html, content_type="text/html")


@_routes.get("/ws")
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    _clients.add(ws)

    await ws.send_str(json.dumps(_full_snapshot()))

    async for msg in ws:
        if msg.type == WSMsgType.ERROR:
            break

    _clients.remove(ws)
    return ws


@_routes.post("/remove/{guild_id}")
async def remove_guild(request):
    gid = int(request.match_info["guild_id"])
    guild = bot_instance.get_guild(gid)
    success = False
    if guild:
        try:
            await guild.leave()
            success = True
        except Exception:
            success = False

    data = json.dumps(_full_snapshot())
    for ws in list(_clients):
        asyncio.create_task(ws.send_str(data))

    return web.json_response({"success": success})


def start_dashboard(bot, host="127.0.0.1", port=5000):
    global bot_instance
    bot_instance = bot

    app = web.Application()
    app.add_routes(_routes)

    runner = web.AppRunner(app)
    loop = bot.loop

    async def _run():
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        print(f"📊 Dashboard running at http://{host}:{port}")

    loop.create_task(_run())


def notify_dashboard_guild(
    guild_id: int, track: Playable | None = None, preserve_current: bool = False
):
    """
    Call this on track start/end. Pass title+url+thumbnail
    thumbnail can be track.artwork or None.
    """
    if track:
        _current_tracks[guild_id] = {
            "title": track.title,
            "url": track.uri,
            "thumbnail": track.artwork,
        }
    elif not preserve_current:
        _current_tracks[guild_id] = None

    data = json.dumps(_full_snapshot())
    for ws in list(_clients):
        asyncio.create_task(ws.send_str(data))
