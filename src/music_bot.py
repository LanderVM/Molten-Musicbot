import logging
import os
from datetime import datetime, timezone

import discord
import wavelink
from discord.ext import commands
from dotenv import load_dotenv

from cogs.buttons import ControlButton, PlayerControlView
from utils import format_duration, load_setup_channels, save_setup_channels

load_dotenv()


class Bot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        discord.utils.setup_logging(level=logging.INFO)
        super().__init__(
            command_prefix="!",
            intents=intents,
            partials=["MESSAGE", "REACTION", "USER"],
        )

        self.setup_channels = load_setup_channels()
        self.latest_action: dict | None = None
        self.delete_message_tags: set[int] = set()

    def set_latest_action(self, action: str, persist: bool = False):
        """
        Sets the latest user action for display in embeds.

        Parameters:
        - action (str): The action message (e.g., "Skipped by User").
        - persist (bool): Whether to persist the action message on the next embed update.
        """
        self.latest_action = {"text": action, "persist": persist}

    async def setup_hook(self):
        """
        Runs once when the bot starts. Connects to Wavelink node and loads extensions.
        """
        await wavelink.Pool.connect(
            nodes=[
                wavelink.Node(
                    uri=os.getenv("WAVELINK_NODE_URI"),
                    password=os.getenv("WAVELINK_NODE_PASSWORD"),
                )
            ],
            client=self,
            cache_capacity=100,
        )
        await self.load_extension("cogs.commands")
        await self.load_extension("cogs.events")
        await self.tree.sync()

    def create_now_playing_embed(
        self, track: wavelink.Playable, original: wavelink.Playable | None
    ) -> discord.Embed:
        embed = discord.Embed(
            title=track.title, url=track.uri, color=discord.Color.blue()
        )
        embed.set_author(
            name="Now Playing", icon_url=os.getenv("NOW_PLAYING_SPIN_GIF_URL")
        )
        requester = getattr(track, "requester", None) or getattr(
            original, "requester", None
        )
        embed.add_field(
            name="Requested by",
            value=requester.mention if requester else "Unknown",
            inline=True,
        )
        duration = format_duration(track.length) if not track.is_stream else "Live"
        embed.add_field(name="Duration", value=duration, inline=True)
        if track.artwork:
            embed.set_image(url=track.artwork)
        if self.latest_action:
            embed.set_footer(text=self.latest_action["text"])
            self.latest_action = None
        return embed

    def create_default_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Now Playing", description="No song currently playing"
        )
        embed.set_image(url=os.getenv("NO_SONG_PLAYING_IMAGE_URL"))
        if self.latest_action:
            embed.set_footer(text=self.latest_action["text"])
        return embed

    async def handle_setup_play(self, message: discord.Message) -> str:
        try:
            await message.delete()
        except discord.NotFound:
            return "Message not found; nothing to delete."

        player: wavelink.Player = message.guild.voice_client
        if not player:
            if not message.author.voice:
                return "You must be in a voice channel."
            try:
                player = await message.author.voice.channel.connect(cls=wavelink.Player)
            except Exception as e:
                logging.error(f"Voice connection failed: {e}")
                return "Voice connection failed."

        player.autoplay = wavelink.AutoPlayMode.partial
        player.home = message.channel

        try:
            tracks = await wavelink.Playable.search(message.content)
            if not tracks:
                return "No tracks found with your query."

            if isinstance(tracks, wavelink.Playlist):
                for track in tracks.tracks:
                    track.requester = message.author
                await player.queue.put_wait(tracks)
            else:
                track = tracks[0]
                track.requester = message.author
                await player.queue.put_wait(track)

            if not player.playing:
                await player.play(
                    player.queue.get(), volume=int(os.getenv("BOT_VOLUME"))
                )
            return "Playback started."
        except Exception as e:
            logging.error(f"Playback error: {e}")
            return "Playback error occurred."

    async def handle_play_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
        query: str,
    ) -> str:
        if not player:
            if not user.voice:
                return "Please join a voice channel first."
            try:
                player = await user.voice.channel.connect(cls=wavelink.Player)
            except Exception as e:
                logging.error(f"Voice connection failed: {e}")
                return "Failed to join your voice channel."

        player.autoplay = wavelink.AutoPlayMode.partial
        if not hasattr(player, "home"):
            player.home = interaction.channel
        elif player.home != interaction.channel:
            return f"You can only play songs in {player.home.mention}, as the player has already started there."

        try:
            tracks = await wavelink.Playable.search(query)
            if not tracks:
                return "Could not find any tracks with that query."

            if isinstance(tracks, wavelink.Playlist):
                for track in tracks.tracks:
                    track.requester = user
                await player.queue.put_wait(tracks)
                msg = f"Added playlist **`{tracks.name}`** to the queue."
            else:
                track = tracks[0]
                track.requester = user
                await player.queue.put_wait(track)
                msg = f"Added **`{track}`** to the queue."

            if not player.playing:
                await player.play(
                    player.queue.get(), volume=int(os.getenv("BOT_VOLUME"))
                )
            return msg
        except Exception as e:
            logging.error(f"Playback error: {e}")
            return "Playback error occurred."

    async def handle_skip_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
    ) -> str:
        if not player:
            return "No active player."
        try:
            await player.skip(force=True)
            self.set_latest_action(f"Skipped by {user.display_name}", persist=True)
            return "Skipped the current track."
        except Exception as e:
            logging.error(f"Skip error: {e}")
            return "Failed to skip the track."

    async def handle_toggle_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
    ) -> str:
        if not player:
            return "No active player."

        new_pause_state = not player.paused
        try:
            await player.pause(new_pause_state)
        except Exception as e:
            logging.error(f"Toggle error: {e}")
            return "Failed to toggle pause/resume."

        action = "Paused" if new_pause_state else "Resumed"
        self.set_latest_action(f"{action} by {user.display_name}")
        await self.update_setup_embed(guild, player)
        return f"{action} the current track."

    async def handle_disconnect_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
    ) -> str:
        if not player:
            return "No active player."
        try:
            await player.disconnect()
        except Exception as e:
            logging.error(f"Disconnect error: {e}")
            return "Failed to disconnect the player."

        self.set_latest_action(f"Disconnected by {user.display_name}")
        setup_data = self.setup_channels.get(guild.id)
        if setup_data:
            try:
                channel = guild.get_channel(setup_data.get("channel"))
                message = await channel.fetch_message(setup_data.get("message"))
                embed = self.create_default_embed()
                await message.edit(
                    embed=embed,
                    view=PlayerControlView(
                        self,
                        player,
                        disabled_buttons=[
                            ControlButton.LEAVE,
                            ControlButton.PAUSE_RESUME,
                            ControlButton.SKIP,
                            ControlButton.SHUFFLE,
                        ],
                    ),
                )
            except Exception as e:
                logging.error(f"Error updating embed on disconnect: {e}")
                return "Disconnected, but failed to update embed."
        return "Disconnected the player."

    async def handle_shuffle_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
    ) -> str:
        if not player or player.queue.is_empty:
            return "No active player or the queue is empty."
        try:
            player.queue.shuffle()
            self.set_latest_action(f"Shuffled by {user.display_name}")
            await self.update_setup_embed(guild, player)
            return "The queue has been shuffled!"
        except Exception as e:
            logging.error(f"Shuffle error: {e}")
            return "Failed to shuffle the queue."

    async def handle_nightcore_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
        mode: int,
    ) -> str:
        if not player:
            if not user.voice:
                return "Please join a voice channel first."
            try:
                player = await user.voice.channel.connect(cls=wavelink.Player)
            except Exception as e:
                logging.error(f"Nightcore connection failed: {e}")
                return "Failed to join your voice channel."

        filters = player.filters
        try:
            if mode == 0:
                filters.timescale.reset()
                self.set_latest_action(f"Nightcore OFF by {user.display_name}")
                msg = "Nightcore effect disabled."
            else:
                filters.timescale.set(pitch=1.2, speed=1.1, rate=1.0)
                self.set_latest_action(f"Nightcore ON by {user.display_name}")
                msg = "Nightcore effect enabled!"

            await player.set_filters(filters)
            await self.update_setup_embed(guild, player)
            return msg
        except Exception as e:
            logging.error(f"Filter update error: {e}")
            return "Failed to update filters."

    async def update_setup_embed(
        self,
        guild: discord.Guild,
        player: wavelink.Player | None,
        view: discord.ui.View = None,
        embed: discord.Embed = None,
    ):
        """
        Updates the embed and view in the setup channel.

        This method gets the channel and message based on stored setup data,
        fetches or creates an embed, updates (or replaces) the message, and
        then saves the new message ID.
        """
        setup_data = self.setup_channels.get(guild.id)
        if not setup_data:
            return

        channel_id = setup_data.get("channel")
        message_id = setup_data.get("message")
        channel = guild.get_channel(channel_id)
        if channel is None:
            logging.error("Channel %s not found for guild %s", channel_id, guild.id)
            return

        embed = await self._fetch_or_create_embed(channel, message_id, embed)
        view = view or PlayerControlView(self, player)

        new_message_id, edited, original_message = (
            await self._update_or_replace_message(channel, message_id, embed, view)
        )

        self.setup_channels[guild.id]["message"] = new_message_id
        save_setup_channels(self.setup_channels)

        if (
            edited
            and original_message
            and (
                (
                    datetime.now(timezone.utc) - original_message.created_at
                ).total_seconds()
                > 3600
            )
        ):
            self.delete_message_tags.add(new_message_id)

    async def _fetch_or_create_embed(
        self, channel: discord.TextChannel, message_id: int, embed: discord.Embed = None
    ) -> discord.Embed:
        """
        Attempts to fetch an existing message and retrieve its embed.
        If not available, returns a default embed.
        """
        try:
            message = await channel.fetch_message(message_id)
            if embed is None:
                embed = (
                    message.embeds[0] if message.embeds else self.create_default_embed()
                )
            if self.latest_action:
                embed.set_footer(text=self.latest_action["text"])
            return embed
        except Exception as e:
            logging.error("Error fetching embed: %s", e)
            return self.create_default_embed()

    async def _update_or_replace_message(
        self,
        channel: discord.TextChannel,
        message_id: int,
        embed: discord.Embed,
        view: discord.ui.View,
    ) -> tuple[int, bool, discord.Message | None]:
        """
        Updates the message if possible; if it’s flagged for deletion or not found,
        sends a new message instead.

        Returns:
            new_message_id, a boolean indicating if the original message was edited,
            and the original message (or new message) object.
        """
        try:
            message = await channel.fetch_message(message_id)
            # If flagged for deletion, delete it and send a new one.
            if message_id in self.delete_message_tags:
                await message.delete()
                self.delete_message_tags.discard(message_id)
                new_message = await channel.send(embed=embed, view=view)
                return new_message.id, False, new_message
            else:
                await message.edit(embed=embed, view=view)
                return message_id, True, message
        except discord.NotFound:
            new_message = await channel.send(embed=embed, view=view)
            return new_message.id, False, new_message
        except Exception as e:
            logging.error("Error updating setup message: %s", e)
            return message_id, False, None
