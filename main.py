# main.py

import discord
from discord.ext import commands
import asyncio
import os
import json
from keep_alive import keep_alive
from datetime import datetime

TOKEN = os.environ["DISCORD_TOKEN"]

intents = discord.Intents.all()

bot = commands.Bot(command_prefix="?", intents=intents)
log_channel_id = None
staff_role_id = None

WARNINGS_FILE = "warnings.json"
ACTIONS_FILE = "actions.json"

def load_warnings():
    if os.path.exists(WARNINGS_FILE):
        with open(WARNINGS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_warnings(warnings):
    with open(WARNINGS_FILE, "w") as f:
        json.dump(warnings, f, indent=4)

def load_actions():
    if os.path.exists(ACTIONS_FILE):
        with open(ACTIONS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_actions(data):
    with open(ACTIONS_FILE, "w") as f:
        json.dump(data, f, indent=4)

warnings_data = load_warnings()
actions_data = load_actions()

def staff_only():
    async def predicate(ctx):
        if not staff_role_id:
            await ctx.send("Staff role is not set.")
            return False
        role = discord.utils.get(ctx.guild.roles, id=staff_role_id)
        return role in ctx.author.roles
    return commands.check(predicate)

async def log_action(ctx, message, user_id=None, action_type=None):
    if log_channel_id:
        channel = bot.get_channel(log_channel_id)
        if channel:
            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            user_info = f"[User: {ctx.author} | ID: {ctx.author.id}]"
            await channel.send(f"[LOG - {timestamp}] {user_info} {message}")
    if user_id and action_type:
        guild_id = str(ctx.guild.id)
        uid = str(user_id)
        if guild_id not in actions_data:
            actions_data[guild_id] = {}
        if uid not in actions_data[guild_id]:
            actions_data[guild_id][uid] = []
        actions_data[guild_id][uid].append({
            "type": action_type,
            "by": str(ctx.author),
            "time": datetime.utcnow().isoformat(),
            "detail": message
        })
        save_actions(actions_data)

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="my creator, theofficialtruck"))
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

@bot.command()
@commands.has_permissions(administrator=True)
async def staffset(ctx, role: discord.Role):
    global staff_role_id
    staff_role_id = role.id
    await ctx.send(f"Staff role set to {role.mention}")
    await log_action(ctx, f"set staff role to {role.name} (ID: {role.id})")

@bot.command()
@commands.has_permissions(administrator=True)
async def logchannel(ctx, channel: discord.TextChannel):
    global log_channel_id
    log_channel_id = channel.id
    await ctx.send(f"Log channel set to {channel.mention}")

@bot.command()
@staff_only()
async def kick(ctx, member: discord.Member, *, reason=None):
    await member.kick(reason=reason)
    await ctx.send(f"Kicked {member.mention} for reason: {reason}")
    await log_action(ctx, f"kicked {member} for: {reason}", user_id=member.id, action_type="kick")

@bot.command()
@staff_only()
async def ban(ctx, member: discord.Member, *, reason=None):
    await member.ban(reason=reason)
    await ctx.send(f"Banned {member.mention} for reason: {reason}")
    await log_action(ctx, f"banned {member} for: {reason}", user_id=member.id, action_type="ban")

@bot.command()
@staff_only()
async def unban(ctx, user_id: int):
    user = await bot.fetch_user(user_id)
    await ctx.guild.unban(user)
    await ctx.send(f"Unbanned {user.mention}")
    await log_action(ctx, f"unbanned {user}", user_id=user.id, action_type="unban")

@bot.command()
@staff_only()
async def mute(ctx, member: discord.Member, duration: str = None, *, reason=None):
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not mute_role:
        mute_role = await ctx.guild.create_role(name="Muted")
        for channel in ctx.guild.channels:
            await channel.set_permissions(mute_role, speak=False, send_messages=False)
    await member.add_roles(mute_role)
    await ctx.send(f"Muted {member.mention} for reason: {reason}")
    await log_action(ctx, f"muted {member} for: {reason} ({duration or 'indefinitely'})", user_id=member.id, action_type="mute")
    if duration:
        seconds = convert_time(duration)
        if seconds:
            await asyncio.sleep(seconds)
            await member.remove_roles(mute_role)
            await ctx.send(f"Unmuted {member.mention} after {duration}")
            await log_action(ctx, f"{member} was automatically unmuted after {duration}", user_id=member.id, action_type="unmute")
        else:
            await ctx.send("Invalid time format. Use s, m, h, or d.")

@bot.command()
@staff_only()
async def unmute(ctx, member: discord.Member):
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if mute_role in member.roles:
        await member.remove_roles(mute_role)
        await ctx.send(f"Unmuted {member.mention}")
        await log_action(ctx, f"unmuted {member}", user_id=member.id, action_type="unmute")
    else:
        await ctx.send(f"{member.mention} is not muted.")

@bot.command()
@staff_only()
async def purge(ctx, amount: int):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"Deleted {amount} messages.", delete_after=5)
    await log_action(ctx, f"purged {amount} messages in #{ctx.channel.name}")

@bot.command()
@staff_only()
async def warn(ctx, member: discord.Member, *, reason=None):
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    if guild_id not in warnings_data:
        warnings_data[guild_id] = {}
    if user_id not in warnings_data[guild_id]:
        warnings_data[guild_id][user_id] = []
    warnings_data[guild_id][user_id].append({"reason": reason, "by": str(ctx.author), "time": datetime.utcnow().isoformat()})
    save_warnings(warnings_data)
    await ctx.send(f"{member.mention} has been warned for: {reason}")
    try:
        await member.send(f"You have been warned in {ctx.guild.name} for: {reason}")
    except:
        await log_action(ctx, f"Failed to DM warn message to {member} (ID: {member.id})")
    await log_action(ctx, f"warned {member} for: {reason}", user_id=member.id, action_type="warn")

@bot.command()
@staff_only()
async def slowmode(ctx, seconds: int):
    await ctx.channel.edit(slowmode_delay=seconds)
    await ctx.send(f"Set slowmode to {seconds} seconds.")
    await log_action(ctx, f"set slowmode to {seconds}s in #{ctx.channel.name}")

@bot.command()
@staff_only()
async def setprefix(ctx, prefix):
    bot.command_prefix = prefix
    await ctx.send(f"Prefix changed to: `{prefix}`")
    await log_action(ctx, f"changed prefix to: {prefix}")

@bot.command()
@staff_only()
async def reactionrole(ctx, message_id: int, emoji, role: discord.Role):
    channel = ctx.channel
    try:
        message = await channel.fetch_message(message_id)
        await message.add_reaction(emoji)

        @bot.event
        async def on_raw_reaction_add(payload):
            if payload.message_id == message_id and str(payload.emoji) == emoji:
                guild = discord.utils.get(bot.guilds, id=payload.guild_id)
                member = guild.get_member(payload.user_id)
                if member:
                    await member.add_roles(role)

        @bot.event
        async def on_raw_reaction_remove(payload):
            if payload.message_id == message_id and str(payload.emoji) == emoji:
                guild = discord.utils.get(bot.guilds, id=payload.guild_id)
                member = guild.get_member(payload.user_id)
                if member:
                    await member.remove_roles(role)
        await log_action(ctx, f"set up reaction role for {role.name} on message {message_id}")
    except:
        await ctx.send("Could not find message or add reaction.")

@bot.command()
async def userinfo(ctx, member: discord.Member):
    roles = ", ".join([role.name for role in member.roles if role.name != "@everyone"])
    await ctx.send(f"User: {member}\nID: {member.id}\nJoined: {member.joined_at}\nRoles: {roles}")

@bot.command()
async def serverinfo(ctx):
    await ctx.send(f"Server: {ctx.guild.name}\nID: {ctx.guild.id}\nMembers: {ctx.guild.member_count}")

@bot.command()
async def cmds(ctx):
    await ctx.send("""
Staff-only Commands:
?!kick @user <reason>
?ban @user <reason>
?unban <user_id>
?mute @user <duration> <reason>
?unmute @user
?purge <number>
?warn @user <reason>
?slowmode <seconds>
?setprefix <new prefix>
?reactionrole <message_id> <emoji> @role
?logchannel #channel
?userinfo @user
?staffset @role

General:
?serverinfo
?cmds
""")

def convert_time(time_str):
    try:
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        return int(time_str[:-1]) * units[time_str[-1]]
    except (ValueError, KeyError):
        return None

keep_alive()
bot.run(TOKEN)
