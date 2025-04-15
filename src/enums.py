from enum import StrEnum


class SetupChannelKeys(StrEnum):
    CHANNEL = "channel"
    MESSAGE = "message"
    DJ_ROLE = "dj_role"
    DJ_ROLE_NAME = "Molten_DJ"


class LatestActionKeys(StrEnum):
    TEXT = "text"
    PERSIST = "persist"
