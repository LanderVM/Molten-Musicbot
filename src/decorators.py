import asyncio
import logging
from functools import wraps

from utils import Error


def debounce_action(delay: float = 0.5):
    """
    Decorator to ensure that only one action per guild can run
    within `delay` seconds. Subsequent calls return an Error.
    """

    def decorator(fn):
        @wraps(fn)
        async def wrapper(self, interaction, guild, user, *args, **kwargs):
            lock = self._action_locks[guild.id]
            if lock.locked():
                return Error("Too many button presses at once—please wait a moment.")
            await lock.acquire()

            logging.debug(f"[{guild.id}] lock acquired by {user.display_name}")
            asyncio.create_task(self._release_lock_after(lock, delay))
            return await fn(self, interaction, guild, user, *args, **kwargs)

        return wrapper

    return decorator


def ensure_voice(fn):
    """
    Decorator to run voice_precheck before the action.
    If it returns an error string, immediately return Error(err).
    """

    @wraps(fn)
    async def wrapper(self, interaction, guild, user, *args, **kwargs):
        err = await self.voice_precheck(user, guild)
        if err:
            return Error(err)
        return await fn(self, interaction, guild, user, *args, **kwargs)

    return wrapper
