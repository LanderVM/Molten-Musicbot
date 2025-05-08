from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
import wavelink
from discord.ext import commands

from cogs.buttons import ControlButton, PlayerControlView

if TYPE_CHECKING:
    from music_bot import Bot


class EventHandlers(commands.Cog):
    """
    A cog to handle various Discord and wavelink events.
    This includes handling bot readiness, track events, and message interactions.
    """

    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    @commands.Cog.listener()
    async def on_connect(self):
        """
        Called when the bot is connected to Discord.
        Sets up the bot's presence and loads the setup message cache.
        """
        logging.info("Connecting to Discord...")
        await self.bot.wait_until_ready()
        logging.info("Connected to Discord.")
    

    @commands.Cog.listener()
    async def on_ready(self):
        """
        Called when the bot has connected to Discord.
        Sets the bot's presence and logs the successful login.
        """
        logging.info("Logged in: %s | %s", self.bot.user, self.bot.user.id)
        activity = discord.Activity(
            type=discord.ActivityType.listening, name="your requests ♫"
        )
        await self.bot.load_setup_message_cache()
        await self.bot.change_presence(status=discord.Status.online, activity=activity)
        logging.info("Bot is online & can be used ♫")

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        """
        Called when a wavelink node connects.

        :param payload: The event payload containing node information.
        """
        logging.info(
            "Wavelink Node connected: %r | Resumed: %s", payload.node, payload.resumed
        )

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        """
        Called when a track starts playing.
        Updates the setup message with the now playing embed and control view.

        :param payload: The event payload containing track and player information.
        """
        player = payload.player
        track = payload.track

        # Clear temporary latest action if not persistent
        if self.bot.latest_action and not self.bot.latest_action.get("persist", False):
            self.bot.latest_action = None

        embed = self.bot.create_now_playing_embed(track, payload.original)
        await self.bot.update_setup_embed(
            guild=player.guild, player=player, embed=embed
        )

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        """
        Called when a track ends.
        Updates the setup message to reflect that playback has ended.

        :param payload: The event payload containing track end and player information.
        """
        player = payload.player
        if not player:
            return

        if not hasattr(player, "queue") or player.queue.is_empty:
            setup_data = self.bot.setup_channels.get(player.guild.id, {})
            if setup_data:
                try:
                    await self.bot.update_setup_embed(
                        player.guild,
                        player,
                        embed=self.bot.create_default_embed(),
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
                    logging.error("Error updating embed on track end: %s", e)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """
        Called when an interaction is received.
        Defers the response for component interactions if not already done.

        :param interaction: The interaction instance from Discord.
        """
        if interaction.type == discord.InteractionType.component:
            if not interaction.response.is_done():
                await interaction.response.defer()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Called when a message is sent in a guild.
        Processes messages in designated setup channels.

        :param message: The message instance from Discord.
        """
        if message.author.bot or not message.guild:
            return

        setup_data = self.bot.setup_channels.get(message.guild.id, {})
        if message.channel.id != setup_data.get("channel"):
            return

        if err := await self.bot.handle_setup_play(message):
            await message.channel.send(err, delete_after=5)


async def setup(bot: commands.Bot):
    """
    The setup function for adding the EventHandlers cog to the bot.

    :param bot: The bot instance.
    """
    await bot.add_cog(EventHandlers(bot))
