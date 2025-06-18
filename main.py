# main.py

import discord
from discord.ext import commands
import os
from keep_alive import keep_alive

TOKEN = os.environ["DISCORD_TOKEN"]

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="?", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

@bot.command()
async def ping(ctx):
    await ctx.send("Pong")

# start web server
keep_alive()

# start bot
bot.run(TOKEN)
