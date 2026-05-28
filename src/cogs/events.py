from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

import lavalink
from cogs.buttons import ControlButton, PlayerControlView
from lavalink.events import (
    NodeReadyEvent,
    PlayerErrorEvent,
    QueueEndEvent,
    TrackStartEvent,
    TrackStuckEvent,
)
from enums import SetupChannelKeys
from utils import Error, save_setup_channels_async


if TYPE_CHECKING:
    from music_bot import Bot


class EventHandlers(commands.Cog):
    """
    A cog to handle Discord and Lavalink events.
    """

    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        if self.bot.lavalink:
            self.bot.lavalink.add_event_hooks(self)

    @commands.Cog.listener()
    async def on_connect(self):
        logging.info("Connecting to Discord...")
        await self.bot.wait_until_ready()
        logging.info("Connected to Discord.")

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info("Logged in: %s | %s", self.bot.user, self.bot.user.id)
        activity = discord.Game(name="Playing your requests ♫")
        await self.bot.load_setup_message_cache()
        await self.bot.change_presence(status=discord.Status.online, activity=activity)
        logging.info("Bot is online & can be used ♫")

    @lavalink.listener(NodeReadyEvent)
    async def on_lavalink_node_ready(self, event: NodeReadyEvent):
        self.bot.lavalink_ready = True
        self.bot.lavalink_last_ready_at = datetime.now(timezone.utc)
        logging.info(
            "Lavalink node ready: %s | Session: %s | Resumed: %s",
            event.node,
            event.session_id,
            event.resumed,
        )

    @lavalink.listener(TrackStartEvent)
    async def on_lavalink_track_start(self, event: TrackStartEvent):
        player = event.player
        guild = self.bot.get_guild(player.guild_id)
        if not guild:
            return

        self.bot.clear_latest_action(guild.id, only_non_persistent=True)

        embed = self.bot.create_now_playing_embed(event.track, guild)
        await self.bot.update_setup_embed(guild=guild, player=player, embed=embed)

    @lavalink.listener(QueueEndEvent)
    async def on_lavalink_queue_end(self, event: QueueEndEvent):
        player = event.player
        guild = self.bot.get_guild(player.guild_id)
        if not guild:
            return

        setup_data = self.bot.setup_channels.get(guild.id, {})
        if not setup_data:
            return

        try:
            await self.bot.update_setup_embed(
                guild,
                player,
                embed=self.bot.create_default_embed(guild),
                view=PlayerControlView(
                    self.bot,
                    player,
                    disabled_buttons=[
                        ControlButton.STOP,
                        ControlButton.PAUSE_RESUME,
                        ControlButton.SKIP,
                        ControlButton.SHUFFLE,
                    ],
                ),
            )
        except Exception as e:
            logging.error("Error updating embed on queue end: %s", e)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        setup_data = self.bot.setup_channels.get(message.guild.id, {})
        if message.channel.id != setup_data.get(SetupChannelKeys.CHANNEL):
            return

        msg = await self.bot.handle_setup_play(message)
        if isinstance(msg, Error):
            await message.channel.send(msg, delete_after=5)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        await self.bot.check_voice_channel_empty_and_leave(member)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        """Clean up stale DJ role cache when role is deleted."""
        guild_id = role.guild.id
        setup_data = self.bot.setup_channels.get(guild_id, {})
        dj_role_id = setup_data.get(SetupChannelKeys.DJ_ROLE)
        
        if role.id == dj_role_id:
            del setup_data[SetupChannelKeys.DJ_ROLE]
            self.bot.setup_channels[guild_id] = setup_data
            self.bot.dj_roles.pop(guild_id, None)
            
            asyncio.create_task(save_setup_channels_async(self.bot.setup_channels))
            logging.info("DJ role deleted for guild %s, cache cleaned.", guild_id)

    @lavalink.listener(PlayerErrorEvent)
    async def on_lavalink_player_error(self, event: PlayerErrorEvent):
        logging.warning(
            "Track exception on guild %s: %r",
            event.player.guild_id,
            event,
        )
        self.bot.set_latest_action(
            event.player.guild_id,
            "Skipped — track failed to load",
            persist=True,
        )
        await event.player.skip()

    @lavalink.listener(TrackStuckEvent)
    async def on_lavalink_track_stuck(self, event: TrackStuckEvent):
        logging.warning(
            "Track stuck on guild %s at position %sms",
            event.player.guild_id,
            event.threshold,
        )
        self.bot.set_latest_action(
            event.player.guild_id,
            "Skipped — track got stuck",
            persist=True,
        )
        await event.player.skip()


async def setup(bot: commands.Bot):
    await bot.add_cog(EventHandlers(bot))
