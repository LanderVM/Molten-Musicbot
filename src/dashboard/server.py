"""Molten Musicbot web dashboard with delta-SSE updates."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from aiohttp import web

from .auth import LOGIN_ATTEMPTS, LOGIN_WINDOW, SESSION_SECONDS
from .stats import _fmt_playtime, _fmt_uptime, _load_stats, _save_stats_sync

if TYPE_CHECKING:
    from music_bot import Bot

logger = logging.getLogger("dashboard")
PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
_LOGIN_HTML = (PACKAGE_DIR / "templates" / "login.html").read_text(encoding="utf-8")
_DASHBOARD_HTML = (PACKAGE_DIR / "templates" / "dashboard.html").read_text(
    encoding="utf-8"
)
STREAM_INTERVAL = 2.0


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
        dashboard.notify_change()  # optional immediate SSE check after commands
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
        self._sessions: dict[str, tuple[float, str]] = {}
        self._login_csrf: dict[str, float] = {}
        self._login_failures: dict[str, list[float]] = {}
        self._save_task: asyncio.Task | None = None
        self._stream_task: asyncio.Task | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._stream_wakeup = asyncio.Event()
        # guild_id (int) -> unix timestamp of track start
        self._track_start: dict[int, float] = {}
        self._track_elapsed: dict[int, float] = {}
        self._runner: web.AppRunner | None = None
        self.app = web.Application()
        self._setup_routes()

    # ── Routes ────────────────────────────────────────────────────────────────

    def _setup_routes(self) -> None:
        r = self.app.router
        r.add_get("/", self._handle_dashboard)
        r.add_get("/static/login.css", self._handle_static_login_css)
        r.add_get("/static/dashboard.css", self._handle_static_dashboard_css)
        r.add_get("/static/dashboard.js", self._handle_static_dashboard_js)
        r.add_get("/login", self._handle_login_page)
        r.add_post("/login", self._handle_login)
        r.add_post("/logout", self._handle_logout)
        r.add_get("/api/stats", self._handle_api_stats)
        r.add_get("/api/events", self._handle_events)
        r.add_post("/api/leave/{guild_id}", self._handle_leave)

    def _session(self, req: web.Request) -> tuple[str, str] | None:
        token = req.cookies.get("dashboard_token", "")
        record = self._sessions.get(token)
        if not record:
            return None
        expires, csrf = record
        if expires <= time.time():
            self._sessions.pop(token, None)
            return None
        return token, csrf

    def _authed(self, req: web.Request) -> bool:
        return self._session(req) is not None

    @staticmethod
    def _same_origin(req: web.Request) -> bool:
        # Origin or Referer is checked against the browser-visible Host. A proxy must
        # preserve the Host header (and terminate HTTPS itself).
        source = req.headers.get("Origin") or req.headers.get("Referer")
        if not source:
            return False
        try:
            url = urlsplit(source)
            return url.scheme in ("http", "https") and url.netloc == req.host
        except ValueError:
            return False

    def _csrf_ok(self, req: web.Request) -> bool:
        session = self._session(req)
        supplied = req.headers.get("X-CSRF-Token", "")
        return bool(
            session
            and supplied
            and hmac.compare_digest(session[1], supplied)
            and self._same_origin(req)
        )

    def _queue_save(self) -> None:
        if not self._save_task or self._save_task.done():
            self._save_task = asyncio.create_task(self._save_debounced())

    async def _save_debounced(self) -> None:
        await asyncio.sleep(1.0)
        # Snapshot state before transferring the JSON write to a worker thread.
        snapshot = json.loads(json.dumps(self.stats, default=str))
        try:
            await asyncio.to_thread(_save_stats_sync, snapshot)
        except Exception:
            logger.exception("Dashboard stats save failed")

    async def _static_file(self, name: str, content_type: str) -> web.Response:
        contents = (STATIC_DIR / name).read_text(encoding="utf-8")
        return web.Response(
            text=contents,
            content_type=content_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    async def _handle_static_login_css(self, req: web.Request) -> web.Response:
        return await self._static_file("login.css", "text/css")

    async def _handle_static_dashboard_css(self, req: web.Request) -> web.Response:
        return await self._static_file("dashboard.css", "text/css")

    async def _handle_static_dashboard_js(self, req: web.Request) -> web.Response:
        return await self._static_file("dashboard.js", "application/javascript")

    # ── Page handlers ─────────────────────────────────────────────────────────

    async def _handle_dashboard(self, req: web.Request) -> web.Response:
        session = self._session(req)
        if not session:
            raise web.HTTPFound("/login")
        return web.Response(
            text=_DASHBOARD_HTML.replace("{{CSRF}}", session[1]),
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def _handle_login_page(self, req: web.Request) -> web.Response:
        if self._authed(req):
            raise web.HTTPFound("/")
        now = time.time()
        self._login_csrf = {k: v for k, v in self._login_csrf.items() if v > now}
        csrf = secrets.token_urlsafe(24)
        self._login_csrf[csrf] = now + 600
        # A fixed message is used; URL parameters never reach HTML directly.
        err_html = (
            '<p class="err" role="alert">Invalid password or too many attempts.</p>'
            if req.query.get("error")
            else ""
        )
        html_body = _LOGIN_HTML.replace("{{ERROR}}", err_html).replace(
            "{{LOGIN_CSRF}}", csrf
        )
        return web.Response(
            text=html_body,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    async def _handle_login(self, req: web.Request) -> web.Response:
        if not self._same_origin(req):
            raise web.HTTPForbidden(text="Invalid origin")
        now = time.time()
        remote = req.remote or "unknown"
        attempts = [
            t for t in self._login_failures.get(remote, []) if now - t < LOGIN_WINDOW
        ]
        if len(attempts) >= LOGIN_ATTEMPTS:
            self._login_failures[remote] = attempts
            raise web.HTTPTooManyRequests(
                text="Too many login attempts. Try again later."
            )
        data = await req.post()
        csrf = str(data.get("csrf", ""))
        expiry = self._login_csrf.pop(csrf, 0)
        if expiry < now:
            raise web.HTTPForbidden(text="Login form expired; reload the page")
        password = str(data.get("password", ""))
        if hmac.compare_digest(password.encode(), self.secret.encode()):
            self._login_failures.pop(remote, None)
            token, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self._sessions[token] = (now + SESSION_SECONDS, csrf_token)
            resp = web.HTTPFound("/")
            resp.set_cookie(
                "dashboard_token",
                token,
                httponly=True,
                samesite="Strict",
                secure=(
                    req.secure
                    or os.getenv("DASHBOARD_COOKIE_SECURE", "").lower() == "true"
                ),
                max_age=SESSION_SECONDS,
                path="/",
            )
            return resp
        attempts.append(now)
        self._login_failures[remote] = attempts
        raise web.HTTPFound("/login?error=1")

    async def _handle_logout(self, req: web.Request) -> web.Response:
        if not self._same_origin(req):
            raise web.HTTPForbidden()
        session = self._session(req)
        data = await req.post()
        if not session or not hmac.compare_digest(
            str(data.get("csrf", "")), session[1]
        ):
            raise web.HTTPForbidden()
        token = req.cookies.get("dashboard_token", "")
        self._sessions.pop(token, None)
        resp = web.HTTPFound("/login")
        resp.del_cookie("dashboard_token", path="/")
        return resp

    # ── API handlers ──────────────────────────────────────────────────────────

    async def _handle_api_stats(self, req: web.Request) -> web.Response:
        if not self._authed(req):
            return web.json_response({"error": "Unauthorized"}, status=401)

        return web.json_response(
            await self._stats_payload(), headers={"Cache-Control": "no-store"}
        )

    async def _stats_payload(self) -> dict:
        bot = self.bot
        uptime_delta = datetime.now(timezone.utc) - bot.start_time

        lavalink_connected = bot.is_lavalink_connected()
        lavalink_host = os.getenv("LAVALINK_HOST", "localhost")
        lavalink_port = os.getenv("LAVALINK_PORT", "2333")
        lavalink_last_ready = (
            bot.lavalink_last_ready_at.isoformat()
            if bot.lavalink_last_ready_at
            else None
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
                now_playing = getattr(player.current, "title", None) or "Unknown"
                now_playing_url = getattr(player.current, "uri", None)

            # Wavelink Player.paused reflects whether the current track is paused.
            is_paused = bool(now_playing and getattr(player, "paused", False))

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
                self._sync_pause(guild.id, is_paused)
                session_extra = int(self._track_elapsed.get(guild.id, 0) * 1000)
                if guild.id in self._track_start:
                    session_extra += int(
                        (time.monotonic() - self._track_start[guild.id]) * 1000
                    )
            else:
                session_extra = int(self._track_elapsed.get(guild.id, 0) * 1000)

            guilds_data.append(
                {
                    "id": str(guild.id),
                    "name": guild.name,
                    "icon_url": str(guild.icon.url) if guild.icon else None,
                    "member_count": guild.member_count or 0,
                    "voice_members": voice_members,
                    "voice_channel": voice_channel_name,
                    "now_playing": now_playing,
                    "now_playing_url": (
                        str(now_playing_url) if now_playing_url else None
                    ),
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
                    "is_playing": bool(now_playing) and not is_paused,
                    "is_paused": is_paused,
                }
            )

        return {
            "uptime": _fmt_uptime(uptime_delta),
            "uptime_seconds": int(uptime_delta.total_seconds()),
            "lavalink_connected": lavalink_connected,
            "lavalink_host": lavalink_host,
            "lavalink_port": lavalink_port,
            "lavalink_last_ready": lavalink_last_ready,
            "guild_count": len(guilds_data),
            "guilds": guilds_data,
        }

    @staticmethod
    def _stream_state(payload: dict) -> tuple[dict, dict]:
        """Strip locally ticking fields before comparing / broadcasting deltas."""
        meta = {
            k: v
            for k, v in payload.items()
            if k not in ("uptime", "uptime_seconds", "guilds")
        }
        guilds = {}
        for item in payload["guilds"]:
            stable = item.copy()
            if stable.get("is_playing"):
                # Playback time changes every sample even if nothing happened.
                stable.pop("total_playtime_ms", None)
                stable.pop("total_playtime_formatted", None)
            guilds[item["id"]] = stable
        return meta, guilds

    @staticmethod
    def _stream_delta(before: tuple[dict, dict], after: tuple[dict, dict]) -> dict:
        old_meta, old_guilds = before
        new_meta, new_guilds = after
        delta = {"meta": {}, "guilds": {}, "removed": []}
        delta["meta"] = {k: v for k, v in new_meta.items() if old_meta.get(k) != v}
        for gid, guild in new_guilds.items():
            previous = old_guilds.get(gid)
            if previous is None:
                delta["guilds"][gid] = guild
            else:
                changes = {k: v for k, v in guild.items() if previous.get(k) != v}
                if changes:
                    delta["guilds"][gid] = changes
        delta["removed"] = [gid for gid in old_guilds if gid not in new_guilds]
        return delta

    def notify_change(self) -> None:
        """Optional: call after a bot setting / Discord player state changes.

        Scheduled in the dashboard's event loop; the periodic comparison still
        catches changes when the hook is not used.
        """
        self._stream_wakeup.set()

    async def _broadcast_loop(self) -> None:
        previous = None
        while True:
            try:
                payload = await self._stats_payload()
                current = self._stream_state(payload)
                if previous is not None:
                    delta = self._stream_delta(previous, current)
                    if any(delta.values()):
                        serialized = json.dumps(delta, ensure_ascii=False)
                        for queue in tuple(self._subscribers):
                            if queue.full():
                                # Overflow => full resynchronization instead of
                                # silently losing a necessary intermediate delta.
                                while not queue.empty():
                                    queue.get_nowait()
                                queue.put_nowait(("resync", ""))
                            else:
                                queue.put_nowait(("delta", serialized))
                previous = current
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Dashboard SSE sampling failed")
            try:
                await asyncio.wait_for(
                    self._stream_wakeup.wait(), timeout=STREAM_INTERVAL
                )
            except asyncio.TimeoutError:
                pass
            self._stream_wakeup.clear()

    async def _handle_events(self, req: web.Request) -> web.StreamResponse:
        session = self._session(req)
        if not session:
            raise web.HTTPUnauthorized()
        if len(self._subscribers) >= 100:
            raise web.HTTPServiceUnavailable(text="Too many dashboard streams")
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(req)
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=8)
        self._subscribers.add(queue)
        try:
            # Every new connection gets a complete authoritative baseline.
            initial = json.dumps(await self._stats_payload(), ensure_ascii=False)
            await response.write(
                ("event: snapshot\ndata: " + initial + "\n\n").encode()
            )
            while True:
                if not self._authed(req):
                    await response.write(b"event: unauthorized\ndata: {}\n\n")
                    break
                try:
                    event_type, body = await asyncio.wait_for(queue.get(), timeout=20)
                    if event_type == "resync":
                        body = json.dumps(
                            await self._stats_payload(), ensure_ascii=False
                        )
                        event_type = "snapshot"
                    await response.write(
                        ("event: " + event_type + "\ndata: " + body + "\n\n").encode()
                    )
                except asyncio.TimeoutError:
                    await response.write(b": heartbeat\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._subscribers.discard(queue)
        return response

    async def _handle_leave(self, req: web.Request) -> web.Response:
        if not self._authed(req):
            return web.json_response({"error": "Unauthorized"}, status=401)

        if not self._csrf_ok(req):
            return web.json_response(
                {"error": "Invalid CSRF token or origin"}, status=403
            )
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

    def _sync_pause(self, guild_id: int, paused: bool) -> None:
        # Accumulate monotonic elapsed time only while playback is active.
        started = self._track_start.get(guild_id)
        if paused and started is not None:
            self._track_elapsed[guild_id] = self._track_elapsed.get(guild_id, 0) + max(
                0, time.monotonic() - started
            )
            self._track_start.pop(guild_id, None)
        elif not paused and started is None and guild_id in self._track_elapsed:
            self._track_start[guild_id] = time.monotonic()

    def record_track_start(self, guild_id: int, track_title: str) -> None:
        self.record_track_end(guild_id)
        self._track_start[guild_id] = time.monotonic()
        self._track_elapsed[guild_id] = 0.0
        g = self.stats.setdefault(str(guild_id), {})
        g["last_played_at"] = datetime.now(timezone.utc).isoformat()
        g["last_track"] = track_title
        g["total_tracks_played"] = g.get("total_tracks_played", 0) + 1
        self._queue_save()

    def record_track_end(self, guild_id: int) -> None:
        started = self._track_start.pop(guild_id, None)
        elapsed = self._track_elapsed.pop(guild_id, 0.0)
        if started is not None:
            elapsed += max(0, time.monotonic() - started)
        if started is None and elapsed == 0:
            return
        g = self.stats.setdefault(str(guild_id), {})
        g["total_playtime_ms"] = g.get("total_playtime_ms", 0) + int(elapsed * 1000)
        self._queue_save()

    def record_guild_join(self, guild_id: int) -> None:
        g = self.stats.setdefault(str(guild_id), {})
        if "joined_at" not in g:
            g["joined_at"] = datetime.now(timezone.utc).isoformat()
            self._queue_save()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        self._stream_task = asyncio.create_task(self._broadcast_loop())
        logger.info("🌐 Dashboard running → http://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass
        await asyncio.to_thread(
            _save_stats_sync, json.loads(json.dumps(self.stats, default=str))
        )
        if self._runner:
            await self._runner.cleanup()
            logger.info("Dashboard stopped.")
