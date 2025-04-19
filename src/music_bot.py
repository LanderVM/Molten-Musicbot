import asyncio
import logging
import os
from datetime import datetime, timezone

import discord
import wavelink
from discord.ext import commands
from dotenv import load_dotenv

from cogs.buttons import ControlButton, PlayerControlView
from enums import EnvironmentKeys, LatestActionKeys, SetupChannelKeys
from utils import (
    format_duration,
    load_setup_channels,
    remove_setup_channel,
    save_setup_channels,
)

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
        self.setup_message_cache: dict[int, discord.Message] = {}
        self.dj_roles: dict[int, discord.Role] = {}

    def set_latest_action(self, action: str, persist: bool = False):
        """
        Sets the latest user action for display in embeds.

        Parameters:
            action (str): The action message (e.g., "Skipped by User").
            persist (bool): Whether to persist the action message on the next embed update.
        """
        self.latest_action = {
            LatestActionKeys.TEXT: action,
            LatestActionKeys.PERSIST: persist,
        }

    async def setup_hook(self):
        """
        Runs once when the bot starts. Connects to Lavalink node and loads extensions.
        """
        ssl_enabled = os.getenv("SSL_ENABLED", "false").lower() == "true"
        protocol = "wss://" if ssl_enabled else "ws://"

        await wavelink.Pool.connect(
            nodes=[
                wavelink.Node(
                    uri=f"{protocol}{os.getenv(EnvironmentKeys.LAVALINK_HOST)}:{os.getenv(EnvironmentKeys.LAVALINK_PORT)}",
                    password=os.getenv(EnvironmentKeys.LAVALINK_PASSWORD),
                )
            ],
            client=self,
            cache_capacity=100,
        )
        await self.load_extension("cogs.commands")
        await self.load_extension("cogs.events")
        await self.tree.sync()

    async def load_setup_message_cache(self) -> None:
        """
        Loads and caches the setup messages for each guild from the stored setup_channels.
        If the setup channel isn't found or an error occurs while fetching the message,
        the guild's entry is removed from both the in-memory setup_channels and the local file.
        Also loads the DJ role (if stored) into self.dj_roles.
        """
        guild_count = len(self.setup_channels)
        delay = 0.02 if guild_count > 50 else 0

        for guild_id, data in list(self.setup_channels.items()):
            channel_id = data.get(SetupChannelKeys.CHANNEL)
            message_id = data.get(SetupChannelKeys.MESSAGE)
            guild = self.get_guild(guild_id)
            if not guild:
                logging.error(
                    f"Guild {guild_id} not found. Removing from setup_channels."
                )
                remove_setup_channel(guild_id, self.setup_channels)
                continue

            channel = guild.get_channel(channel_id)
            if not channel:
                logging.error(
                    f"Channel {channel_id} not found in guild {guild_id}. Removing from setup_channels."
                )
                remove_setup_channel(guild_id, self.setup_channels)
                continue

            try:
                msg = await channel.fetch_message(message_id)
                self.setup_message_cache[guild_id] = msg
                logging.info(f"Cached setup message for guild {guild_id}.")
            except Exception as e:
                logging.error(
                    f"Error fetching setup message for guild {guild_id}: {e}. Removing from setup_channels."
                )
                remove_setup_channel(guild_id, self.setup_channels)
                continue

            if SetupChannelKeys.DJ_ROLE in data:
                role_id = data.get(SetupChannelKeys.DJ_ROLE)
                dj_role = guild.get_role(role_id)
                if dj_role:
                    self.dj_roles[guild_id] = dj_role
                else:
                    logging.warning(
                        f"DJ role with ID {role_id} not found in guild {guild_id}. Removing from setup_channels."
                    )
                    del data[SetupChannelKeys.DJ_ROLE]
                    save_setup_channels(self.setup_channels)
            if delay:
                await asyncio.sleep(delay)

    async def create_setup_channel(self, guild: discord.Guild) -> str:
        """
        Creates a dedicated music request channel for the guild,
        sends the initial status message with an embed and control view,
        updates the in-memory dictionary, the message cache, and persistent storage,
        and returns a message string that the caller (commands) can display.
        """
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                send_messages=True,
                read_messages=True,
                manage_messages=False,
                embed_links=False,
            ),
            guild.me: discord.PermissionOverwrite(
                send_messages=True, manage_messages=True, read_message_history=True
            ),
        }

        try:
            channel = await guild.create_text_channel(
                name="🎵music-requests", overwrites=overwrites
            )
            embed = self.create_default_embed()
            view = PlayerControlView(self, None)
            status_message = await channel.send(embed=embed, view=view)
            data = self.setup_channels.get(guild.id, {})
            data[SetupChannelKeys.CHANNEL] = channel.id
            data[SetupChannelKeys.MESSAGE] = status_message.id
            self.setup_channels[guild.id] = data
            save_setup_channels(self.setup_channels)
            self.setup_message_cache[guild.id] = status_message

            dj_role = self.dj_roles.get(guild.id)
            if dj_role:
                await channel.set_permissions(
                    guild.default_role,
                    overwrite=discord.PermissionOverwrite(view_channel=False),
                )

                dj_overwrites = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                    embed_links=True,
                )
                await channel.set_permissions(dj_role, overwrite=dj_overwrites)
                logging.info(
                    f"Updated permissions for existing DJ role in guild {guild.id}."
                )

            return f"Music channel created: {channel.mention}"
        except discord.Forbidden:
            return "I need permissions to manage channels!"

    def create_now_playing_embed(
        self, track: wavelink.Playable, original: wavelink.Playable | None
    ) -> discord.Embed:
        embed = discord.Embed(
            title=track.title, url=track.uri, color=discord.Color.blue()
        )
        embed.set_author(
            name="Now Playing",
            icon_url=os.getenv(EnvironmentKeys.NOW_PLAYING_SPIN_GIF_URL),
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
        else:
            embed.set_image(url=os.getenv("NO_SONG_PLAYING_IMAGE_URL"))
        if self.latest_action:
            embed.set_footer(text=self.latest_action[LatestActionKeys.TEXT])
            self.latest_action = None
        return embed

    def create_default_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Now Playing", description="No song currently playing"
        )
        embed.set_image(url=os.getenv(EnvironmentKeys.NO_SONG_PLAYING_IMAGE_URL))
        if self.latest_action:
            embed.set_footer(text=self.latest_action[LatestActionKeys.TEXT])
        return embed

    async def create_dj_role(self, guild: discord.Guild) -> str:
        """
        Creates a DJ role for the guild and updates persistent storage and
        the in-memory cache. If the DJ role already exists, the function returns
        a message indicating so. Otherwise, it creates the role and updates
        the music channel’s permissions so that only the DJ role can see it.
        """
        setup_data = self.setup_channels.get(guild.id, {})

        if SetupChannelKeys.DJ_ROLE in setup_data:
            dj_role = guild.get_role(setup_data[SetupChannelKeys.DJ_ROLE])
            if dj_role:
                return f"DJ role already exists: {dj_role.mention}"

        try:
            dj_role = await guild.create_role(
                name=SetupChannelKeys.DJ_ROLE_NAME,
                mentionable=True,
                reason="DJ role created via bot command.",
            )
        except discord.Forbidden:
            return "I do not have permission to create roles."

        setup_data[SetupChannelKeys.DJ_ROLE] = dj_role.id
        self.setup_channels[guild.id] = setup_data
        save_setup_channels(self.setup_channels)
        self.dj_roles[guild.id] = dj_role

        channel_id = setup_data.get(SetupChannelKeys.CHANNEL)
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                await channel.set_permissions(
                    guild.default_role,
                    overwrite=discord.PermissionOverwrite(view_channel=False),
                )

                dj_overwrites = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                    embed_links=True,
                )
                await channel.set_permissions(dj_role, overwrite=dj_overwrites)

        return f"DJ role created successfully: {dj_role.mention}"

    async def remove_dj_role(self, guild: discord.Guild) -> str:
        """
        Removes the DJ role for the guild and updates persistent storage and
        in-memory cache. If the DJ role is removed, it also updates the permissions
        of the music channel so that everyone can access it. Returns a message
        describing the outcome.
        """
        setup_data = self.setup_channels.get(guild.id, {})
        dj_role = None
        if SetupChannelKeys.DJ_ROLE in setup_data:
            dj_role = guild.get_role(setup_data[SetupChannelKeys.DJ_ROLE])
        if not dj_role:
            return "No DJ role found to remove."

        try:
            await dj_role.delete(reason="DJ role removed via bot command.")
        except discord.Forbidden:
            return "I do not have permission to delete roles."

        self.dj_roles.pop(guild.id, None)
        if SetupChannelKeys.DJ_ROLE in setup_data:
            del setup_data[SetupChannelKeys.DJ_ROLE]
            self.setup_channels[guild.id] = setup_data
            save_setup_channels(self.setup_channels)

        channel_id = setup_data.get(SetupChannelKeys.CHANNEL)
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    default_overwrite = discord.PermissionOverwrite(
                        send_messages=True,
                        read_messages=True,
                        manage_messages=False,
                        embed_links=False,
                    )
                    await channel.set_permissions(
                        guild.default_role, overwrite=default_overwrite
                    )
                except Exception as e:
                    return f"DJ role removed, but failed to update channel permissions: {e}"

        return "DJ role removed. The music channel is now public for everyone."

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
                    player.queue.get(),
                    volume=int(os.getenv(EnvironmentKeys.BOT_VOLUME)),
                )

            if not player.queue.is_empty:
                await self.update_setup_embed(
                    guild=player.guild,
                    player=player,
                    view=PlayerControlView(self, player),
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
                    player.queue.get(),
                    volume=int(os.getenv(EnvironmentKeys.BOT_VOLUME)),
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
        await self.update_setup_embed(
            guild,
            player,
            embed=self.create_default_embed(),
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
    ) -> None:
        """
        Updates the embed and view in the setup channel using the cached setup message.
        This avoids duplicate API calls by referencing the cached message.
        """
        setup_data = self.setup_channels.get(guild.id)
        if not setup_data:
            return

        channel_id = setup_data.get(SetupChannelKeys.CHANNEL)
        message_id = setup_data.get(SetupChannelKeys.MESSAGE)
        channel = guild.get_channel(channel_id)
        if channel is None:
            logging.error("Channel %s not found for guild %s", channel_id, guild.id)
            return

        embed = await self._fetch_or_create_embed(channel, message_id, embed)
        view = view or PlayerControlView(self, player)
        new_message_id, edited, original_message = (
            await self._update_or_replace_message(channel, message_id, embed, view)
        )
        setup_data[SetupChannelKeys.MESSAGE] = new_message_id
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
        Attempts to retrieve the embed from a cached message.
        If not available, fetches the message, caches it, and returns its embed.
        If the message has no embed or an error occurs, returns a default embed.
        """
        guild_id = channel.guild.id
        message = self.setup_message_cache.get(guild_id)
        if message is None:
            try:
                message = await channel.fetch_message(message_id)
                self.setup_message_cache[guild_id] = message
                logging.info("Fetched and cached message for guild %s.", guild_id)
            except Exception as e:
                logging.error("Error fetching embed for guild %s: %s", guild_id, e)
                return self.create_default_embed()

        if embed is None:
            embed = message.embeds[0] if message.embeds else self.create_default_embed()
        if self.latest_action:
            embed.set_footer(text=self.latest_action[LatestActionKeys.TEXT])
        return embed

    async def _update_or_replace_message(
        self,
        channel: discord.TextChannel,
        message_id: int,
        embed: discord.Embed,
        view: discord.ui.View,
    ) -> tuple[int, bool, discord.Message | None]:
        """
        Updates the cached message if possible; if it’s flagged for deletion or not found,
        sends a new message instead and updates the cache accordingly.

        Returns:
            new_message_id (int): The ID of the updated or new message.
            edited (bool): True if the original message was successfully edited.
            message (discord.Message | None): The updated (or new) message object.
        """
        guild_id = channel.guild.id
        message = self.setup_message_cache.get(guild_id)
        try:
            if message is None:
                message = await channel.fetch_message(message_id)
            if message_id in self.delete_message_tags:
                await message.delete()
                self.delete_message_tags.discard(message_id)
                new_message = await channel.send(embed=embed, view=view)
                self.setup_message_cache[guild_id] = new_message
                return new_message.id, False, new_message
            else:
                await message.edit(embed=embed, view=view)
                new_message = await channel.fetch_message(message_id)
                self.setup_message_cache[guild_id] = new_message
                return message_id, True, new_message
        except discord.NotFound:
            new_message = await channel.send(embed=embed, view=view)
            self.setup_message_cache[guild_id] = new_message
            return new_message.id, False, new_message
        except Exception as e:
            logging.error("Error updating setup message: %s", e)
            return message_id, False, None
