from enum import StrEnum


class SetupChannelKeys(StrEnum):
    CHANNEL = "channel"
    MESSAGE = "message"
    DJ_ROLE = "dj_role"
    DJ_ROLE_NAME = "Molten_DJ"


class LatestActionKeys(StrEnum):
    TEXT = "text"
    PERSIST = "persist"


class EnvironmentKeys(StrEnum):
    DISCORD_TOKEN = "DISCORD_BOT_TOKEN"
    LAVALINK_HOST = "LAVALINK_HOST"
    LAVALINK_PORT = "LAVALINK_PORT"
    LAVALINK_PASSWORD = "LAVALINK_PASSWORD"
    NOW_PLAYING_SPIN_GIF_URL = "NOW_PLAYING_SPIN_GIF_URL"
    NO_SONG_PLAYING_IMAGE_URL = "NO_SONG_PLAYING_IMAGE_URL"
    BOT_VOLUME = "BOT_VOLUME"
    SSL_ENABLED = "SSL_ENABLED"
    LOG_LEVEL = "LOG_LEVEL"
