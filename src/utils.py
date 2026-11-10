import asyncio
import ipaddress
import json
import os
import socket
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from urllib.parse import urlparse, urlsplit

SETUP_CHANNELS_FILE = "data/setup_channels.json"
os.makedirs(os.path.dirname(SETUP_CHANNELS_FILE), exist_ok=True)

_save_lock = asyncio.Lock()  # Prevents concurrent JSON writes from corrupting file


def _blocked_stream_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            return _blocked_stream_address(str(address.ipv4_mapped))
        if address.sixtofour and _blocked_stream_address(str(address.sixtofour)):
            return True
        if address.teredo and any(
            _blocked_stream_address(str(ip)) for ip in address.teredo
        ):
            return True
        if address in ipaddress.ip_network("64:ff9b::/96"):
            return _blocked_stream_address(
                str(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
            )
        if address in ipaddress.ip_network("64:ff9b:1::/48"):
            return True
    return (
        not address.is_global
        or address.is_multicast
        or address.is_reserved
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
    )


async def direct_url_error(value: str) -> str | None:
    """Blacklist non-public submitted destinations without restricting station hosts/ports.

    This is an input check, not an egress firewall: Lavalink resolves and fetches
    independently, including redirects and URLs embedded in media playlists.
    """
    blocked = "Request invalid."
    try:
        if any(ord(char) <= 32 or ord(char) == 127 for char in value) or "\\" in value:
            raise ValueError("Ambiguous URL")
        parsed = urlsplit(value)
        host = (
            (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        )
        if parsed.scheme not in ("http", "https") or not host or "%" in host:
            raise ValueError("Invalid HTTP host")
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        if port == 0:
            raise ValueError("Invalid port")
        if (
            host == "localhost"
            or host.endswith((".localhost", ".local"))
            or host
            in (
                "host.docker.internal",
                "gateway.docker.internal",
            )
        ):
            return blocked
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # inet_aton catches integer, short, hexadecimal and octal IPv4 forms
            # that HTTP stacks can otherwise interpret differently from a URL parser.
            try:
                address = ipaddress.ip_address(socket.inet_aton(host))
            except OSError:
                address = None
        if address is not None:
            return blocked if _blocked_stream_address(str(address)) else None
        records = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=5,
        )
        if not records:
            return "Could not verify this URL's hostname."
        if any(_blocked_stream_address(record[4][0]) for record in records):
            return blocked
        return None
    except (ValueError, UnicodeError):
        return "Invalid HTTP(S) URL."
    except (OSError, asyncio.TimeoutError):
        return "Could not verify this URL's hostname; try again later."


class TrackWithTitleAndUri(Protocol):
    title: str | None
    uri: str | None


def get_track_display_title(track: TrackWithTitleAndUri) -> str:
    title = getattr(track, "title", None)
    if title and title.strip().lower() != "unknown title":
        return title

    uri = getattr(track, "uri", None)
    if not uri:
        return title or "Unknown title"

    try:
        parsed = urlparse(uri if "://" in uri else f"https://{uri}")

        host = parsed.hostname or ""
        host = host.lower()

        if host.startswith("www."):
            host = host[4:]

        return host or (title or "Unknown title")

    except Exception:
        return title or "Unknown title"


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
            if not isinstance(data, dict) or any(
                not isinstance(info, dict) for info in data.values()
            ):
                raise ValueError("Expected guild settings objects")
            return {int(guild_id): info for guild_id, info in data.items()}
        except (OSError, ValueError, TypeError) as e:
            raise RuntimeError(
                f"Cannot read {SETUP_CHANNELS_FILE}; repair or restore it before starting"
            ) from e
    else:
        return {}


def save_setup_channels_sync(data: dict) -> None:
    """
    Saves the setup channels dict to a JSON file.

    Args:
        data: The dict to save.
    """
    directory = os.path.dirname(os.path.abspath(SETUP_CHANNELS_FILE))
    os.makedirs(directory, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=".setup-",
            suffix=".tmp",
            delete=False,
        ) as f:
            temp_path = f.name
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, SETUP_CHANNELS_FILE)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


async def save_setup_channels_async(data: dict) -> None:
    async with _save_lock:
        snapshot = json.loads(json.dumps(data))
        worker = asyncio.create_task(
            asyncio.to_thread(save_setup_channels_sync, snapshot)
        )
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Keep the lock until the worker finishes, even during shutdown.
            await worker
            raise


def dj_permission_error(guild, user, setup_channels: dict) -> str | None:
    """One rule for slash commands, typed requests, and player buttons."""
    if guild is None:
        return "This action can only be used in a server."
    role_id = setup_channels.get(guild.id, {}).get("dj_role")
    if role_id and not any(role.id == role_id for role in getattr(user, "roles", ())):
        return "🚫 You need the configured DJ role to use music controls."
    return None


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


def format_duration_mm_ss(ms: int) -> str:
    """Formats milliseconds as MM:SS for compact queue display."""
    seconds = ms // 1000
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d}"


def format_uptime(uptime: timedelta) -> str:
    """Formats timedelta as a compact uptime string (e.g. 2d 3h 4m 5s)."""
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


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


@dataclass
class LatestAction:
    text: str
    persist: bool = False
