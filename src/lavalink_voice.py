from __future__ import annotations

import discord

import lavalink
from lavalink.errors import ClientError


class LavalinkVoiceClient(discord.VoiceProtocol):
    """Voice protocol bridge between discord.py and Lavalink.py."""

    def __init__(self, client: discord.Client, channel: discord.abc.Connectable):
        self.client = client
        self.channel = channel
        self.guild_id = channel.guild.id
        self._destroyed = False

        self.lavalink: lavalink.Client = self.client.lavalink

    async def on_voice_state_update(self, data):
        channel_id = data.get("channel_id")

        if not channel_id:
            await self._destroy()
            return

        channel = self.client.get_channel(int(channel_id))

        if channel is None:
            guild = self.client.get_guild(self.guild_id)
            if guild is None:
                await self._destroy()
                return
            try:
                channel = await guild.fetch_channel(int(channel_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                await self._destroy()
                return

        self.channel = channel

    async def connect(
        self,
        *,
        timeout: float,
        reconnect: bool,
        self_deaf: bool = False,
        self_mute: bool = False,
    ) -> None:
        self.lavalink.player_manager.create(guild_id=self.channel.guild.id)
        await self.channel.guild.change_voice_state(
            channel=self.channel, self_mute=self_mute, self_deaf=self_deaf
        )

    async def disconnect(self, *, force: bool = False) -> None:
        player = self.lavalink.player_manager.get(self.channel.guild.id)

        if player and not force and not player.is_connected:
            return

        await self.channel.guild.change_voice_state(channel=None)

        if player:
            player.channel_id = None

        await self._destroy()

    async def _destroy(self):
        self.cleanup()

        if self._destroyed:
            return

        self._destroyed = True

        try:
            await self.lavalink.player_manager.destroy(self.guild_id)
        except ClientError:
            pass
