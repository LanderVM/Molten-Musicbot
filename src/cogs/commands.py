from __future__ import annotations

from typing import TYPE_CHECKING, cast

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from cogs.buttons import PlayerControlView
from utils import save_setup_channels

if TYPE_CHECKING:
    from music_bot import Bot


class MusicCommands(commands.Cog):
    """
    A cog for music-related slash commands.
    Provides functionality for setup, playback control, queue manipulation, and audio effects.
    """

    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    @app_commands.command(
        name="setup",
        description="Create a dedicated music request channel with persistent player status.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_create(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message(
                "This command can only be used in a guild.", ephemeral=True
            )

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
            embed = self.bot.create_default_embed()
            view = PlayerControlView(self.bot, None)
            status_message = await channel.send(embed=embed, view=view)

            self.bot.setup_channels[guild.id] = {
                "channel": channel.id,
                "message": status_message.id,
            }
            save_setup_channels(self.bot.setup_channels)

            await interaction.response.send_message(
                f"Music channel created: {channel.mention}"
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I need permissions to manage channels!", ephemeral=True
            )

    @app_commands.command(name="play", description="Play a song with the given query.")
    async def play(self, interaction: discord.Interaction, query: str):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_play_action(
            interaction, interaction.guild, interaction.user, player, query
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(name="skip", description="Skip the current song.")
    async def skip(self, interaction: discord.Interaction):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_skip_action(
            interaction, interaction.guild, interaction.user, player
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(
        name="toggle", description="Toggle pause/resume of the current song."
    )
    async def pause_resume(self, interaction: discord.Interaction):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_toggle_action(
            interaction, interaction.guild, interaction.user, player
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(name="disconnect", description="Disconnect the player.")
    async def disconnect(self, interaction: discord.Interaction):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_disconnect_action(
            interaction, interaction.guild, interaction.user, player
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(
        name="shuffle", description="Shuffle the current queue of songs."
    )
    async def shuffle(self, interaction: discord.Interaction):
        player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
        msg = await self.bot.handle_shuffle_action(
            interaction, interaction.guild, interaction.user, player
        )
        await interaction.response.send_message(msg, ephemeral=True, delete_after=3)

    @app_commands.command(
        name="nightcore",
        description="Toggle the Nightcore effect (timescale) on or off.",
    )
    @app_commands.describe(mode="Toggle Nightcore effect")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Off", value=0),
            app_commands.Choice(name="Nightcore", value=1),
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
        name="help",
        description="Get information on how to set up the music bot and usage instructions.",
    )
    async def help_command(self, interaction: discord.Interaction):
        help_message = """
**Music Bot Setup Help:**

To set up a music request channel in your server, use the `/setup` command. This will create a dedicated channel where users can send song requests.
        
Once the channel is created, you can:
- Use the `/play <song name>` command to play a song.
- Use the `/skip` command to skip the current song.
- Use the `/toggle` command to pause or resume the song.
- Use the `/shuffle` command to shuffle the current queue.
- Use the `/nightcore` command to toggle the Nightcore effect on or off.
- Use the `/disconnect` command to disconnect the player and stop playback.

The bot will automatically manage the player and display the current song status in the setup channel.

Happy listening! 🎶
        """
        await interaction.response.send_message(help_message, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCommands(bot))
