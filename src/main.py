import asyncio
import os

from dotenv import load_dotenv

from music_bot import Bot

load_dotenv()

bot = Bot()


async def main() -> None:
    async with bot:
        await bot.start(os.getenv("DISCORD_BOT_TOKEN"))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually")
