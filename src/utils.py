import json
import logging
import os
from typing import Any, cast

import discord
import wavelink

SETUP_CHANNELS_FILE = "setup_channels.json"


def load_setup_channels() -> dict:
    """
    Loads the setup channels from a JSON file.

    Returns:
        A dict with guild IDs as keys (as ints) and channel info as values.
    """
    if os.path.exists(SETUP_CHANNELS_FILE):
        try:
            with open(SETUP_CHANNELS_FILE, "r") as f:
                data = json.load(f)
            return {int(guild_id): info for guild_id, info in data.items()}
        except Exception as e:
            logging.error(f"Failed to load setup channels: {e}")
            return {}
    else:
        return {}


def save_setup_channels(data: dict) -> None:
    """
    Saves the setup channels dict to a JSON file.

    Args:
        data: The dict to save.
    """
    try:
        with open(SETUP_CHANNELS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logging.error(f"Failed to save setup channels: {e}")


def format_duration(ms: int) -> str:
    """
    Converts milliseconds to a formatted time string.

    Args:
        ms: Duration in milliseconds.

    Returns:
        A string formatted as MM:SS or HH:MM:SS.
    """
    seconds = ms // 1000
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def ensure_player(interaction: discord.Interaction) -> Any:
    """
    Checks for an existing voice client for the guild.
    If not present, attempts to connect using the interaction user's voice channel.

    Args:
        interaction: The interaction invoking the command.

    Returns:
        The Wavelink player instance or None if connection fails.
    """
    player: wavelink.Player = cast(wavelink.Player, interaction.guild.voice_client)
    return player
