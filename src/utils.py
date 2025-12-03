import asyncio
import json
import logging
import os
from dataclasses import dataclass

SETUP_CHANNELS_FILE = "data/setup_channels.json"
os.makedirs(os.path.dirname(SETUP_CHANNELS_FILE), exist_ok=True)


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


def save_setup_channels_sync(data: dict) -> None:
    """
    Saves the setup channels dict to a JSON file.

    Args:
        data: The dict to save.
    """
    with open(SETUP_CHANNELS_FILE, "w") as f:
        json.dump(data, f)


async def save_setup_channels_async(data: dict) -> None:
    await asyncio.to_thread(save_setup_channels_sync, data)


def remove_setup_channel(guild_id: int, data: dict) -> None:
    """
    Removes the setup channel entry for the given guild ID from the provided data dictionary
    and saves the updated data to the JSON file.

    Args:
        guild_id (int): The guild ID to remove.
        data (dict): The current setup channels dictionary.
    """
    if guild_id in data:
        del data[guild_id]
        asyncio.create_task(save_setup_channels_async(data))


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


@dataclass
class Error:
    """Represents an error result."""

    message: str

    def __str__(self):
        return self.message


@dataclass
class Success:
    """Represents a non‐error result."""

    message: str

    def __str__(self):
        return self.message
