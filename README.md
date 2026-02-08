# Molten Musicbot

Molten is a lightweight music bot built on top of Lavalink v4, designed to provide high-performance and low-latency music playback. This bot utilizes Wavelink to interact with Lavalink and play music efficiently.

## Example

![Molten-Example-Small](https://github.com/user-attachments/assets/19ea1dd8-efcb-4b5d-b28e-e002042e8171)

---

## Getting Started

Molten Musicbot supports two ways to run the bot:

- **[Docker Setup](#docker-setup-recommended-for-beginners)** → easiest, includes Lavalink automatically
- **[Manual Setup](#manual-setup-recommended-for-advanced-users)** → for users who already host their own Lavalink

---

## Docker Setup (Recommended for Beginners)

### Prerequisites

Before you begin, ensure you have the following installed on your machine:

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)

### 1. Clone the repository

First, clone the repository to your local machine.

```bash
git clone https://github.com/LanderVM/Molten-Musicbot.git
cd Molten-Musicbot
```

### 2. Set Up Environment Variables

Copy the `.env.example` file and rename it to `.env`.

### 3. Find Your Discord Bot Token

To run the bot, you’ll need a Discord bot token. Follow these steps to get your bot token:

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Select your application (or create a new one).
3. In the "Bot" section, click on "Reset Token" under the "TOKEN" field. And save the token somewhere safe.
4. Scroll down to the "Privileged Gateway Intents" section and enable the following:
   - **Server Members Intent**
   - **Message Content Intent**
5. Save the changes.
6. In the Installation section, make sure to add the bot to your server with the following settings and use the Install Link to invite the bot to your server:
   ![DiscordInstallation](https://github.com/user-attachments/assets/5f1dd3f6-e8a4-45dc-8dfe-e25a3615f9b1)

### 4. Edit `.env` File

Open the `.env` file in a text editor and add your Discord bot token. Update the DISCORD_BOT_TOKEN to look something like this:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
```

Replace `your_discord_bot_token_here` with the bot token you obtained in step 3.

### 5. Run the Bot with Docker

```bash
docker-compose up -d
```

The bot and Lavalink will start automatically.

---

## Manual Setup (Recommended for Advanced Users)

Use this method if you already have a **Lavalink V4 server** or want to run the bot without Docker.

### Prerequisites

Before you begin, ensure you have the following installed on your machine:

- [Python 3.11 or later](https://www.python.org/downloads/)
- Lavalink **V4** server. You can [host your own Lavalink V4](https://lavalink.dev/getting-started) or [use a public one](https://lavalink.darrennathanael.com/NoSSL/lavalink-without-ssl/).

### [Run steps 1-3 from Docker Setup first.](#docker-setup-recommended-for-beginners)

### 4. Edit `.env` File

Open the `.env` file in a text editor and add your Discord bot token. Update the following variables:

```env
DISCORD_BOT_TOKEN=your_discord_bot_token_here
LAVALINK_HOST=localhost
LAVALINK_PORT=2333
LAVALINK_PASSWORD=youshallnotpass
SSL_ENABLED=false
```

Replace `your_discord_bot_token_here` with the bot token you obtained in step 3. Make sure to set the Lavalink server details correctly.

### 5. Install Required Packages

```bash
pip install -r requirements.txt
```

### 6. Run the Bot

```bash
python src/main.py
```

If everything is set up correctly, your bot should be online and ready to start playing music in your Discord server.

---

## Usage

In your Discord server, you can use the following commands to control the bot:

- `/setup` to create a new song request channel. In the song request channel you can just type any message or url and the bot will find the song and play it.

- `/help` to get a list of available commands.

## Additional Information

### Troubleshooting

- If the bot can’t play songs from certain sources anymore, but could play them before, try repulling the Docker image with `docker-compose pull` and then restart the bot using `docker-compose up -d`.
- Make sure you are connected to a voice channel before trying to play music.
- Ensure your Lavalink V4 server is running and accessible.
- If you get errors related to missing dependencies, make sure you have all packages installed from `requirements.txt`.

---

## Permissions

This bot requires the following permissions for full functionality: `Connect`, `Embed Links`, `Manage Channels`, `Manage Messages`, `Manage Roles`, `Send Messages`, `Speak`, and `View Channels`.

> **Note:**
>
> - `Manage Channels` is only needed when running the `/setup` command.
> - `Manage Roles` is only needed for the `/create_dj` and `/remove_dj` commands.
>
> After using those commands, you can remove those permissions if you’d like.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
