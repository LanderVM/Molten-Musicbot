from __future__ import annotations

from typing import TYPE_CHECKING, Optional, cast

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from enums import SetupChannelKeys
from utils import Error

if TYPE_CHECKING:
    from music_bot import Bot


class MusicCommands(commands.Cog):
    """
    A cog for music-related slash commands.
    Provides functionality for setup, playback control, queue manipulation, and audio effects.
    """

    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            missing = ", ".join(error.missing_permissions)
            await interaction.response.send_message(
                f"🚫 You need the `{missing}` permission(s) to use this command.",
                ephemeral=True,
                delete_after=5,
            )
        else:
            await interaction.response.send_message(
                "❌ An error occurred while running the command.", ephemeral=True
            )
            raise error

    def dj_role_required(interaction: discord.Interaction) -> bool:
        """
        Checks if the user has the DJ role required for music commands.
        Uses the DJ role stored in the setup_channels via its ID.
        If no DJ role is stored for the guild, the command is allowed.
        """
        guild = interaction.guild
        if guild is None:
            return True

        bot: Bot = interaction.client
        setup_data = bot.setup_channels.get(guild.id)
        dj_role = None
        if setup_data and SetupChannelKeys.DJ_ROLE in setup_data:
            dj_role = guild.get_role(setup_data[SetupChannelKeys.DJ_ROLE])

        if dj_role is None or dj_role in interaction.user.roles:
            return True

        raise app_commands.MissingPermissions([SetupChannelKeys.DJ_ROLE_NAME])

    @app_commands.command(
        name="setup",
        description="Create a dedicated music request channel with persistent player status.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_create(self, interaction: discord.Interaction):
        msg = await self.bot.create_setup_channel(interaction.guild)
        await interaction.response.send_message(msg, ephemeral=True, delete_after=5)

    @app_commands.command(name="play", description="Play a song with the given query.")
    @app_commands.check(dj_role_required)
    async def play(self, interaction: discord.Interaction, query: str):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_play_action(
            interaction, interaction.guild, interaction.user, player, query
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(name="stop", description="Stop playback and clear the queue.")
    @app_commands.check(dj_role_required)
    async def stop(self, interaction: discord.Interaction):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_stop_action(
            interaction, interaction.guild, interaction.user, player
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(name="skip", description="Skip the current song.")
    @app_commands.check(dj_role_required)
    @app_commands.describe(count="How many tracks to skip (default = 1)")
    async def skip(self, interaction: discord.Interaction,  count: Optional[app_commands.Range[int, 1, None]] = 1):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_skip_action(
            interaction, interaction.guild, interaction.user, player, count
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(
        name="toggle", description="Toggle pause/resume of the current song."
    )
    @app_commands.check(dj_role_required)
    async def pause_resume(self, interaction: discord.Interaction):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_toggle_action(
            interaction, interaction.guild, interaction.user, player
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(name="disconnect", description="Disconnect the player.")
    @app_commands.check(dj_role_required)
    async def disconnect(self, interaction: discord.Interaction):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_disconnect_action(
            interaction, interaction.guild, interaction.user, player
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(
        name="shuffle", description="Shuffle the current queue of songs."
    )
    @app_commands.check(dj_role_required)
    async def shuffle(self, interaction: discord.Interaction):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_shuffle_action(
            interaction, interaction.guild, interaction.user, player
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(name="queue", description="Display the current queue.")
    @app_commands.check(dj_role_required)
    @app_commands.describe(page_size="Number of songs to display per page [10-25]")
    async def queue(self, interaction: discord.Interaction, page_size: app_commands.Range[int, 10, 25] = 20):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        result = await self.bot.handle_queue_action(
            interaction, interaction.guild, interaction.user, player, page_size
        )
        if isinstance(result, Error):
            await interaction.response.send_message(result, ephemeral=True)
            return
        embed, view = result
        await interaction.response.send_message(
            embed=embed, view=view, ephemeral=True, delete_after=120
        )

    @app_commands.command(
        name="forward", description="Forward song by a given number of seconds"
    )
    @app_commands.check(dj_role_required)
    @app_commands.describe(seconds="Number of seconds to skip forward")
    async def forward(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 1, None]):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_forward_action(
            interaction, interaction.guild, interaction.user, player, seconds
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(
        name="nightcore",
        description="Toggle the Nightcore effect (timescale) on or off.",
    )
    @app_commands.check(dj_role_required)
    @app_commands.describe(mode="Toggle Nightcore effect")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Off", value=0),
            app_commands.Choice(name="On", value=1),
        ]
    )
    async def nightcore(
        self, interaction: discord.Interaction, mode: app_commands.Choice[int]
    ):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_nightcore_action(
            interaction, interaction.guild, interaction.user, player, mode.value
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(
        name="create_dj",
        description="Create a DJ role to restrict music channel access and command usage.",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def create_dj(self, interaction: discord.Interaction):
        msg = await self.bot.create_dj_role(interaction.guild)
        await interaction.response.send_message(msg, ephemeral=True, delete_after=5)

    @app_commands.command(
        name="remove_dj",
        description="Remove the DJ role and make the music channel public.",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    async def remove_dj(self, interaction: discord.Interaction):
        msg = await self.bot.remove_dj_role(interaction.guild)
        await interaction.response.send_message(msg, ephemeral=True, delete_after=5)

    @app_commands.command(
        name="247", description="Toggle 24/7 mode for the music channel."
    )
    @app_commands.check(dj_role_required)
    async def enable_247(self, interaction: discord.Interaction):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_stay_247_action(
            interaction, interaction.guild, interaction.user, player
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(
        name="help",
        description="Get information on how to set up the music bot and usage instructions.",
    )
    async def help_command(self, interaction: discord.Interaction):
        help_message = """
**Music Bot Setup Help:**

To set up a music request channel in your server, use the `/setup` command. This will create a dedicated channel where users can send song requests.
        
Once the channel is created, you can:
- Use the `/play <song name>` command to play a song.
- Use the `/skip [count]` command to skip the current song.
- Use the `/toggle` command to pause or resume the song.
- Use the `/stop` command to stop playback and clear the queue.
- Use the `/shuffle` command to shuffle the current queue.
- Use the `/247` command to enable or disable 24/7 mode for the music channel.
- Use the `/nightcore` command to toggle the Nightcore effect on or off.
- Use the `/create_dj` command to create a DJ role that can manage the music channel and commands.
- Use the `/remove_dj` command to remove the DJ role and make the channel public.
- Use the `/disconnect` command to disconnect the player and stop playback.
- Use the `/forward <seconds>` command to skip forward by a given number of seconds.
- Use the `/queue` command to display the current queue of songs.

The bot will automatically manage the player and display the current song status in the setup channel.

Happy listening! 🎶
        """
        await interaction.response.send_message(help_message, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCommands(bot))
