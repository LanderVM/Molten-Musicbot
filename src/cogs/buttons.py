from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Awaitable, List, Optional

import discord
from discord import Interaction
from discord.ui import Button, View, button

import lavalink
from utils import Error, format_duration_mm_ss, get_track_display_title

if TYPE_CHECKING:
    from music_bot import Bot


class ControlButton(Enum):
    """Enum representing available player control buttons"""

    STOP = "control_stop"
    PAUSE_RESUME = "control_pause_resume"
    SKIP = "control_skip"
    SHUFFLE = "control_shuffle"


IDLE_DISABLED_BUTTONS = (
    ControlButton.STOP,
    ControlButton.PAUSE_RESUME,
    ControlButton.SKIP,
    ControlButton.SHUFFLE,
)


class PlayerControlView(View):
    """
    A Discord UI view for player control buttons with enum-based button control.
    """

    def __init__(
        self,
        bot: Bot,
        player: Optional[lavalink.DefaultPlayer],
        disabled_buttons: List[ControlButton] = None,
        *,
        timeout: float = None,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.player = player
        disabled_ids = [btn.value for btn in (disabled_buttons or [])]

        # Set button states
        for child in self.children:
            if not isinstance(child, Button):
                continue

            # Automatic state management
            if self.player is None:
                child.disabled = True
            elif child.custom_id == ControlButton.PAUSE_RESUME.value:
                child.emoji = "▶️" if self.player.paused else "⏸️"
            elif (
                len(self.player.queue) <= 1
                and child.custom_id == ControlButton.SHUFFLE.value
            ):
                child.disabled = True

            # Apply manual disables
            if child.custom_id in disabled_ids:
                child.disabled = True

    async def _handle_control_action(
        self, interaction: Interaction, action: Awaitable[object]
    ) -> None:
        msg = await action
        if isinstance(msg, Error):
            await interaction.response.send_message(msg, ephemeral=True, delete_after=3)
            return
        await interaction.response.defer()

    @button(emoji="⏹️", custom_id=ControlButton.STOP.value)
    async def stop_button(self, interaction: Interaction, button: Button):
        await self._handle_control_action(
            interaction,
            self.bot.handle_stop_action(
                interaction, interaction.guild, interaction.user, self.player
            ),
        )

    @button(emoji="⏸️", custom_id=ControlButton.PAUSE_RESUME.value)
    async def pause_button(self, interaction: Interaction, button: Button):
        await self._handle_control_action(
            interaction,
            self.bot.handle_toggle_action(
                interaction, interaction.guild, interaction.user, self.player
            ),
        )

    @button(emoji="⏭️", custom_id=ControlButton.SKIP.value)
    async def skip_button(self, interaction: Interaction, button: Button):
        await self._handle_control_action(
            interaction,
            self.bot.handle_skip_action(
                interaction, interaction.guild, interaction.user, self.player
            ),
        )

    @button(emoji="🔀", custom_id=ControlButton.SHUFFLE.value)
    async def shuffle_button(self, interaction: Interaction, button: Button):
        await self._handle_control_action(
            interaction,
            self.bot.handle_shuffle_action(
                interaction, interaction.guild, interaction.user, self.player
            ),
        )


class QueueView(View):
    def __init__(
        self, user: discord.User, tracks: List[lavalink.AudioTrack], page_size: int = 15
    ):
        super().__init__(timeout=120)
        self.user = user
        self.tracks = tracks

        self.embeds: List[discord.Embed] = []
        total_pages = (len(tracks) - 1) // page_size + 1
        for page in range(total_pages):
            start = page * page_size
            chunk = tracks[start : start + page_size]

            lines = []
            for i, track in enumerate(chunk, start=start + 1):
                length = getattr(track, "duration", 0)
                dur = format_duration_mm_ss(length)
                title = get_track_display_title(track)
                uri = getattr(track, "uri", None)
                track_text = f"[{title}]({uri})" if uri else title
                lines.append(f"**{i}.** {track_text} — `{dur}`")

            desc = (
                f"Page {page+1}/{total_pages}\n"
                f"Total tracks: {len(tracks)}\n\n" + "\n".join(lines)
            )
            embed = discord.Embed(
                title="Queue", description=desc, color=discord.Color.purple()
            )
            self.embeds.append(embed)

        self.page = 0
        self.prev.disabled = True
        self.next.disabled = len(self.embeds) <= 1

    def current_embed(self) -> discord.Embed:
        return self.embeds[self.page]

    @discord.ui.button(label="⬅️ Prev", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: Interaction, button: Button):
        self.page -= 1
        self.prev.disabled = self.page == 0
        self.next.disabled = False
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Next ➡️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: Interaction, button: Button):
        self.page += 1
        self.next.disabled = self.page >= len(self.embeds) - 1
        self.prev.disabled = False
        await interaction.response.edit_message(embed=self.current_embed(), view=self)
