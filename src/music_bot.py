import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import List, cast

import discord
import wavelink
from discord.ext import commands
from dotenv import load_dotenv

from cogs.buttons import ControlButton, PlayerControlView
from decorators import debounce_action, ensure_voice
from enums import EnvironmentKeys, LatestActionKeys, SetupChannelKeys
from utils import (
    Error,
    Success,
    format_duration,
    load_setup_channels,
    remove_setup_channel,
    save_setup_channels_async,
)

load_dotenv()


class Bot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        logging_level = (
            logging.DEBUG
            if os.getenv(EnvironmentKeys.LOG_LEVEL).lower() == "debug"
            else logging.INFO
        )
        discord.utils.setup_logging(level=logging_level)

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
        self._action_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

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
        ssl_enabled = os.getenv(EnvironmentKeys.SSL_ENABLED, "false").lower() == "true"
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
                logging.warning(
                    f"Guild {guild_id} not found. Removing from setup_channels."
                )
                remove_setup_channel(guild_id, self.setup_channels)
                continue

            channel = guild.get_channel(channel_id)
            if not channel:
                logging.warning(
                    f"Channel {channel_id} not found in guild {guild_id}. Removing from setup_channels."
                )
                remove_setup_channel(guild_id, self.setup_channels)
                continue

            try:
                msg = await channel.fetch_message(message_id)
                self.setup_message_cache[guild_id] = msg
                logging.info(f"Cached setup message for guild {guild_id}.")
            except Exception as e:
                logging.warning(
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
                    asyncio.create_task(save_setup_channels_async(self.setup_channels))
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
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                embed_links=True,
            ),            
            guild.default_role: discord.PermissionOverwrite(
                send_messages=True,
                read_messages=True,
                manage_messages=False,
                embed_links=False,
            ),
        }

        try:
            channel = await guild.create_text_channel(
                name="🎧song-requests", overwrites=overwrites, slowmode_delay=2
            )
            embed = self.create_default_embed()
            view = PlayerControlView(self, None)
            status_message = await channel.send(embed=embed, view=view)
            data = self.setup_channels.get(guild.id, {})
            data[SetupChannelKeys.CHANNEL] = channel.id
            data[SetupChannelKeys.MESSAGE] = status_message.id
            self.setup_channels[guild.id] = data
            asyncio.create_task(save_setup_channels_async(self.setup_channels))
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
            return "I need the following permissions: `Connect`, `Embed Links`, `Manage Channels`, `Manage Messages`, `Manage Roles`, `Send Messages`, `Speak` and `View Channels`."

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
            embed.set_image(url=os.getenv(EnvironmentKeys.NO_SONG_PLAYING_IMAGE_URL))
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

    async def voice_precheck(
        self,
        user: discord.abc.Snowflake,
        guild: discord.Guild,
    ) -> str | None:
        """
        Return an error message if the user is not in a voice channel
        or is not in the same one as the bot. Otherwise None.
        """
        member = guild.get_member(user.id)
        if not member or not member.voice or not member.voice.channel:
            return "🚫 You must join a voice channel first."

        vc = guild.voice_client
        if vc and vc.channel != member.voice.channel:
            return f"🚫 You must be in the same voice channel as the bot ({vc.channel.mention})."

        return None

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
        asyncio.create_task(save_setup_channels_async(self.setup_channels))
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
            asyncio.create_task(save_setup_channels_async(self.setup_channels))

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

    async def _delayed_delete(self, message: discord.Message, delay: float = 0.2):
        """Deletes `message` after `delay` seconds, ignoring NotFound."""
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except discord.NotFound:
            pass

    async def handle_setup_play(self, message: discord.Message) -> str:
        asyncio.create_task(self._delayed_delete(message, delay=0.2))

        return await self.handle_play_action(
            message,
            message.guild,
            message.author,
            cast(wavelink.Player, message.guild.voice_client),
            message.content,
        )

    async def _release_lock_after(self, lock: asyncio.Lock, delay: float):
        await asyncio.sleep(delay)
        if lock.locked():
            lock.release()
            logging.debug(f"Lock released after {delay} seconds.")

    @ensure_voice
    @debounce_action(delay=0.1)
    async def handle_play_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
        query: str,
    ) -> str:
        search_task = asyncio.create_task(wavelink.Playable.search(query))

        if not player:
            try:
                player = await user.voice.channel.connect(cls=wavelink.Player)
            except Exception as e:
                logging.error("Voice connection failed: %s", e)
                return Error("🚫 Could not join your voice channel.")

        try:
            tracks = await search_task
        except Exception as e:
            logging.error("Search failed: %s", e)
            return Error("🔍 Could not search for that track.")

        if not tracks:
            return Error("❌ No results found for that query.")

        player.autoplay = wavelink.AutoPlayMode.partial

        if isinstance(tracks, wavelink.Playlist):
            first = tracks.tracks[0]
            first.requester = user
            await player.queue.put_wait(first)
            msg = f"Added playlist **`{tracks.name}`** to the queue."

            async def _enqueue_rest():
                for t in tracks.tracks[1:]:
                    t.requester = user
                    await player.queue.put_wait(t)

            asyncio.create_task(_enqueue_rest())

        else:
            track = tracks[0]
            track.requester = user
            await player.queue.put_wait(track)
            msg = f"Added **`{track}`** to the queue."

        if not player.playing:
            await asyncio.sleep(0.2)
            next_track = await player.queue.get_wait()
            await player.play(
                next_track,
                volume=int(os.getenv(EnvironmentKeys.BOT_VOLUME)),
            )

        asyncio.create_task(
            self.update_setup_buttons(player.guild, PlayerControlView(self, player))
        )

        return Success(msg)

    @ensure_voice
    @debounce_action(delay=1)
    async def handle_stop_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
    ) -> str:
        """
        Stops the current track, clears the queue, but stays connected.
        """
        if not player:
            return Error("No active player.")

        try:
            self.set_latest_action(f"Stopped by {user.display_name}", persist=True)
            player.queue.clear()
            await player.skip()

            # on_wavelink_track_end in events.py updates the embed, no need to do it here

            return Success("Playback stopped and queue cleared.")
        except Exception as e:
            logging.error(f"Stop error: {e}")
            return Error("Failed to stop playback.")

    @ensure_voice
    @debounce_action(delay=1)
    async def handle_skip_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
        count: int = 1,
    ) -> str:
        if not player or not player.playing:
            return Error("No active player.")
        if count - 1 > player.queue.count:
            return Error(
                f"Cannot skip {count} tracks; only {player.queue.count} in the queue."
            )
        if count > 1:
            for _ in range(count - 1):
                try:
                    player.queue.delete(0)
                except IndexError:
                    break

        try:
            self.set_latest_action(f"Skipped by {user.display_name}", persist=True)
            await player.skip(force=True)
            return Success(f"⏭️ Skipped {count} track{'s' if count>1 else ''}.")
        except Exception as e:
            logging.error("Skip error", exc_info=e)
            return Error("Failed to skip.")

    @ensure_voice
    @debounce_action(delay=1)
    async def handle_toggle_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
    ) -> str:
        if not player:
            return Error("No active player.")

        new_pause_state = not player.paused
        try:
            await player.pause(new_pause_state)
        except Exception as e:
            logging.error(f"Toggle error: {e}")
            return Error("Failed to toggle pause/resume.")

        action = "Paused" if new_pause_state else "Resumed"
        self.set_latest_action(f"{action} by {user.display_name}")
        await self.update_setup_embed(guild, player)
        return Success(f"{action} the current track.")

    async def handle_disconnect_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
    ) -> str:
        if not guild.voice_client:
            return Error("🚫 I’m not connected to any voice channel.")
        try:
            self.set_latest_action(f"Disconnected by {user.display_name}")
            await player.disconnect()

        except Exception as e:
            logging.error(f"Disconnect error: {e}")
            return "Failed to disconnect the player."

        await self.update_setup_embed(
            guild,
            player,
            embed=self.create_default_embed(),
            view=PlayerControlView(
                self,
                player,
                disabled_buttons=[
                    ControlButton.STOP,
                    ControlButton.PAUSE_RESUME,
                    ControlButton.SKIP,
                    ControlButton.SHUFFLE,
                ],
            ),
        )

        return "Disconnected the player."

    @ensure_voice
    async def handle_shuffle_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
    ) -> str:
        if not player or player.queue.is_empty:
            return Error("No active player or the queue is empty.")
        try:
            player.queue.shuffle()
            self.set_latest_action(f"Shuffled by {user.display_name}")
            await self.update_setup_embed(guild, player)
            return Success("The queue has been shuffled!")
        except Exception as e:
            logging.error(f"Shuffle error: {e}")
            return Error("Failed to shuffle the queue.")

    async def handle_queue_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
        page_size: int,
    ):
        if not player or not player.queue:
            return Error("The queue is empty.")

        tracks = player.queue.copy()
        view = QueueView(interaction.user, tracks, page_size)
        embed = view.current_embed()
        return embed, view

    @ensure_voice
    @debounce_action(delay=0.5)
    async def handle_forward_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
        seconds: int,
    ) -> str:
        if not player or not player.playing:
            return Error("No track is currently playing.")

        new_pos = player.position + (seconds * 1000)
        if new_pos >= player.current.length:
            return Error("Cannot forward beyond the end of the track.")

        try:
            await player.seek(new_pos)
            self.set_latest_action(
                f"Forwarded {seconds}s by {user.display_name}", persist=True
            )
            await self.update_setup_embed(guild, player)
            return Success(f"⏩ Forwarded {seconds} seconds.")
        except Exception as e:
            logging.error(f"Forward error: {e}")
            return Error("Failed to forward playback.")

    @ensure_voice
    async def handle_nightcore_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
        mode: int,
    ) -> str:
        if not player:
            return Error("No active player.")

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
            return Success(msg)
        except Exception as e:
            logging.error(f"Filter update error: {e}")
            return Error("Failed to update filters.")

    async def handle_stay_247_action(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        user: discord.User,
        player: wavelink.Player,
    ) -> str:
        setup_data = self.setup_channels.setdefault(guild.id, {})

        current = setup_data.get(SetupChannelKeys.STAY_247, False)
        new_value = not current
        setup_data[SetupChannelKeys.STAY_247] = new_value

        asyncio.create_task(save_setup_channels_async(self.setup_channels))

        await self.check_voice_channel_empty_and_leave(user)

        status = "enabled" if new_value else "disabled"
        return Success(f"24/7 mode {status}!")

    async def check_voice_channel_empty_and_leave(self, member: discord.Member):
        vc = member.guild.voice_client
        if not vc or not vc.channel:
            return

        if member.bot:
            return

        non_bots = [m for m in vc.channel.members if not m.bot]
        if non_bots:
            return

        guild = member.guild
        stay = self.setup_channels.get(guild.id, {}).get(
            SetupChannelKeys.STAY_247, False
        )

        if not stay:
            player: wavelink.Player = cast(wavelink.Player, vc)

            await self.update_setup_embed(
                player.guild,
                player,
                embed=self.create_default_embed(),
                view=PlayerControlView(
                    self,
                    player,
                    disabled_buttons=[
                        ControlButton.STOP,
                        ControlButton.PAUSE_RESUME,
                        ControlButton.SKIP,
                        ControlButton.SHUFFLE,
                    ],
                ),
            )
            await vc.disconnect()

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
            logging.warning("Channel %s not found for guild %s", channel_id, guild.id)
            return

        embed = await self._fetch_or_create_embed(channel, message_id, embed)
        view = view or PlayerControlView(self, player)
        new_message_id, edited, original_message = (
            await self._update_or_replace_message(channel, message_id, embed, view)
        )
        setup_data[SetupChannelKeys.MESSAGE] = new_message_id
        asyncio.create_task(save_setup_channels_async(self.setup_channels))

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
        self.set_latest_action("")

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
                new_message = await message.edit(embed=embed, view=view)
                self.setup_message_cache[guild_id] = new_message
                return message_id, True, new_message
        except discord.NotFound:
            new_message = await channel.send(embed=embed, view=view)
            self.setup_message_cache[guild_id] = new_message
            return new_message.id, False, new_message
        except Exception as e:
            logging.error("Error updating setup message: %s", e)
            return message_id, False, None

    async def update_setup_buttons(
        self,
        guild: discord.Guild,
        view: discord.ui.View,
    ) -> None:
        """
        Fetches the cached setup message for the guild and edits it
        with the new View (buttons) only.
        """
        setup_data = self.setup_channels.get(guild.id)
        if not setup_data:
            return

        channel_id = setup_data.get(SetupChannelKeys.CHANNEL)
        message_id = setup_data.get(SetupChannelKeys.MESSAGE)

        channel = guild.get_channel(channel_id)
        if channel is None:
            logging.warning(f"Channel {channel_id} not found in guild {guild.id}")
            return

        msg = self.setup_message_cache.get(guild.id)
        if msg is None or msg.id != message_id:
            try:
                msg = await channel.fetch_message(message_id)
                self.setup_message_cache[guild.id] = msg
            except Exception as e:
                logging.error(f"Could not fetch setup message {message_id}: {e}")
                return

        try:
            new_msg = await msg.edit(view=view)
            self.setup_message_cache[guild.id] = new_msg
        except Exception as e:
            logging.error(f"Failed to update buttons on setup message: {e}")


class QueueView(discord.ui.View):
    def __init__(
        self, user: discord.User, tracks: List[wavelink.Playable], page_size: int = 15
    ):
        super().__init__(timeout=120)
        self.user = user
        self.tracks = tracks

        # --- PRECOMPUTE ALL PAGES AT INIT TIME ---
        self.embeds: List[discord.Embed] = []
        total_pages = (len(tracks) - 1) // page_size + 1
        for page in range(total_pages):
            start = page * page_size
            chunk = tracks[start : start + page_size]

            # build each page’s embed
            lines = []
            for i, track in enumerate(chunk, start=start + 1):
                dur = f"{track.length//60000}:{(track.length%60000)//1000:02}"
                lines.append(f"**{i}.** [{track.title}]({track.uri}) — `{dur}`")

            desc = (
                f"Page {page+1}/{total_pages}\n"
                f"Total tracks: {len(tracks)}\n\n" + "\n".join(lines)
            )
            embed = discord.Embed(
                title="Queue", description=desc, color=discord.Color.purple()
            )
            self.embeds.append(embed)

        # state
        self.page = 0
        self.prev.disabled = True
        self.next.disabled = len(self.embeds) <= 1

    def current_embed(self) -> discord.Embed:
        return self.embeds[self.page]

    # initial message will call .current_embed()

    @discord.ui.button(label="⬅️ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self.prev.disabled = self.page == 0
        self.next.disabled = False
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self.next.disabled = self.page >= len(self.embeds) - 1
        self.prev.disabled = False
        await interaction.response.edit_message(embed=self.current_embed(), view=self)
