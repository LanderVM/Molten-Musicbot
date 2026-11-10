import asyncio
import os
import signal

from dotenv import load_dotenv

from enums import EnvironmentKeys
from music_bot import Bot

load_dotenv()

bot = Bot()


async def main() -> None:
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    signal_installed = False
    try:
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
        signal_installed = True
    except NotImplementedError:
        # Windows console interrupts are handled by asyncio.run below.
        pass
    try:
        async with bot:
            await bot.start(os.getenv(EnvironmentKeys.DISCORD_TOKEN))
    except asyncio.CancelledError:
        pass
    finally:
        if signal_installed:
            loop.remove_signal_handler(signal.SIGTERM)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually")
