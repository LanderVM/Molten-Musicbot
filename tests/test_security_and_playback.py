# ruff: noqa: E402
import asyncio
import socket
import sys
from pathlib import Path
import json
import re
import time
import threading
from collections import defaultdict
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from lavalink.events import TrackStuckEvent
from lavalink.player import DefaultPlayer

# Make the existing flat src layout importable without a packaging config.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import utils
from cogs.buttons import PlayerControlView
from cogs.commands import MusicCommands
from cogs.events import EventHandlers
from dashboard.server import MAX_AUTH_ENTRIES, Dashboard
from decorators import debounce_action
from music_bot import Bot
from utils import Error, direct_url_error


def make_dashboard():
    player = NS(current=NS(title="Song", uri=None), paused=False, queue=[])
    guild = NS(id=7, name="Guild", voice_client=None, icon=None, member_count=1)
    bot = NS(
        start_time=datetime.now(timezone.utc),
        guilds=[guild],
        is_lavalink_connected=lambda: True,
        lavalink_last_ready_at=None,
        get_player=lambda _: player,
        setup_channels={},
    )
    with patch("dashboard.server._load_stats", return_value={}):
        dashboard = Dashboard(bot, "test-password")
    dashboard._queue_save = Mock()
    return dashboard, player


def test_failed_save_preserves_previous_config(tmp_path, monkeypatch):
    target = tmp_path / "setup.json"
    original = '{"7":{"dj_role":99}}'
    target.write_text(original)
    monkeypatch.setattr(utils, "SETUP_CHANNELS_FILE", str(target))
    with patch.object(utils.json, "dump", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            utils.save_setup_channels_sync({7: {"dj_role": 100}})
    assert target.read_text() == original
    assert list(tmp_path.iterdir()) == [target]


def test_invalid_setup_fails_closed(tmp_path, monkeypatch):
    target = tmp_path / "setup.json"
    target.write_text("invalid json")
    monkeypatch.setattr(utils, "SETUP_CHANNELS_FILE", str(target))
    with pytest.raises(RuntimeError, match="repair or restore"):
        utils.load_setup_channels()
    assert target.read_text() == "invalid json"


def test_async_save_snapshots_before_worker_mutates_data(tmp_path, monkeypatch):
    target = tmp_path / "setup.json"
    monkeypatch.setattr(utils, "SETUP_CHANNELS_FILE", str(target))
    data = {7: {"dj_role": 99}}
    writer = utils.save_setup_channels_sync

    def mutate_then_write(snapshot):
        data[7]["dj_role"] = 100
        writer(snapshot)

    with patch.object(utils, "save_setup_channels_sync", side_effect=mutate_then_write):
        asyncio.run(utils.save_setup_channels_async(data))
    assert json.loads(target.read_text())["7"]["dj_role"] == 99


def test_cancelled_save_finishes_before_next_write(tmp_path, monkeypatch):
    target = tmp_path / "setup.json"
    monkeypatch.setattr(utils, "SETUP_CHANNELS_FILE", str(target))
    started, release = threading.Event(), threading.Event()
    writer = utils.save_setup_channels_sync

    def slow_first(data):
        if data["7"]["dj_role"] == 99:
            started.set()
            assert release.wait(timeout=5)
        writer(data)

    async def run():
        monkeypatch.setattr(utils, "_save_lock", asyncio.Lock())
        first = asyncio.create_task(
            utils.save_setup_channels_async({7: {"dj_role": 99}})
        )
        assert await asyncio.to_thread(started.wait, 5)
        first.cancel()
        second = asyncio.create_task(
            utils.save_setup_channels_async({7: {"dj_role": 100}})
        )
        try:
            await asyncio.sleep(0.01)
            assert not second.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second

    with patch.object(utils, "save_setup_channels_sync", side_effect=slow_first):
        asyncio.run(run())
    assert json.loads(target.read_text())["7"]["dj_role"] == 100


@pytest.mark.parametrize(
    "action",
    [
        "play",
        "stop",
        "skip",
        "toggle",
        "shuffle",
        "disconnect",
        "nightcore",
        "stay_247",
    ],
)
def test_shared_actions_deny_non_dj(action):
    async def run():
        guild = NS(id=7)
        user = NS(id=1, roles=[])
        bot = NS(
            setup_channels={7: {"dj_role": 99}},
            _action_locks=defaultdict(asyncio.Lock),
            _action_cooldowns={},
            voice_precheck=AsyncMock(return_value=None),
        )
        args = (
            (1,) if action == "nightcore" else (("song",) if action == "play" else ())
        )
        result = await getattr(Bot, f"handle_{action}_action")(
            bot, None, guild, user, None, *args
        )
        assert isinstance(result, Error)
        assert "DJ role" in str(result)
        bot.voice_precheck.assert_not_awaited()

    asyncio.run(run())


def test_missing_role_cache_does_not_remove_authorization():
    interaction = NS(
        guild=NS(id=7, get_role=lambda _: None),
        user=NS(roles=[]),
        client=NS(setup_channels={7: {"dj_role": 99}}),
    )
    with pytest.raises(discord.app_commands.MissingPermissions):
        MusicCommands.dj_role_required(interaction)


def test_buttons_acknowledge_before_running_action():
    async def run():
        acknowledged = []
        interaction = NS(
            response=NS(defer=AsyncMock(side_effect=lambda: acknowledged.append(True))),
            followup=NS(send=AsyncMock()),
        )

        async def action():
            assert acknowledged
            return Error("denied")

        await PlayerControlView(NS(), None)._handle_control_action(interaction, action)
        interaction.followup.send.assert_awaited_once_with("denied", ephemeral=True)

    asyncio.run(run())


def test_slow_action_is_locked_after_cooldown_and_released_on_error():
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        bot = NS(_action_locks=defaultdict(asyncio.Lock), _action_cooldowns={})

        @debounce_action(delay=0.001)
        async def action(self, interaction, guild, user):
            started.set()
            await release.wait()
            raise ValueError("failure")

        guild = NS(id=7)
        first = asyncio.create_task(action(bot, None, guild, None))
        await started.wait()
        await asyncio.sleep(0.01)
        assert isinstance(await action(bot, None, guild, None), Error)
        release.set()
        with pytest.raises(ValueError):
            await first
        assert not bot._action_locks[7].locked()

    asyncio.run(run())


@pytest.mark.parametrize("missing", [False, True])
def test_message_fetch_failure_preserves_policy_and_restores_callbacks(missing):
    async def run():
        response = NS(status=404 if missing else 503, reason="error")
        exception = (discord.NotFound if missing else discord.HTTPException)(
            response, "failure"
        )
        channel = NS(
            fetch_message=AsyncMock(side_effect=exception),
            send=AsyncMock(return_value=NS(id=3)),
        )
        data = {7: {"channel": 1, "message": 2, "dj_role": 99}}
        bot = NS(
            setup_channels=data,
            get_guild=lambda _: NS(
                get_channel=lambda _: channel, get_role=lambda _: None
            ),
            setup_message_cache={},
            dj_roles={},
            get_player=lambda _: None,
            add_view=Mock(),
            create_default_embed=Mock(),
        )
        with patch("music_bot.save_setup_channels_async", new_callable=AsyncMock):
            await Bot.load_setup_message_cache(bot)
        assert data[7]["dj_role"] == 99
        assert data[7]["message"] == (3 if missing else 2)
        assert bot.add_view.call_args.kwargs["message_id"] == 2
        if not missing:
            channel.send.assert_not_awaited()

    asyncio.run(run())


def test_stuck_event_advances_only_once():
    async def run():
        player = NS(guild_id=7, current=None, play=AsyncMock())
        player.skip = lambda: DefaultPlayer.skip(player)
        event = TrackStuckEvent(player, None, 10000)
        handlers = EventHandlers(NS(lavalink=None, set_latest_action=Mock()))
        await DefaultPlayer.handle_event(player, event)
        await handlers.on_lavalink_track_stuck(event)
        player.play.assert_awaited_once()

    asyncio.run(run())


def test_pause_resume_and_idle_accounting():
    async def run():
        dashboard, player = make_dashboard()
        now = [100.0]
        clock = NS(monotonic=lambda: now[0], time=time.time)
        with patch("dashboard.server.time", clock):
            dashboard.record_track_start(7, "Song")
            now[0] = 110
            player.paused = True
            await dashboard._stats_payload()
            now[0] = 120
            player.paused = False
            await dashboard._stats_payload()
            now[0] = 130
            assert (await dashboard._stats_payload())["guilds"][0][
                "total_playtime_ms"
            ] == 20000
            player.current = None
            await dashboard._stats_payload()
            now[0] = 150
            assert (await dashboard._stats_payload())["guilds"][0][
                "total_playtime_ms"
            ] == 20000

    asyncio.run(run())


def test_shutdown_finalizes_playtime():
    async def run():
        dashboard, _ = make_dashboard()
        now = [100.0]
        with patch(
            "dashboard.server.time", NS(monotonic=lambda: now[0], time=time.time)
        ), patch("dashboard.server._save_stats_sync") as save:
            dashboard.record_track_start(7, "Song")
            now[0] = 110
            await dashboard.stop()
        assert save.call_args.args[0]["7"]["total_playtime_ms"] == 10000

    asyncio.run(run())


def test_resumed_node_session_restarts_clock_without_counting_new_track():
    async def run():
        dashboard, _ = make_dashboard()
        now = [100.0]
        with patch(
            "dashboard.server.time", NS(monotonic=lambda: now[0], time=time.time)
        ):
            dashboard.record_track_start(7, "Song")
            now[0] = 110
            dashboard.record_track_end(7)
            now[0] = 120
            dashboard.record_track_resume(7, False)
            now[0] = 130
            payload = await dashboard._stats_payload()
        assert payload["guilds"][0]["total_tracks_played"] == 1
        assert payload["guilds"][0]["total_playtime_ms"] == 20000

    asyncio.run(run())


def test_stat_change_during_write_is_saved_again():
    async def run():
        dashboard, _ = make_dashboard()
        dashboard._queue_save = Dashboard._queue_save.__get__(dashboard)
        snapshots = []
        dashboard.stats = {"revision": 1}
        original_sleep = asyncio.sleep

        async def fast_sleep(_):
            await original_sleep(0)

        async def fake_to_thread(writer, snapshot):
            snapshots.append(snapshot)
            if len(snapshots) == 1:
                dashboard.stats["revision"] = 2
                dashboard._queue_save()

        with patch("dashboard.server.asyncio.sleep", fast_sleep), patch(
            "dashboard.server.asyncio.to_thread", fake_to_thread
        ):
            dashboard._queue_save()
            await dashboard._save_task
        assert snapshots == [{"revision": 1}, {"revision": 2}]

    asyncio.run(run())


def test_readiness_uses_live_node_state():
    node = NS(available=False)
    bot = NS(lavalink=NS(node_manager=NS(nodes=[node])), lavalink_ready=True)
    assert not Bot.is_lavalink_connected(bot)
    node.available = True
    assert Bot.is_lavalink_connected(bot)


def test_valid_dj_stop_clears_queue_and_finalizes_statistics():
    async def run():
        user = NS(id=1, roles=[NS(id=99)], display_name="DJ")
        guild = NS(id=7)
        player = NS(queue=["song"], paused=False, stop=AsyncMock())
        dashboard = NS(record_track_end=Mock())
        bot = NS(
            setup_channels={7: {"dj_role": 99}},
            _action_locks=defaultdict(asyncio.Lock),
            _action_cooldowns={},
            voice_precheck=AsyncMock(return_value=None),
            dashboard=dashboard,
            set_latest_action=Mock(),
            update_setup_embed=AsyncMock(),
            create_default_embed=Mock(),
        )
        result = await Bot.handle_stop_action(bot, None, guild, user, player)
        assert not isinstance(result, Error)
        player.stop.assert_awaited_once()
        assert not player.queue
        dashboard.record_track_end.assert_called_once_with(7)

    asyncio.run(run())


def test_structured_load_error_is_not_reported_as_empty_results():
    async def run():
        from lavalink import LoadType

        bot = NS(
            setup_channels={},
            _action_locks=defaultdict(asyncio.Lock),
            _action_cooldowns={},
            voice_precheck=AsyncMock(return_value=None),
            is_lavalink_connected=lambda: True,
            get_player=lambda _: NS(),
            lavalink=NS(
                get_tracks=AsyncMock(
                    return_value=NS(
                        load_type=LoadType.ERROR,
                        error=NS(message="blocked", cause="host policy"),
                        tracks=[],
                    )
                )
            ),
        )
        result = await Bot.handle_play_action(
            bot, None, NS(id=7, voice_client=NS()), NS(id=1, roles=[]), None, "song"
        )
        assert isinstance(result, Error)
        assert "Could not load" in str(result)

    asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    [
        "http://icecast.vrtcdn.be/radio1-high.mp3",
        "https://another-station.example/live",
        "http://another-station.example:8000/stream",
    ],
)
def test_radio_urls_pass_through_unchanged(url):
    async def run():
        from lavalink import LoadType

        track = NS(title="Radio", uri=url)
        player = NS(queue=[], add=Mock(), is_playing=True, paused=False)
        bot = NS(
            setup_channels={},
            _action_locks=defaultdict(asyncio.Lock),
            _action_cooldowns={},
            voice_precheck=AsyncMock(return_value=None),
            is_lavalink_connected=lambda: True,
            get_player=lambda _: player,
            update_setup_buttons=AsyncMock(),
            lavalink=NS(
                get_tracks=AsyncMock(
                    return_value=NS(load_type=LoadType.TRACK, tracks=[track])
                )
            ),
        )
        with patch(
            "utils.socket.getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 8000)),
            ],
        ):
            result = await Bot.handle_play_action(
                bot, None, NS(id=7, voice_client=NS()), NS(id=1, roles=[]), player, url
            )
        assert not isinstance(result, Error)
        bot.lavalink.get_tracks.assert_awaited_once_with(url)
        player.add.assert_called_once_with(track, requester=1)
        await asyncio.sleep(0)

    asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:2333/",
        "http://127.1/",
        "http://2130706433/",
        "http://0x7f000001/",
        "http://0177.0.0.1/",
        "http://0.0.0.0/",
        "http://10.0.0.1/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/",
        "http://100.64.0.1/",
        "http://224.0.0.1/",
        "http://[::1]/",
        "http://[::]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://[ff02::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:10.0.0.1]/",
        "http://[64:ff9b::7f00:1]/",
        "http://[2002:7f00:1::]/",
        "http://localhost:8080/",
        "http://LOCALHOST./",
        "http://sub.localhost/",
        "http://printer.local/",
        "http://host.docker.internal/",
        "http://gateway.docker.internal/",
        "http://public.example@localhost/",
        "http://127。0。0。1/",
    ],
)
def test_direct_url_blacklist_rejects_local_addresses_without_dns(url):
    with patch(
        "utils.socket.getaddrinfo", side_effect=AssertionError("No DNS lookup expected")
    ):
        error = asyncio.run(direct_url_error(url))
    assert error
    assert "blocked" in error


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["172.18.0.2"],
        ["::1"],
        ["10.0.0.1"],
        ["8.8.8.8", "127.0.0.1"],
        ["8.8.8.8", "fc00::1"],
    ],
)
def test_dns_names_with_any_blacklisted_address_are_rejected(addresses):
    records = [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (address, 8000),
        )
        for address in addresses
    ]
    with patch("utils.socket.getaddrinfo", return_value=records):
        assert "blocked" in asyncio.run(
            direct_url_error("http://radio.example:8000/live")
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8:8000/stream",
        "https://[2606:4700:4700::1111]:8443/stream",
        "http://[::ffff:8.8.8.8]:8000/stream",
    ],
)
def test_public_addresses_and_custom_ports_are_allowed(url):
    assert asyncio.run(direct_url_error(url)) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://[::1",
        "http://radio.example:99999/",
        "http://radio.example:0/",
        "http://%31%32%37.0.0.1/",
        "http://radio.example\\@127.0.0.1/",
        "http://radio.example\n/",
        "file:///etc/passwd",
    ],
)
def test_ambiguous_or_invalid_urls_are_rejected(url):
    assert asyncio.run(direct_url_error(url))


def test_unresolvable_hostname_is_not_forwarded():
    with patch("utils.socket.getaddrinfo", side_effect=socket.gaierror("unresolved")):
        assert "Could not verify" in asyncio.run(
            direct_url_error("http://unknown.example/live")
        )


def test_blacklisted_url_never_joins_voice_or_calls_lavalink():
    async def run():
        bot = NS(
            setup_channels={},
            _action_locks=defaultdict(asyncio.Lock),
            _action_cooldowns={},
            voice_precheck=AsyncMock(return_value=None),
            lavalink=NS(get_tracks=AsyncMock()),
        )
        user = NS(id=1, roles=[], voice=NS(channel=NS(connect=AsyncMock())))
        result = await Bot.handle_play_action(
            bot,
            None,
            NS(id=7, voice_client=None),
            user,
            None,
            "http://127.0.0.1:2333/v4/info",
        )
        assert isinstance(result, Error)
        user.voice.channel.connect.assert_not_awaited()
        bot.lavalink.get_tracks.assert_not_awaited()

    asyncio.run(run())


def test_dashboard_auth_csrf_and_form_limits(monkeypatch):
    monkeypatch.delenv("DASHBOARD_COOKIE_SECURE", raising=False)

    async def run():
        dashboard, _ = make_dashboard()
        async with TestClient(TestServer(dashboard.app)) as client:
            origin = str(client.make_url("/")).rstrip("/")
            response = await client.get("/api/stats")
            assert response.status == 401
            response = await client.get("/login")
            token = re.search(
                'name="csrf" value="([^"]+)"', await response.text()
            ).group(1)
            response = await client.post(
                "/login",
                data={"csrf": token, "password": "test-password"},
                headers={"Origin": "https://attacker.example"},
            )
            assert response.status == 403
            response = await client.post(
                "/login",
                data={"csrf": token, "password": "test-password"},
                headers={"Origin": origin},
                allow_redirects=False,
            )
            assert response.status == 302
            assert response.cookies["dashboard_token"]["httponly"]
            response = await client.get("/api/stats")
            assert response.status == 200
            response = await client.post("/api/leave/7", headers={"Origin": origin})
            assert response.status == 403
            response = await client.post(
                "/logout", data={"csrf": "x" * 20000}, headers={"Origin": origin}
            )
            assert response.status == 413

    asyncio.run(run())


def test_auth_maps_prune_and_limit_forms():
    async def run():
        dashboard, _ = make_dashboard()
        dashboard._sessions["expired"] = (0, "csrf")
        dashboard._login_failures["old"] = [0]
        dashboard._login_csrf["expired"] = 0
        dashboard._prune_auth(time.time())
        assert (
            not dashboard._sessions
            and not dashboard._login_failures
            and not dashboard._login_csrf
        )
        dashboard._login_csrf = {
            str(i): time.time() + 100 for i in range(MAX_AUTH_ENTRIES)
        }
        with pytest.raises(web.HTTPServiceUnavailable):
            await dashboard._handle_login_page(NS(cookies={}))

    asyncio.run(run())
