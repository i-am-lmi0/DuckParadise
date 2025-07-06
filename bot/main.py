import discord
from discord.ext import commands
import asyncio
import os
import json
from keep_alive import keep_alive
from datetime import datetime
import traceback

TOKEN = os.environ["DISCORD_TOKEN"]

intents = discord.Intents.all()

WARNINGS_FILE = "warnings.json"
ACTIONS_FILE = "actions.json"
CONFIG_FILE = "config.json"
REACTION_ROLE_FILE = "reaction_roles.json"
AFK_FILE = "afk.json"

def get_prefix(bot, message):
    guild_id = str(message.guild.id) if message.guild else None
    return config.get("prefixes", {}).get(guild_id, "?")

bot = commands.Bot(command_prefix=get_prefix, intents=intents)
log_channel_id = None
staff_role_id = None

def load_afk():
    if os.path.exists(AFK_FILE):
        with open(AFK_FILE, "r") as f:
            return {int(k): v for k, v in json.load(f).items()}
    return {}

def save_afk():
    with open(AFK_FILE, "w") as f:
        json.dump({str(k): v for k, v in afk_data.items()}, f, indent=4)

afk_data = load_afk()

def load_reaction_roles():
    try:
        if os.path.exists(REACTION_ROLE_FILE):
            with open(REACTION_ROLE_FILE, "r") as f:
                return {int(k): (v[0], v[1]) for k, v in json.load(f).items()}
    except Exception as e:
        print(f"Failed to load reaction roles: {e}")
    return {}

def save_reaction_roles():
    try:
        with open(REACTION_ROLE_FILE, "w") as f:
            json.dump({str(k): v for k, v in reaction_roles.items()}, f, indent=4)
    except Exception as e:
        print(f"Failed to save reaction roles: {e}")

reaction_roles = load_reaction_roles()

def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Failed to load config: {e}")
    return {}

def save_config(data):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Failed to save config: {e}")

# initialize config
config = load_config()
config.setdefault("staff_roles", {})
config.setdefault("log_channels", {})
config.setdefault("welcome_channels", {})
config.setdefault("boost_channels", {})

staff_role_id = config.get("staff_role_id")
log_channel_id = config.get("log_channel_id")

def load_warnings():
    try:
        if os.path.exists(WARNINGS_FILE):
            with open(WARNINGS_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Failed to load warnings: {e}")
    return {}

def save_warnings(warnings):
    try:
        with open(WARNINGS_FILE, "w") as f:
            json.dump(warnings, f, indent=4)
    except Exception as e:
        print(f"Failed to save warnings: {e}")

def load_actions():
    try:
        if os.path.exists(ACTIONS_FILE):
            with open(ACTIONS_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Failed to load actions: {e}")
    return {}

def save_actions(data):
    try:
        with open(ACTIONS_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Failed to save actions: {e}")

warnings_data = load_warnings()
actions_data = load_actions()

def staff_only():
    async def predicate(ctx):
        guild_id = str(ctx.guild.id)
        role_id = config.get("staff_roles", {}).get(guild_id)
        print(f"Checking staff role: guild {guild_id} role_id {role_id} for user {ctx.author}")
        if not role_id:
            await ctx.send("⚠️ Staff role is not set for this server.")
            return False
        role = discord.utils.get(ctx.guild.roles, id=role_id)
        if role:
            print(f"Found role: {role.name}, user roles: {[r.name for r in ctx.author.roles]}")
            if role in ctx.author.roles:
                return True
        await ctx.send("❌ You don't have the staff role required to run this command.")
        return False
    return commands.check(predicate)

async def log_action(ctx, message, user_id=None, action_type=None):
    try:
        guild_id = str(ctx.guild.id)
        log_channel_id = config.get("log_channels", {}).get(guild_id)

        if log_channel_id:
            channel = bot.get_channel(log_channel_id)
            if channel:
                timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
                user_info = f"[User: {ctx.author} | ID: {ctx.author.id}]"
                await channel.send(f"[LOG - {timestamp}] {user_info} {message}")

        if user_id and action_type:
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
    except Exception as e:
        print(f"Error logging action: {e}")

async def resolve_member(ctx, arg):
    try:
        return await commands.MemberConverter().convert(ctx, arg)
    except Exception:
        try:
            return await ctx.guild.fetch_member(int(arg))
        except:
            return None

@bot.command()
async def afk(ctx, *, reason="AFK"):
    user_id = ctx.author.id
    afk_data[user_id] = {"reason": reason, "time": datetime.utcnow().isoformat()}
    save_afk()
    try:
        await ctx.author.edit(nick=f"[AFK] {ctx.author.display_name}")
    except:
        pass
    await ctx.send(f"✅ {ctx.author.mention} is now AFK: {reason}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # remove afk if the user is marked as afk and sends a message
    if message.author.id in afk_data:
        del afk_data[message.author.id]
        save_afk()
        try:
            if message.author.display_name.startswith("[AFK] "):
                new_nick = message.author.display_name.replace("[AFK] ", "", 1)
                await message.author.edit(nick=new_nick)
        except:
            pass
        await message.channel.send(f"🟢 Welcome back {message.author.mention}, I’ve removed your AFK status.")

    # notify if user mentions any afk users
    notified = set()
    for user in message.mentions:
        if user.id in afk_data and user.id not in notified:
            reason = afk_data[user.id]["reason"]
            try:
                since = datetime.fromisoformat(afk_data[user.id]["time"])
                delta = datetime.utcnow() - since
                mins, secs = divmod(int(delta.total_seconds()), 60)
                hrs, mins = divmod(mins, 60)
                days, hrs = divmod(hrs, 24)
                duration = (
                    f"{days}d " if days else "" +
                    f"{hrs}h " if hrs else "" +
                    f"{mins}m " if mins else "" +
                    f"{secs}s"
                ).strip()
                await message.channel.send(
                    f"🔕 {user.display_name} is AFK: {reason} (since {duration} ago)"
                )
            except:
                await message.channel.send(f"🔕 {user.display_name} is AFK: {reason}")
            notified.add(user.id)

    await bot.process_commands(message)

@bot.command()
@staff_only()
async def testwelcome(ctx, member: discord.Member = None):
    member = member or ctx.author
    gid = str(ctx.guild.id)
    channel_id = config.get("welcome_channels", {}).get(gid)
    if not channel_id:
        return await ctx.send("⚠️ Welcome channel not set. Use `?setwelcome #channel`")
    channel = bot.get_channel(channel_id)
    if not channel:
        return await ctx.send("⚠️ Could not find welcome channel.")

    embed = discord.Embed(
        title="Welcome to Duck Paradise 🦆",
        description=(
            f"Welcome, {member.mention}!\n"
            f"You are our **{ctx.guild.member_count}th** member!\n\n"
            f"⭐ Quack in <#main-pond>\n"
            f"⭐ Equip tags in <#pond-info>\n"
            f"⭐ Boost the server and earn <@&Golden Feather> role!"
        ),
        color=discord.Color.yellow()
    )
    embed.set_image(url="https://i.imgur.com/VyH3RlX.png")
    await channel.send(embed=embed)
    await ctx.send("✅ Sent test welcome message.")

@bot.command()
@staff_only()
async def testboost(ctx, member: discord.Member = None):
    member = member or ctx.author
    gid = str(ctx.guild.id)
    channel_id = config.get("boost_channels", {}).get(gid)
    if not channel_id:
        return await ctx.send("⚠️ Boost channel not set. Use `?setboost #channel`")
    channel = bot.get_channel(channel_id)
    if not channel:
        return await ctx.send("⚠️ Could not find boost channel.")

    embed = discord.Embed(
        title="💖 Thanks for boosting!",
        description=f"{member.mention} just boosted the pond! 🌟",
        color=discord.Color.purple()
    )
    embed.set_thumbnail(url=member.avatar.url if member.avatar else "")
    await channel.send(embed=embed)
    await ctx.send("✅ Sent test boost message.")

@bot.command()
@staff_only()
async def setwelcome(ctx, channel: discord.TextChannel):
    config["welcome_channels"][str(ctx.guild.id)] = channel.id
    save_config(config)
    await ctx.send(f"✅ Welcome channel set to {channel.mention}")

@bot.command()
@staff_only()
async def setboost(ctx, channel: discord.TextChannel):
    config["boost_channels"][str(ctx.guild.id)] = channel.id
    save_config(config)
    await ctx.send(f"✅ Boost channel set to {channel.mention}")

@bot.event
async def on_member_join(member):
    guild_id = str(member.guild.id)
    channel_id = config.get("welcome_channels", {}).get(guild_id)
    if channel_id:
        channel = bot.get_channel(channel_id)
        if channel:
            embed = discord.Embed(
                title="Welcome to Duck Paradise 🦆",
                description=(
                    f"Welcome, {member.mention}!\n"
                    f"You are our **{member.guild.member_count}th** member!\n\n"
                    f"⭐ Quack in <#main-pond>\n"
                    f"⭐ Equip tags in <#pond-info>\n"
                    f"⭐ Boost the server and earn <@&Golden Feather> role!"
                ),
                color=discord.Color.yellow()
            )
            embed.set_image(url="https://media.discordapp.net/attachments/1370374741579534408/1386456926300409939/duckduckgo-welcome.gif?ex=6863a962&is=686257e2&hm=9260bcae31ef85f293dfa5ecfbc9925b5cc1f1dfa2415c3c955b9d318d6f87a7&=&width=648&height=216")
            await channel.send(embed=embed)

@bot.event
async def on_member_update(before, after):
    if before.premium_since is None and after.premium_since is not None:
        guild_id = str(after.guild.id)
        channel_id = config.get("boost_channels", {}).get(guild_id)
        if channel_id:
            channel = bot.get_channel(channel_id)
            if channel:
                embed = discord.Embed(
                    title="💖 Thanks for boosting!",
                    description=f"{after.mention} just boosted the pond! 🌟",
                    color=discord.Color.purple()
                )
                embed.set_thumbnail(url=after.avatar.url if after.avatar else "")
                await channel.send(embed=embed)

def has_higher_role(issuer, target):
    return issuer.top_role > target.top_role or issuer == issuer.guild.owner
    
def check_target_permission(ctx, member: discord.Member):
    if member == ctx.author:
        return "❌ You can't perform this action on yourself."
    if member == ctx.guild.owner:
        return "❌ You can't perform this action on the server owner."
    if ctx.author.top_role <= member.top_role and ctx.author != ctx.guild.owner:
        return "❌ You can't perform this action on someone with equal or higher role."
    return None

@bot.event
async def on_ready():
    for guild in bot.guilds:
        gid = str(guild.id)
        if "staff_roles" in config and gid in config["staff_roles"]:
            print(f"[Config] Staff role for {guild.name}: {config['staff_roles'][gid]}")
        if "log_channels" in config and gid in config["log_channels"]:
            print(f"[Config] Log channel for {guild.name}: {config['log_channels'][gid]}")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name="theofficialtruck")
    )
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Missing arguments. Usage: `{ctx.command.name} {ctx.command.signature}`")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("❓ Invalid command. Use `?cmds` to see available commands.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("⚠️ Invalid argument type. Please check your input.")
    else:
        await ctx.send("❗ An unexpected error occurred while processing the command.")
        print("--- Traceback Start ---")
        traceback.print_exception(type(error), error, error.__traceback__)
        print("--- Traceback End ---")

@bot.command()
async def cmds(ctx):
    embed = discord.Embed(title="Command List", color=discord.Color.blue())
    embed.add_field(
        name="Staff-only Commands",
        value="""
?kick @user <reason>
?ban @user <reason>
?unban <user_id>
?mute @user <duration> <reason>
?unmute @user
?purge <number>
?warn @user <reason>
?clearwarns @user
?slowmode <seconds>
?setprefix <new prefix>
?reactionrole <message_id> <emoji> @role
?logchannel #channel
?userinfo @user
?staffset @role
?setwelcome #channel
?setboost #channel
?testwelcome
?testwelcome @user
?testboost
?testboost @user
        """,
        inline=False
    )
    embed.add_field(
        name="General Commands",
        value="""
?serverinfo
?cmds
?staffget
?afk <reason>
        """,
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command()
async def staffset(ctx, role: discord.Role):
    if ctx.author != ctx.guild.owner:
        return await ctx.send("❌ Only the server owner can set the staff role.", delete_after=7)
    guild_id = str(ctx.guild.id)
    config.setdefault("staff_roles", {})
    config["staff_roles"][guild_id] = role.id
    save_config(config)
    await ctx.send(f"✅ Staff role set to {role.mention}", delete_after=7)
    await log_action(ctx, f"Set staff role to {role.name} (ID: {role.id})")
    
@bot.command()
async def staffget(ctx):
    guild_id = str(ctx.guild.id)
    role_id = config.get("staff_roles", {}).get(guild_id)
    if not role_id:
        return await ctx.send("❌ No staff role has been set for this server.", delete_after=7)
    role = discord.utils.get(ctx.guild.roles, id=role_id)
    if role:
        await ctx.send(f"Staff role is set to {role.mention}", delete_after=7)
    else:
        await ctx.send("⚠️ The saved staff role ID does not exist anymore. Please re-set it using `?staffset @role`.", delete_after=7)

@bot.command()
@staff_only()
async def logchannel(ctx, channel: discord.TextChannel):
    guild_id = str(ctx.guild.id)
    if "log_channels" not in config:
        config["log_channels"] = {}
    config["log_channels"][guild_id] = channel.id
    save_config(config)
    await ctx.send(f"✅ Log channel set to {channel.mention} for this server.", delete_after=7)
    await log_action(ctx, f"Set log channel to {channel.mention}")

@bot.command()
@staff_only()
async def kick(ctx, user: str, *, reason: str = "No reason provided"):
    member = await resolve_member(ctx, user)
    if not member:
        return await ctx.send("❌ Could not find that user.")
    err = check_target_permission(ctx, member)
    if err:
        return await ctx.send(err)
    try:
        await member.kick(reason=f"{reason} (by {ctx.author})")
        await ctx.send(f"Kicked {member.mention}")
        await log_action(ctx, f"kicked {member} for: {reason}", user_id=member.id, action_type="kick")
    try:
        await member.send(f"🚫 You have been kicked from **{ctx.guild.name}** for: {reason}")
    except:
        await log_action(ctx, f"Failed to DM kick message to {member} (ID: {member.id})")

    except Exception as e:
        await ctx.send("❌ Failed to kick the user.")
        print(f"[Kick Error] {e}")

@bot.command()
@staff_only()
async def ban(ctx, user: str, *, reason: str = "No reason provided"):
    member = await resolve_member(ctx, user)
    if not member:
        return await ctx.send("❌ Could not find that user.", delete_after=7)

    err = check_target_permission(ctx, member)
    if err:
        return await ctx.send(err, delete_after=7)

    try:
        try:
            await member.send(f"⛔ You have been banned from **{ctx.guild.name}** for: {reason}")
        except:
            await log_action(ctx, f"Failed to DM ban message to {member} (ID: {member.id})")

        await member.ban(reason=f"{reason} (by {ctx.author})")
        await ctx.send(f"{member} has been banned.", delete_after=7)
        await log_action(ctx, f"banned {member} for: {reason}", user_id=member.id, action_type="ban")
    except Exception as e:
        await ctx.send("❌ Failed to ban the user.", delete_after=7)
        print(f"[Ban Error] {e}")

@bot.command()
@staff_only()
async def unban(ctx, *, user: str):
    try:
        user_id = int(user.strip("<@!>"))
        user_obj = await bot.fetch_user(user_id)
        await ctx.guild.unban(user_obj)
        await ctx.send(f"✅ Unbanned {user_obj.mention}", delete_after=7)
        await log_action(ctx, f"unbanned {user_obj}", user_id=user_obj.id, action_type="unban")
    except Exception as e:
        await ctx.send("❌ Failed to unban the user.")
        print(f"[Unban Error] {e}")

@bot.command()
@staff_only()
async def mute(ctx, user: str, duration: str = None, *, reason: str = "No reason provided"):
    member = await resolve_member(ctx, user)
    if not member:
        return await ctx.send("❌ Could not find that user.")

    # Permission checks
    if member == ctx.author:
        return await ctx.send("❌ You can't mute yourself.")
    if member == ctx.guild.owner:
        return await ctx.send("❌ You can't mute the server owner.")
    if ctx.author.top_role <= member.top_role and ctx.author != ctx.guild.owner:
        return await ctx.send("❌ You can't mute someone with an equal or higher role than you.")

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
async def unmute(ctx, *, user: str):
    member = await resolve_member(ctx, user)
    if not member:
        return await ctx.send("❌ Could not find that user.")

    err = check_target_permission(ctx, member)
    if err:
        return await ctx.send(err)

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
    await ctx.send(f"Deleted {amount} messages.", delete_after=7)
    await log_action(ctx, f"purged {amount} messages in #{ctx.channel.name}")

@bot.command()
@staff_only()
async def warn(ctx, user: str, *, reason: str = "No reason provided"):
    member = await resolve_member(ctx, user)
    if not member:
        return await ctx.send("❌ Could not find that user.")
    err = check_target_permission(ctx, member)
    if err:
        return await ctx.send(err)
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
async def clearwarns(ctx, user: str):
    member = await resolve_member(ctx, user)
    if not member:
        return await ctx.send("❌ Could not find that user.")

    guild_id = str(ctx.guild.id)
    user_id = str(member.id)

    if guild_id in warnings_data and user_id in warnings_data[guild_id]:
        del warnings_data[guild_id][user_id]
        save_warnings(warnings_data)
        await ctx.send(f"✅ Cleared all warnings for {member.mention}")
        await log_action(ctx, f"Cleared all warnings for {member}", user_id=member.id, action_type="clearwarns")
    else:
        await ctx.send(f"ℹ️ {member.mention} has no warnings.")

@bot.command()
@staff_only()
async def slowmode(ctx, seconds: int):
    await ctx.channel.edit(slowmode_delay=seconds)
    await ctx.send(f"Set slowmode to {seconds} seconds.", delete_after=7)
    await log_action(ctx, f"set slowmode to {seconds}s in #{ctx.channel.name}")

@bot.command()
async def setprefix(ctx, new_prefix):
    if not ctx.guild:
        return await ctx.send("❌ This command can't be used in DMs.", delete_after=7)

    staff_role_id = config.get("staff_roles", {}).get(str(ctx.guild.id))
    if staff_role_id is None:
        return await ctx.send("❌ Staff role not set for this server.", delete_after=7)
    if staff_role_id not in [role.id for role in ctx.author.roles]:
        return await ctx.send("❌ You do not have permission to use this command.", delete_after=7)

    guild_id = str(ctx.guild.id)
    config.setdefault("prefixes", {})[guild_id] = new_prefix
    save_config(config)
    await ctx.send(f"✅ Prefix updated to `{new_prefix}`")

@bot.command()
@staff_only()
async def reactionrole(ctx, message_id: int, emoji, role: discord.Role):
    try:
        message = await ctx.channel.fetch_message(message_id)
    except discord.NotFound:
        return await ctx.send("❌ Message not found. Please check the message ID.", delete_after=7)
    except discord.Forbidden:
        return await ctx.send("❌ I don't have permission to fetch that message.", delete_after=7)
    except discord.HTTPException as e:
        return await ctx.send(f"❌ Failed to fetch the message: {e}", delete_after=7)

    try:
        await message.add_reaction(emoji)
    except discord.HTTPException:
        return await ctx.send("❌ Failed to add the emoji reaction. Make sure it's a valid emoji.")

    reaction_roles[message_id] = (emoji, role.id)
    save_reaction_roles()

    await ctx.send(f"✅ Reaction role set: {emoji} → {role.mention}", delete_after=7)
    await log_action(ctx, f"Set reaction role: {emoji} → {role.name} on message {message_id}")

@bot.event
async def on_raw_reaction_add(payload):
    data = reactionrole.get(payload.message_id)
    if not data or str(payload.emoji) != data[0]:
        return
    guild = discord.utils.get(bot.guilds, id=payload.guild_id)
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    role = discord.utils.get(guild.roles, id=data[1])
    if member and role:
        await member.add_roles(role)

@bot.event
async def on_raw_reaction_remove(payload):
    data = reaction_roles.get(payload.message_id)
    if not data or str(payload.emoji) != data[0]:
        return
    guild = discord.utils.get(bot.guilds, id=payload.guild_id)
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    role = discord.utils.get(guild.roles, id=data[1])
    if member and role:
        await member.remove_roles(role)

@bot.command()
@staff_only()
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author

    try:
        roles = [role.name for role in member.roles if role.name != "@everyone"]
        roles_string = ", ".join(roles) if roles else "None"

        joined_at = member.joined_at.strftime("%B %d, %Y at %I:%M %p UTC") if member.joined_at else "Unknown"
        created_at = member.created_at.strftime("%B %d, %Y at %I:%M %p UTC")

        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        warnings = len(warnings_data.get(guild_id, {}).get(user_id, []))

        embed = discord.Embed(
            title=f"Complete User Info - {member}",
            description=f"User data for {member.mention}",
            color=discord.Color.blurple()
        )

        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)

        # basic info
        embed.add_field(name="Username", value=f"{member.name}#{member.discriminator}", inline=True)
        embed.add_field(name="Display Name", value=member.display_name, inline=True)
        embed.add_field(name="User ID", value=member.id, inline=True)

        # dates
        embed.add_field(name="Account Created", value=created_at, inline=False)
        embed.add_field(name="Joined Server", value=joined_at, inline=False)

        # roles
        embed.add_field(name="Roles", value=roles_string, inline=False)
        embed.add_field(name="Top Role", value=member.top_role.name if member.top_role else "None", inline=True)
        embed.add_field(name="Hoist Role", value=member.top_role.name if member.top_role and member.top_role.hoist else "None", inline=True)

        # status & activity
        embed.add_field(name="Status", value=str(member.status).capitalize(), inline=True)
        embed.add_field(name="Desktop Status", value=str(member.desktop_status).capitalize(), inline=True)
        embed.add_field(name="Mobile Status", value=str(member.mobile_status).capitalize(), inline=True)
        embed.add_field(name="Web Status", value=str(member.web_status).capitalize(), inline=True)

        # activity (if any)
        activity = member.activity
        if activity:
            embed.add_field(name="Activity Type", value=str(activity.type).split('.')[-1].capitalize(), inline=True)
            embed.add_field(name="Activity Name", value=activity.name, inline=True)
            if getattr(activity, 'details', None):
                embed.add_field(name="Activity Details", value=activity.details, inline=True)
            if getattr(activity, 'state', None):
                embed.add_field(name="Activity State", value=activity.state, inline=True)

        # other
        embed.add_field(name="Is Bot", value="✅ Yes" if member.bot else "❌ No", inline=True)
        embed.add_field(name="Is Timed Out?", value="✅ Yes" if getattr(member, "timed_out", False) else "❌ No", inline=True)
        embed.add_field(name="Pending?", value="✅ Yes" if getattr(member, "pending", False) else "❌ No", inline=True)
        embed.add_field(name="Boosting Since", value=member.premium_since.strftime("%B %d, %Y at %I:%M %p UTC") if member.premium_since else "Not boosting", inline=False)

        # permissions
        permissions = [perm[0].replace('_', ' ').title() for perm in member.guild_permissions if perm[1]]
        permissions_str = ', '.join(permissions) if permissions else "None"
        embed.add_field(name="Guild Permissions", value=permissions_str, inline=False)

        # list individual warnings if any
        user_warnings = warnings_data.get(guild_id, {}).get(user_id, [])
        if user_warnings:
            for i, w in enumerate(user_warnings[:3], 1):
                reason = w.get("reason", "No reason")
                by = w.get("by", "Unknown")
                time = w.get("time", "Unknown")
                embed.add_field(
                    name=f"⚠️ Warning {i}",
                    value=f"**By:** {by}\n**Reason:** {reason}\n**Time:** <t:{int(datetime.fromisoformat(time).timestamp())}:R>",
                    inline=False
                )

        # avatar banner
        banner_url = ""
        if hasattr(member, "banner") and member.banner:
            try:
                banner_url = member.banner.url
            except Exception:
                banner_url = ""

        if banner_url:
            embed.set_image(url=banner_url)

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send("❗ An error occurred while fetching user info.")
        print(f"[UserInfo Error] {e}")

@bot.command()
async def serverinfo(ctx):
    await ctx.send(f"Server: {ctx.guild.name}\nID: {ctx.guild.id}\nMembers: {ctx.guild.member_count}")

def convert_time(time_str):
    try:
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        return int(time_str[:-1]) * units[time_str[-1]]
    except (ValueError, KeyError):
        return None

if __name__ == '__main__':
    import tempfile
    import shutil

    def test_convert_time():
        assert convert_time("10s") == 10
        assert convert_time("2m") == 120
        assert convert_time("1h") == 3600
        assert convert_time("1d") == 86400
        assert convert_time("5x") is None
        assert convert_time("abc") is None

    def test_warning_file_rw():
        backup = shutil.copy(WARNINGS_FILE, WARNINGS_FILE + ".bak") if os.path.exists(WARNINGS_FILE) else None
        test_data = {"123": {"456": [{"reason": "test", "by": "tester", "time": "now"}]} }
        save_warnings(test_data)
        loaded = load_warnings()
        assert loaded == test_data
        if backup:
            shutil.move(WARNINGS_FILE + ".bak", WARNINGS_FILE)
        else:
            os.remove(WARNINGS_FILE)

    def test_actions_file_rw():
        backup = shutil.copy(ACTIONS_FILE, ACTIONS_FILE + ".bak") if os.path.exists(ACTIONS_FILE) else None
        test_data = {"789": {"101": [{"type": "test", "by": "tester", "time": "now", "detail": "some detail"}]} }
        save_actions(test_data)
        loaded = load_actions()
        assert loaded == test_data
        if backup:
            shutil.move(ACTIONS_FILE + ".bak", ACTIONS_FILE)
        else:
            os.remove(ACTIONS_FILE)

    test_convert_time()
    test_warning_file_rw()
    test_actions_file_rw()
    print("All tests passed!")

keep_alive()
bot.run(TOKEN)