from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, List, Optional

import wavelink
from discord import Interaction
from discord.ui import Button, View, button

if TYPE_CHECKING:
    from music_bot import Bot


class ControlButton(Enum):
    """Enum representing available player control buttons"""

    STOP = "control_stop"
    PAUSE_RESUME = "control_pause_resume"
    SKIP = "control_skip"
    SHUFFLE = "control_shuffle"


class PlayerControlView(View):
    """
    A Discord UI view for player control buttons with enum-based button control.
    """

    def __init__(
        self,
        bot: Bot,
        player: Optional[wavelink.Player],
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
                self.player.queue.count <= 1
                and child.custom_id == ControlButton.SHUFFLE.value
            ):
                child.disabled = True

            # Apply manual disables
            if child.custom_id in disabled_ids:
                child.disabled = True

    @button(emoji="⏹️", custom_id=ControlButton.STOP.value)
    async def stop_button(self, interaction: Interaction, button: Button):
        await self.bot.handle_stop_action(
            interaction, interaction.guild, interaction.user, self.player
        )

    @button(emoji="⏸️", custom_id=ControlButton.PAUSE_RESUME.value)
    async def pause_button(self, interaction: Interaction, button: Button):
        await self.bot.handle_toggle_action(
            interaction, interaction.guild, interaction.user, self.player
        )

    @button(emoji="⏭️", custom_id=ControlButton.SKIP.value)
    async def skip_button(self, interaction: Interaction, button: Button):
        await self.bot.handle_skip_action(
            interaction, interaction.guild, interaction.user, self.player
        )

    @button(emoji="🔀", custom_id=ControlButton.SHUFFLE.value)
    async def shuffle_button(self, interaction: Interaction, button: Button):
        await self.bot.handle_shuffle_action(
            interaction, interaction.guild, interaction.user, self.player
        )
