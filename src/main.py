import asyncio
import os

from dotenv import load_dotenv

from enums import EnvironmentKeys
from music_bot import Bot

load_dotenv()

bot = Bot()


async def main() -> None:
    async with bot:
        await bot.start(os.getenv(EnvironmentKeys.DISCORD_TOKEN))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually")
