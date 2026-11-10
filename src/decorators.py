import time
from functools import wraps

from utils import Error, dj_permission_error


def debounce_action(delay: float = 0.5):
    """Serialize guild mutations, with a separate minimum request interval."""

    def decorator(fn):
        @wraps(fn)
        async def wrapper(self, interaction, guild, user, *args, **kwargs):
            if guild is None:
                return Error("This action can only be used in a server.")
            lock = self._action_locks[guild.id]
            now = time.monotonic()
            if lock.locked() or now < self._action_cooldowns.get(guild.id, 0):
                return Error("Too many button presses at once—please wait a moment.")
            async with lock:
                self._action_cooldowns[guild.id] = now + delay
                return await fn(self, interaction, guild, user, *args, **kwargs)

        return wrapper

    return decorator


def require_dj(fn):
    @wraps(fn)
    async def wrapper(self, interaction, guild, user, *args, **kwargs):
        err = dj_permission_error(guild, user, self.setup_channels)
        if err:
            return Error(err)
        return await fn(self, interaction, guild, user, *args, **kwargs)

    return wrapper


def ensure_voice(fn):
    """Authorize and check voice state inside the guild mutation lock."""

    @require_dj
    @wraps(fn)
    async def wrapper(self, interaction, guild, user, *args, **kwargs):
        err = await self.voice_precheck(user, guild)
        if err:
            return Error(err)
        return await fn(self, interaction, guild, user, *args, **kwargs)

    return wrapper
