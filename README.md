# Molten Musicbot

Molten is a lightweight music bot built on top of Lavalink v4, designed to provide high-performance and low-latency music playback. This bot utilizes Wavelink to interact with Lavalink and play music efficiently.

## Prerequisites

Before you begin, ensure you have the following installed on your machine:

- [Python 3.11 or later](https://www.python.org/downloads/)
- A Discord bot token (which you can get from the [Discord Developer Portal](https://discord.com/developers/applications))
- [Lavalink server](<(https://lavalink.dev/getting-started).>) You can host your own or use a public one. A free list of Lavalink servers can be found [here](https://lavalink.darrennathanael.com/NoSSL/lavalink-without-ssl/).

---

## Getting Started

Follow these steps to set up Molten:

### 1. Clone the repository

First, clone the repository to your local machine.

```bash
git clone https://github.com/yourusername/molten-musicbot.git
cd molten-musicbot
```

### 2. Install Required Packages

Now, install the required Python packages using **pip**. Run the following command:

```bash
pip install -r requirements.txt
```

### 3. Set Up Environment Variables

Copy the `.env.example` file and rename it to `.env`. This file contains the environment variables used by the bot.

### 4. Find Your Discord Bot Token

To run the bot, you’ll need a Discord bot token. Follow these steps to get your bot token:

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Select your application (or create a new one).
3. In the "Bot" section, click on "Reset Token" under the "TOKEN" field. And save the token somewhere safe.

### 5. Edit `.env` File

Open the `.env` file in a text editor and add your Discord bot token. The file should look something like this:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
LAVALINK_HOST=localhost
LAVALINK_PORT=2333
LAVALINK_PASSWORD=youshallnotpass
```

Replace `your_discord_bot_token_here` with the bot token you obtained in step 5. Make sure to set the Lavalink server details correctly.

### 7. Run the Bot

Finally, run the bot using the following command:

```bash
python src/main.py
```

If everything is set up correctly, your bot should be online and ready to start playing music in your Discord server.

---

## Additional Information

### Troubleshooting

- If you get errors related to missing dependencies, make sure you have all packages installed from `requirements.txt`.
- Ensure your Lavalink server is running and accessible.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
