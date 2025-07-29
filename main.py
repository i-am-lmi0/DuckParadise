import sys, types
sys.modules["audioop"] = types.ModuleType("audioop")  # Prevent audioop errors
print("audioop monkey-patched")

import os, asyncio, random, traceback, threading
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from duckquiz_questions import questions
import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
from discord import ButtonStyle, Interaction
from flask import Flask
import aiohttp
from discord.ext.commands import cooldown, BucketType
from pytz import UTC
from collections import defaultdict
import time
from dateutil import parser
from discord import ui

# 1. SETUP ====================================================
TOKEN = os.environ["DISCORD_TOKEN"]
mongo = AsyncIOMotorClient(os.getenv("MONGO_URI"))
db = mongo["discord_bot"]
settings_col = db["guild_settings"]
logs_col = db["logs"]
economy_col = db["economy"]
mod_col = db["moderation"]
afk_col = db["afk"]
vanity_col = db["vanityroles"]
sticky_col = db["stickynotes"]
reaction_col = db["reactionroles"]
shop_col = db["shop"]
welcome_col = db["welcome"]
boost_col = db["boost"]
quiz_col = db['quiz']

print("Top of main.py reached")

fishes = [            # for economy game
    ("🦐 Shrimp", 100),
    ("🐟 Fish", 200),
    ("🐠 Tropical Fish", 300),
    ("🦑 Squid", 400),
    ("🐡 Pufferfish", 500)
]

ALLOWED_DUCK_CHANNELS = [1370374736814669845, 1374442889710407741] # for ?duck command

PAWAN_API_KEY = os.environ.get("PAWAN_API_KEY")

ROLE_ID = 1396526875987148982      # for the .duckquiz
QUIZ_CHANNEL = 1370374735594258558
NUM_Q = 10
PASS_PCT = 80.0

intents = discord.Intents.all()

async def get_prefix(bot, message):
    if not message.guild:
        return "?"
    doc = await settings_col.find_one({"guild": str(message.guild.id)})
    return doc.get("prefix", "?") if doc else "?"

bot = commands.Bot(command_prefix=get_prefix, intents=intents)

@bot.event
async def on_guild_join(guild):
    await settings_col.update_one(
        {"guild": str(guild.id)},
        {"$setOnInsert": {"prefix": "?"}},
        upsert=True
    )

bot_locks = {}

@bot.check
async def global_lock_check(ctx):
    # Always allow the override command to run
    if ctx.command.name == "override":
        return True

    if bot_locks.get(str(ctx.guild.id)):
        await ctx.send("🔒 The bot is locked — only `override` by theofficialtruck works.")
        return False
    return True
    
@bot.event
async def on_disconnect():
    print("⚠️ Bot disconnected from Discord. Will attempt reconnect soon.")

# 2. UTIL FUNCTIONS ===========================================
def staff_only():
    async def predicate(ctx):
        guild_id = str(ctx.guild.id)
        settings = await settings_col.find_one({"guild": guild_id})
        if not settings or "staff_role" not in settings:
            return False
        role = discord.utils.get(ctx.guild.roles, id=settings["staff_role"])
        return bool(role and role in ctx.author.roles)
    return commands.check(predicate)
    
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        return await ctx.send("❌ You don't have permission to use this command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send("⚠️ Missing arguments for this command.")
    elif isinstance(error, commands.CommandNotFound):
        return await ctx.send("⚠️ That command doesn't exist.")
    else:
        print(f"Unexpected error: {error}")

async def get_user(guild_id, user_id):
    key = f"{guild_id}-{user_id}"
    u = await economy_col.find_one({"_id": key})
    if not u:
        await economy_col.insert_one({"_id": key, "guild": str(guild_id), "user": str(user_id), "wallet": 0, "bank": 0, "inventory": []})
        u = await economy_col.find_one({"_id": key})
    return u

def convert_time(s):
    try:
        return int(s[:-1]) * {"s":1,"m":60,"h":3600,"d":86400}[s[-1]]
    except Exception:
        return None

async def resolve_member(ctx, arg):
    try:
        return await commands.MemberConverter().convert(ctx, arg)
    except Exception:
        try:
            return await ctx.guild.fetch_member(int(arg.strip("<@!>")))
        except Exception:
            return None

def check_target_permission(ctx, member: discord.Member):
    if member == ctx.author:
        return "❌ You can't perform this action on yourself."
    if member == ctx.guild.owner:
        return "❌ You can't perform this action on the server owner."
    if ctx.author.top_role <= member.top_role and ctx.author != ctx.guild.owner:
        return "❌ You can't perform this action on someone with an equal or higher role."
    return None

async def log_action(ctx, message, user_id=None, action_type=None):
    try:
        guild_id = str(ctx.guild.id)
        settings = await settings_col.find_one({"guild": guild_id})
        log_channel_id = settings.get("log_channel") if settings else None

        if log_channel_id:
            log_channel = bot.get_channel(log_channel_id)
            if log_channel:
                embed = discord.Embed(
                    title="📋 Moderation Log",
                    description=message,
                    color=discord.Color.dark_blue(),
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text=f"By {ctx.author} • {ctx.author.id}")
                await log_channel.send(embed=embed)

        if user_id and action_type:
            log_doc = {
                "guild": guild_id,
                "user_id": str(user_id),
                "action": action_type,
                "by": {"name": str(ctx.author), "id": str(ctx.author.id)},
                "message": message,
                "timestamp": datetime.utcnow().isoformat()
            }
            await logs_col.insert_one(log_doc)
    except Exception as e:
        print(f"[log_action ERROR] {e}")

@tasks.loop(minutes=1)
async def check_expired_mutes():
    now = datetime.now(timezone.utc)
    async for doc in mod_col.find({"muted_until": {"$exists": True}}):
        try:
            mute_until = datetime.fromisoformat(doc["muted_until"])
            if mute_until <= now:
                guild = bot.get_guild(int(doc["guild"]))
                if not guild:
                    continue
                member = guild.get_member(int(doc["user"]))
                if not member:
                    continue
                mute_role = discord.utils.get(guild.roles, name="Muted")
                if mute_role and mute_role in member.roles:
                    await member.remove_roles(mute_role, reason="Mute expired")
                    await log_action(ctx=None, message=f"Auto-unmuted {member}", user_id=member.id, action_type="unmute")

                await mod_col.update_one(
                    {"guild": doc["guild"], "user": doc["user"]},
                    {"$unset": {"muted_until": ""}}
                )
        except Exception as e:
            print(f"[Auto-unmute error] {e}")

@check_expired_mutes.before_loop
async def before_unmute_loop():
    await bot.wait_until_ready()

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="theofficialtruck"))
    print(f"🎉 Bot ready — Logged in as {bot.user}")

    # Only insert shop items once
    existing = await shop_col.count_documents({})
    if existing == 0:
        initial_items = [
            {"_id": "fishing rod", "price": 150, "description": "🎣 Catch fish to earn coins."},
            {"_id": "laptop", "price": 500, "description": "💻 Needed to work certain jobs."}
        ]
        await shop_col.insert_many(initial_items)
        print("✅ Shop items added.")

async def ask_duck_gpt(prompt: str) -> str:
    url = "https://api.pawan.krd/v1/chat/completions"  # or "/cosmosrp/v1/chat/completions" if needed
    headers = {
        "Authorization": f"Bearer {PAWAN_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "pai-001-beta",  # Use a supported Pawan model
        "messages": [
            {
                "role": "system",
                "content": "You are a smart duck that replies in a funny and helpful duck-themed way."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.7,
        "max_tokens": 150
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as resp:
            if resp.status != 200:
                text = await resp.text()
                return f"Quack? (error {resp.status}: {text})"
            result = await resp.json()
            choice = result.get("choices", [])
            if not choice:
                return "Quack?"
            msg_content = choice[0].get("message", {}).get("content") or choice[0].get("text")
            return msg_content.strip() if msg_content else "Quack?"
    
# Store last trigger time per channel
last_sticky_trigger = defaultdict(float)

# Keep track of last sticky message ID per channel
last_sticky_msg = {}

@bot.event
async def on_message(message):
    if message.author.bot:
        return

# PAWAN CONFIG \\\\\\\\\\\\\\
    if bot.user in message.mentions:
        await message.channel.typing()
        reply = await ask_duck_gpt(message.content)
        await message.reply(reply)
        
# STICKYNOTE CONFIG \\\\\\\\\\\\
    doc = await sticky_col.find_one({
        "guild": str(message.guild.id),
        "channel": str(message.channel.id)
    })
    if doc:
        now = time.time()
        if now - last_sticky_trigger[message.channel.id] >= 3:
            last_sticky_trigger[message.channel.id] = now
            try:
                # Delete old sticky message if exists
                old_id = last_sticky_msg.get(message.channel.id)
                if old_id:
                    old = await message.channel.fetch_message(old_id)
                    await old.delete()
                # Send and store new sticky
                embed = discord.Embed(description=doc["text"], color=discord.Color.burple())
                sent = await message.channel.send(embed=embed)
                last_sticky_msg[message.channel.id] = sent.id
            except Exception as e:
                print(f"[sticky repost error] {e}")

# AFK CONFIG \\\\\\\\
     # check mentions
    for user in message.mentions:
        doc = await afk_col.find_one({"_id": f"{message.guild.id}-{user.id}"})
        if doc:
            reason = doc.get("reason", "AFK")
            timestamp = doc.get("timestamp")
            if timestamp:
                dt = parser.isoparse(timestamp)
                elapsed = datetime.now(timezone.utc) - dt.replace(tzinfo=timezone.utc)
                mins = int(elapsed.total_seconds() // 60)
                hours = mins // 60
                mins %= 60
                time_str = f"{hours}h {mins}m ago" if hours else f"{mins} minutes ago"
                await message.channel.send(f"📨 {user.display_name} is AFK ({reason}) — set {time_str}.")
            else:
                await message.channel.send(f"📨 {user.display_name} is AFK: {reason}")

    # remove AFK status if the user talks
    afk_key = f"{message.guild.id}-{message.author.id}"
    if await afk_col.find_one({"_id": afk_key}):
        await afk_col.delete_one({"_id": afk_key})
        await message.channel.send(f"✅ Welcome back, {message.author.mention}! AFK removed.")

    await bot.process_commands(message)
    await sticky_col.create_index([("guild", 1), ("channel", 1)], unique=True)
        
# 3. COMMANDS \\\\\\\\
@bot.command()
async def staffset(ctx, role: discord.Role):
    if ctx.author != ctx.guild.owner:
        return await ctx.send("❌ Only the server owner can set the staff role.")

    await settings_col.update_one(
        {"guild": str(ctx.guild.id)},
        {"$set": {"staff_role": role.id}},
        upsert=True
    )

    await ctx.send(f"✅ Staff role set to {role.mention}")

@bot.command()
@staff_only()
async def staffget(ctx):
    doc = await settings_col.find_one({"guild": str(ctx.guild.id)})
    role = ctx.guild.get_role(doc.get("staff_role")) if doc else None
    if role:
        await ctx.send(f"ℹ️ Staff role is {role.mention}.")
    else:
        await ctx.send("⚠️ No staff role is currently set.")

@bot.command()
@staff_only()
async def vanityroles(ctx, role: discord.Role, log_channel: discord.TextChannel, *, keyword: str):
    guild = str(ctx.guild.id)
    await vanity_col.update_one(
        {"guild": guild},
        {"$set": {"role": role.id, "log": log_channel.id, "keyword": keyword, "users": []}},
        upsert=True
    )
    await ctx.send(f"✅ Vanity role set for '{keyword}' → {role.mention}")

@bot.command()
@staff_only()
async def promoters(ctx):
    data = await vanity_col.find_one({"guild": str(ctx.guild.id)})
    users = data.get("users", []) if data else []
    mentions = [ctx.guild.get_member(uid).mention for uid in users if ctx.guild.get_member(uid)]
    await ctx.send(embed=discord.Embed(
        title="📢 Current Promoters",
        description="\n".join(mentions) or "None",
        color=discord.Color.blue()
    ))

@bot.command()
@staff_only()
async def resetpromoters(ctx):
    guild = str(ctx.guild.id)
    data = await vanity_col.find_one({"guild": guild})
    if not data:
        return await ctx.send("❌ No vanity config set.")

    await ctx.send("⚠️ Type exactly:\n`I confirm I want to reset all the promoters.`")
    try:
        msg = await bot.wait_for("message", check=lambda m: m.author == ctx.author and m.channel == ctx.channel, timeout=30)
    except asyncio.TimeoutError:
        return await ctx.send("❌ Timeout — cancelled.")
    
    if msg.content.strip() != "I confirm I want to reset all the promoters.":
        return await ctx.send("❌ Confirmation failed — cancelled.")

    r = ctx.guild.get_role(data["role"])
    removed = 0
    for uid in data["users"]:
        m = ctx.guild.get_member(uid)
        if m and r in m.roles:
            await m.remove_roles(r, reason="reset promoters")
            removed += 1

    await vanity_col.update_one({"guild": guild}, {"$set": {"users": []}})
    await ctx.send(embed=discord.Embed(
        title="🔁 Promoters Reset",
        description=f"{removed} users removed. List cleared.",
        color=discord.Color.red()
    ))

@bot.event
async def on_presence_update(before, after):
    if not check_all_statuses.is_running():
        check_all_statuses.start()
    if after.bot or not after.guild:
        return

    # Only process when user is online (not offline)
    if after.status == discord.Status.offline:
        return

    data = await vanity_col.find_one({"guild": str(after.guild.id)})
    if not data:
        return

    keyword = data["keyword"].lower()
    # Safely get activity
    status = before.activity.name.lower() if before.activity and before.activity.name else ""
    new_status = after.activity.name.lower() if after.activity and after.activity.name else ""
    role = after.guild.get_role(data["role"])
    log_ch = after.guild.get_channel(data["log"])
    has_role = role in after.roles

    # Give role when keyword newly appears in status
    if keyword not in status and keyword in new_status and not has_role:
        await after.add_roles(role, reason="vanity match")
        await vanity_col.update_one({"guild": str(after.guild.id)}, {"$addToSet": {"users": after.id}})
        if log_ch:
            await log_ch.send(embed=discord.Embed(
                title="Vanity Added ✨",
                description=(
                    f"{after.mention} has been awarded **{role.name}** "
                    f"for proudly displaying our vanity `{keyword}` in their status!"
                ),
                color=discord.Color.magenta(),
                timestamp=datetime.utcnow()
            ).set_thumbnail(url=after.display_avatar.url))

    # Remove role when keyword is removed from status (while online)
    elif keyword in status and keyword not in new_status and has_role:
        await after.remove_roles(role, reason="vanity lost")
        await vanity_col.update_one({"guild": str(after.guild.id)}, {"$pull": {"users": after.id}})
        if log_ch:
            await log_ch.send(embed=discord.Embed(
                title="Vanity Removed",
                description=(
                    f"{after.mention} has lost **{role.name}** for no longer "
                    f"displaying our vanity `{keyword}`."
                ),
                color=discord.Color.light_gray(),
                timestamp=datetime.utcnow()
            ).set_thumbnail(url=after.display_avatar.url))
            
@tasks.loop(minutes=3)
async def check_all_statuses():
    for guild in bot.guilds:
        data = await vanity_col.find_one({"guild": str(guild.id)})
        if not data:
            continue

        keyword = data["keyword"].lower()
        role = guild.get_role(data["role"])
        log_ch = guild.get_channel(data["log"])

        if not role:
            continue

        for member in guild.members:
            if member.bot or member.status == discord.Status.offline:
                continue

            status = (member.activity.name.lower() if member.activity and member.activity.name else "")
            has_role = role in member.roles

            if keyword in status and not has_role:
                await member.add_roles(role, reason="Vanity match (auto-check)")
                await vanity_col.update_one({"guild": str(guild.id)}, {"$addToSet": {"users": member.id}})
                if log_ch:
                    await log_ch.send(embed=discord.Embed(
                        title="Vanity Added ✨",
                        description=(
                            f"{member.mention} has been awarded **{role.name}**\n"
                            f"For displaying `{keyword}` in their status!"
                        ),
                        color=discord.Color.magenta(),
                        timestamp=datetime.now(UTC)
                    ).set_thumbnail(url=member.display_avatar.url))

            elif keyword not in status and has_role:
                await member.remove_roles(role, reason="Vanity removed (auto-check)")
                await vanity_col.update_one({"guild": str(guild.id)}, {"$pull": {"users": member.id}})
                if log_ch:
                    await log_ch.send(embed=discord.Embed(
                        title="Vanity Removed",
                        description=(
                            f"{member.mention} lost **{role.name}** for no longer "
                            f"displaying `{keyword}` in their status."
                        ),
                        color=discord.Color.light_gray(),
                        timestamp=datetime.now(UTC)
                    ).set_thumbnail(url=member.display_avatar.url))

@bot.command(aliases=["bal"])
async def balance(ctx, member: discord.Member = None):
    member = member or ctx.author
    data = await get_user(ctx.guild.id, member.id)
    embed = discord.Embed(title=f"{member.display_name}'s Balance", color=discord.Color.gold())
    embed.add_field(name="Wallet", value=f"🪙 {data['wallet']}", inline=True)
    embed.add_field(name="Bank", value=f"🏦 {data['bank']}", inline=True)
    await ctx.send(embed=embed)
    
@bot.command()
async def daily(ctx):
    data = await get_user(ctx.guild.id, ctx.author.id)
    now = datetime.utcnow()
    last = data.get("last_daily")

    if last and now - datetime.fromisoformat(last) < timedelta(hours=24):
        rem = timedelta(hours=24) - (now - datetime.fromisoformat(last))
        return await ctx.send(f"🕒 Claim again in {rem.seconds//3600}h {(rem.seconds//60)%60}m")

    new_balance = data['wallet'] + 500
    await economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"wallet": new_balance, "last_daily": now.isoformat()}}
    )
    await ctx.send("✅ You claimed your daily reward of 500 coins!")
    
@bot.command()
async def beg(ctx):
    data = await get_user(ctx.guild.id, ctx.author.id)
    now = datetime.utcnow()
    last = data.get("last_beg")

    if last and now - datetime.fromisoformat(last) < timedelta(minutes=15):
        rem = timedelta(minutes=15) - (now - datetime.fromisoformat(last))
        return await ctx.send(f"🕒 You can beg again in {rem.seconds // 60} minutes.")

    amount = random.randint(50, 200)
    donor = random.choice(["thetruck", "CuteBatak"])

    await economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"wallet": data["wallet"] + amount, "last_beg": now.isoformat()}}
    )
    await ctx.send(f"🙇 {donor} was kind enough to donate **{amount} coins** to you!")
    
@bot.command(aliases=["dep"])
async def deposit(ctx, amount: str):
    data = await get_user(ctx.guild.id, ctx.author.id)
    wallet = data["wallet"]

    if amount.lower() == "all":
        if wallet <= 0:
            return await ctx.send("❌ You have no coins to deposit.")
        deposit_amount = wallet
    elif amount.isdigit():
        deposit_amount = int(amount)
        if deposit_amount <= 0:
            return await ctx.send("❌ Invalid deposit amount.")
        if deposit_amount > wallet:
            return await ctx.send("❌ You can't afford that!")
    else:
        return await ctx.send("❌ Please enter a valid number or `all`.")

    await economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {
            "wallet": wallet - deposit_amount,
            "bank": data["bank"] + deposit_amount
        }}
    )
    await ctx.send(f"🏦 You deposited {deposit_amount} coins.")
    
@bot.command(aliases=["with"])
async def withdraw(ctx, amount: str):
    data = await get_user(ctx.guild.id, ctx.author.id)
    bank = data["bank"]

    if amount.lower() == "all":
        if bank <= 0:
            return await ctx.send("❌ You have no coins to withdraw.")
        withdraw_amount = bank
    elif amount.isdigit():
        withdraw_amount = int(amount)
        if withdraw_amount <= 0:
            return await ctx.send("❌ Invalid withdrawal amount.")
        if withdraw_amount > bank:
            return await ctx.send("❌ You can't afford that")
    else:
        return await ctx.send("❌ Please enter a valid number or `all`.")

    await economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {
            "wallet": data["wallet"] + withdraw_amount,
            "bank": bank - withdraw_amount
        }}
    )
    await ctx.send(f"💰 You withdrew {withdraw_amount} coins.")
    
@bot.command()
async def shop(ctx):
    shop_items = db["shop"].find()
    embed = discord.Embed(title="🛍️ Shop", color=discord.Color.green())
    async for item in shop_items:
        embed.add_field(
            name=f"{item['_id'].capitalize()} - 🪙 {item['price']}",
            value=item['description'],
            inline=False
        )
    await ctx.send(embed=embed)
    
@bot.command()
@staff_only()
async def additem(ctx, name, price: int, *, description):
    await shop_col.insert_one({
        "_id": name.lower(),
        "price": price,
        "description": description
    })
    await ctx.send(f"✅ `{name}` added to the shop.")
    
@bot.command()
@staff_only()
async def edititem(ctx, name, price: int, *, description):
    result = await shop_col.update_one(
        {"_id": name.lower()},
        {"$set": {"price": price, "description": description}}
    )
    if result.matched_count:
        await ctx.send(f"📝 `{name}` updated!")
    else:
        await ctx.send("❌ Item not found.")

@bot.command()
@staff_only()
async def delitem(ctx, name):
    result = await shop_col.delete_one({"_id": name.lower()})
    if result.deleted_count:
        await ctx.send(f"🗑️ `{name}` removed from the shop.")
    else:
        await ctx.send("❌ Item not found.")
    
@bot.command()
async def buy(ctx, *, item: str = None):
    if not item:
        return await ctx.send("❌ You must specify an item to buy.")
    item = item.lower()
    store_item = await shop_col.find_one({"_id": item})
    if not store_item:
        return await ctx.send("❌ Item not found.")

    data = await get_user(ctx.guild.id, ctx.author.id)
    if data["wallet"] < store_item["price"]:
        return await ctx.send("❌ Not enough coins.")

    data["wallet"] -= store_item["price"]
    data["inventory"].append(item)
    await economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"wallet": data["wallet"], "inventory": data["inventory"]}}
    )
    await ctx.send(f"✅ You bought a {item}!")
    
@bot.command()
async def use(ctx, *, item: str):
    item = item.lower()
    data = await get_user(ctx.guild.id, ctx.author.id)
    inv = data.get("inventory", [])

    # Find item ignoring case
    matched_item = next((i for i in inv if i.lower() == item), None)
    if not matched_item:
        return await ctx.send(f"❌ You don't have a {item} in your inventory.")

    # Remove one instance
    inv.remove(matched_item)
    await economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"inventory": inv}}
    )

#    if item == "_______":
#        await ctx.send("_____________")
#    else:
#        await ctx.send(f"🤷‍♂️ You used a {item}, but nothing special happened!")

@bot.command(aliases=["inv"])
async def inventory(ctx):
    data = await get_user(ctx.guild.id, ctx.author.id)
    inv = data.get("inventory", [])
    if not inv:
        return await ctx.send("🎒 Your inventory is empty.")
    counts = {i: inv.count(i) for i in set(inv)}
    desc = "\n".join(f"{name.capitalize()} x{count}" for name, count in counts.items())
    await ctx.send(embed=discord.Embed(
        title=f"{ctx.author.display_name}'s Inventory",
        description=desc, color=discord.Color.purple()
    ))

@bot.command(aliases=["pay"])
async def give(ctx, member: discord.Member, amount: int):
    if member == ctx.author or amount <= 0:
        return await ctx.send("❌ Invalid transaction.")

    sender = await get_user(ctx.guild.id, ctx.author.id)
    receiver = await get_user(ctx.guild.id, member.id)
    if sender["wallet"] < amount:
        return await ctx.send("❌ You don't have enough coins.")

    await economy_col.update_one({"_id": f"{ctx.guild.id}-{ctx.author.id}"}, {"$set": {"wallet": sender["wallet"] - amount}})
    await economy_col.update_one({"_id": f"{ctx.guild.id}-{member.id}"}, {"$set": {"wallet": receiver["wallet"] + amount}})
    await ctx.send(f"🤝 You gave {amount} coins to {member.mention}!")
    
@bot.command(aliases=["lb"])
async def leaderboard(ctx):
    cursor = economy_col.find({"guild": str(ctx.guild.id)})
    users = []
    async for doc in cursor:
        total = doc.get("wallet", 0) + doc.get("bank", 0)
        users.append((doc["user"], total))

    users.sort(key=lambda x: x[1], reverse=True)
    embed = discord.Embed(title="🏆 Leaderboard - Richest Users", color=discord.Color.teal())
    for i, (uid, total) in enumerate(users[:10], start=1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"User {uid}"
        embed.add_field(name=f"#{i} {name}", value=f"🪙 {total} coins", inline=False)
    await ctx.send(embed=embed)
    
@bot.command(aliases=["cf"])
async def coinflip(ctx, amount: int):
    data = await get_user(ctx.guild.id, ctx.author.id)

    if amount <= 0:
        return await ctx.send("❌ Invalid amount to coin flip.")
    if amount > data["wallet"]:
        return await ctx.send("❌ You can't afford that!")

    win_chance = 0.3
    won = random.random() < win_chance

    new_wallet = data["wallet"] + amount if won else data["wallet"] - amount
    await economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"wallet": new_wallet}}
    )

    if won:
        await ctx.send(f"🎉 You won {amount} coins from flipping a coin!")
    else:
        await ctx.send(f"💸 You lost {amount} coins from flipping a coin.")

@coinflip.error
async def coinflip_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ You must specify an amount. Example: `.coinflip 100`")
    else:
        await ctx.send(f"⚠️ Error: {type(error).__name__}: {error}")

@bot.command()
async def lottery(ctx):
    user_id = f"{ctx.guild.id}-{ctx.author.id}"
    data = await get_user(ctx.guild.id, ctx.author.id)
    now = datetime.utcnow()

    # Check cooldown from Mongo
    last_time = data.get("last_lottery")
    if last_time:
        last_dt = datetime.fromisoformat(last_time)
        if now - last_dt < timedelta(hours=1):
            rem = timedelta(hours=1) - (now - last_dt)
            return await ctx.send(f"🕒 You can try the lottery again in {rem.seconds // 60}m {rem.seconds % 60}s.")

    ticket_price = 300
    jackpot = random.randint(5000, 10000)
    chance = 0.01

    if data["wallet"] < ticket_price:
        return await ctx.send("🎟️ You need at least 300 coins to buy a lottery ticket.")

    data["wallet"] -= ticket_price
    win = random.random() <= chance
    if win:
        data["wallet"] += jackpot
        await ctx.send(f"🎉 You hit the jackpot and won **{jackpot} coins**!")
    else:
        await ctx.send("😢 No luck this time. Better luck next draw!")

    await economy_col.update_one(
        {"_id": user_id},
        {"$set": {"wallet": data["wallet"], "last_lottery": now.isoformat()}}
    )
    
@lottery.error
async def lottery_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        rem = timedelta(seconds=error.retry_after)
        mins = rem.seconds // 60
        secs = rem.seconds % 60
        return await ctx.send(f"🕒 Try again in {mins}m {secs}s.")
    
@bot.command(aliases=["mbox", "box"])
async def mysterybox(ctx):
    user_id = f"{ctx.guild.id}-{ctx.author.id}"
    data = await get_user(ctx.guild.id, ctx.author.id)
    now = datetime.utcnow()

    # Cooldown check
    last_time = data.get("last_mysterybox")
    if last_time:
        last_dt = datetime.fromisoformat(last_time)
        if now - last_dt < timedelta(hours=1):
            rem = timedelta(hours=1) - (now - last_dt)
            return await ctx.send(f"🕒 You can open another Mystery Box in {rem.seconds // 60}m {rem.seconds % 60}s.")

    price = 250
    if data["wallet"] < price:
        return await ctx.send("❌ You need 250 coins to open a Mystery Box.")

    data["wallet"] -= price

    rewards = [
        {"type": "garbage", "desc": "you found a half-empty bottle 🍼", "chance": 0.3},
        {"type": "garbage", "desc": "you fished out some leftover pizza 🍕", "chance": 0.25},
        {"type": "garbage", "desc": "you discovered a smelly sock 🧦", "chance": 0.2},
        {"type": "coins", "amount": 100, "desc": "💰 You found 100 coins!", "chance": 0.1},
        {"type": "coins", "amount": 300, "desc": "💸 Nice! You got 300 coins!", "chance": 0.05},
        {"type": "item", "name": "fishing rod", "desc": "🎣 You won a Fishing Rod!", "chance": 0.05},
        {"type": "item", "name": "laptop", "desc": "💻 You scored a shiny new Laptop!", "chance": 0.03},
        {"type": "item", "name": "gold badge", "desc": "🏅 You got a rare Gold Badge!", "chance": 0.02},
    ]

    reward = random.choices(rewards, weights=[r["chance"] for r in rewards])[0]
    msg = reward["desc"]
    if reward["type"] == "coins":
        data["wallet"] += reward["amount"]
    elif reward["type"] == "item":
        data.setdefault("inventory", []).append(reward["name"])

    await economy_col.update_one(
        {"_id": user_id},
        {"$set": {
            "wallet": data["wallet"],
            "inventory": data["inventory"],
            "last_mysterybox": now.isoformat()
        }}
    )

    await ctx.send(f"🎁 {msg}")

class JobPicker(ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=30)
        self.ctx = ctx

    async def interaction_check(self, interaction):
        return interaction.user == self.ctx.author

    @ui.button(label="Developer 🧑‍💻", style=discord.ButtonStyle.blurple)
    async def dev_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.set_job(interaction, "developer")

    @ui.button(label="Duck 🦆", style=discord.ButtonStyle.green)
    async def duck_button(self, interaction: discord.Interaction, button: ui.Button):
        await self.set_job(interaction, "duck")

    async def set_job(self, interaction, job_name):
        await economy_col.update_one(
            {"_id": f"{self.ctx.guild.id}-{self.ctx.author.id}"},
            {"$set": {
                "job": job_name,
                "job_start": datetime.utcnow().isoformat(),
                "promoted": False
            }},
            upsert=True
        )
        await interaction.response.edit_message(
            content=f"✅ You are now working as a **{job_name.capitalize()}**!",
            view=None
        )

@bot.command()
async def choosejob(ctx):
    view = JobPicker(ctx)
    await ctx.send(
        "💼 Choose your job by clicking one of the buttons below:",
        view=view
    )

@bot.command(name="work")
@commands.cooldown(1, 43200, commands.BucketType.user)  # 12-hour cooldown
async def work(ctx):
    try:
        data = await get_user(ctx.guild.id, ctx.author.id)
        job = data.get("job")

        if not job:
            # Get server prefix for help message
            doc = await settings_col.find_one({"guild": str(ctx.guild.id)})
            prefix = doc.get("prefix", "?") if doc else "?"
            return await ctx.send(f"❌ You don’t have a job yet! Use `{prefix}choosejob` to get one.")

        # Inventory check for developer job
        inventory = data.get("inventory", [])
        if job == "developer" and "laptop" not in inventory:
            return await ctx.send("💻 You need a **laptop** to work as a developer!")

        # Job time & promotion logic
        job_start_raw = data.get("job_start")
        promoted = data.get("promoted", False)
        if job_start_raw:
            job_start = datetime.fromisoformat(job_start_raw) if isinstance(job_start_raw, str) else job_start_raw
            days_worked = (datetime.utcnow() - job_start).days
        else:
            days_worked = 0

        # Payouts and job descriptions
        base_payouts = {
            "developer": (300, 600),
            "duck": (200, 500)
        }
        promo_payouts = {
            "developer": (600, 1000),
            "duck": (500, 900)
        }
        descriptions = {
            "developer": "You wrote some killer code 💻",
            "duck": "You danced and quacked around the duck pond 🦆"
        }

        # Promotion chance after 7 days
        if not promoted and days_worked >= 7 and random.random() <= 0.001:
            promoted = True
            await ctx.send("🎉 **Congratulations – You've been PROMOTED!** You now earn more in your job!")

        # Payout calculation
        low, high = promo_payouts[job] if promoted else base_payouts[job]
        earned = random.randint(low, high)
        new_wallet = data.get("wallet", 0) + earned

        # Save changes to Mongo
        await economy_col.update_one(
            {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
            {"$set": {
                "wallet": new_wallet,
                "promoted": promoted
            }},
            upsert=True
        )

        await ctx.send(
            f"🧾 {descriptions.get(job, 'You worked hard!')}\n"
            f"💰 You earned **{earned} coins** as a {'promoted ' if promoted else ''}{job}!"
        )

    except Exception as e:
        # Catch any unexpected errors and log them
        await ctx.send("⚠️ Something went wrong while processing your work. Please try again.")
        print(f"[ERROR] work command: {type(e).__name__} - {e}")

@work.error
async def work_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        total_seconds = int(error.retry_after)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return await ctx.send(f"🕒 You can work again in {hours}h {minutes}m.")
    else:
        await ctx.send("⚠️ An unexpected error occurred.")
        raise error

@bot.command()
async def jobstatus(ctx):
    user_id = f"{ctx.guild.id}-{ctx.author.id}"
    user_data = await economy_col.find_one({"_id": user_id}) or {}

    # Use job_start, not job_since
    job = user_data.get("job")
    job_start_str = user_data.get("job_start")

    if not job or not job_start_str:
        return await ctx.send("💼 You don't currently have a job. Choose one with your server's prefix like `?choosejob`.")

    try:
        # Parse ISO date string into datetime object
        job_start = datetime.fromisoformat(job_start_str)
    except Exception as e:
        print(f"[jobstatus error] Failed to parse job_start: {e}")
        return await ctx.send("⚠️ There was an error reading your job data. Please try again or contact support.")

    now = datetime.utcnow()
    delta = now - job_start

    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60

    eligible = "✅ Eligible for promotion!" if days >= 7 else f"❌ Not eligible yet (need {7 - days} more day(s))."

    embed = discord.Embed(
        title=f"📋 Job Status for {ctx.author.display_name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="Job", value=job.capitalize(), inline=False)
    embed.add_field(name="Time on Job", value=f"{days}d {hours}h {minutes}m", inline=False)
    embed.add_field(name="Promotion Chance", value=eligible, inline=False)

    await ctx.send(embed=embed)

@bot.command()
async def fish(ctx):
    user_id = f"{ctx.guild.id}-{ctx.author.id}"
    data = await get_user(ctx.guild.id, ctx.author.id)

    # Check for fishing rod
    if "fishing rod" not in data.get("inventory", []):
        return await ctx.send("🎣 You need a fishing rod to fish!")

    # Check for cooldown
    last_fished = data.get("last_fished")
    now = datetime.utcnow()
    if last_fished:
        # Convert to datetime if stored as string (in case it is)
        if isinstance(last_fished, str):
            last_fished = datetime.fromisoformat(last_fished)

        delta = now - last_fished
        if delta < timedelta(hours=3):
            hours_remaining = round((timedelta(hours=3) - delta).total_seconds() / 3600, 2)
            return await ctx.send(f"🕒 You can fish again in {hours_remaining} hours.")

    # Perform the fishing
    catch = random.choice(fishes)
    data["wallet"] += catch[1]

    await economy_col.update_one(
        {"_id": user_id},
        {"$set": {
            "wallet": data["wallet"],
            "last_fished": now
        }}
    )

    await ctx.send(f"🎣 You caught a {catch[0]} and earned {catch[1]} coins!")

@fish.error
async def fish_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"🕒 You can fish again in {round(error.retry_after / 3600, 2)} hours.")

@bot.command(aliases=["steal"])
async def rob(ctx, member: discord.Member):
    if member == ctx.author:
        return await ctx.send("❌ You can't rob yourself!")

    now = datetime.utcnow()
    robber_id = f"{ctx.guild.id}-{ctx.author.id}"
    victim_id = f"{ctx.guild.id}-{member.id}"

    r_doc = await economy_col.find_one({"_id": robber_id}) or {}
    v_doc = await economy_col.find_one({"_id": victim_id}) or {}

    # Check cooldown from Mongo
    cooldown = r_doc.get("rob_cooldown")
    if cooldown:
        cooldown_dt = datetime.fromisoformat(cooldown)
        if now < cooldown_dt:
            remaining = cooldown_dt - now
            mins = int(remaining.total_seconds() // 60)
            return await ctx.send(f"🕒 You can rob again in {mins} minute(s).")

    # Passive mode checks
    if r_doc.get("passive_until"):
        until = datetime.fromisoformat(r_doc["passive_until"])
        if until > now:
            return await ctx.send("🔒 You have passive mode enabled — disable it to rob others.")
    if v_doc.get("passive_until"):
        until = datetime.fromisoformat(v_doc["passive_until"])
        if until > now:
            return await ctx.send("🔒 That user has passive mode enabled — you can't rob them.")

    # Victim rob cooldown (1h protection)
    last_robbed = v_doc.get("last_robbed")
    if last_robbed:
        if isinstance(last_robbed, str):
            last_robbed = datetime.fromisoformat(last_robbed)
        if now - last_robbed < timedelta(hours=1):
            rem = timedelta(hours=1) - (now - last_robbed)
            minutes = round(rem.total_seconds() / 60)
            return await ctx.send(f"🛡️ {member.display_name} is under protection. Try again in {minutes} minutes.")

    # Wallet checks
    if r_doc.get("wallet", 0) < 500:
        return await ctx.send("❌ You need at least 500 coins to rob.")
    if v_doc.get("wallet", 0) < 300:
        return await ctx.send("❌ They don’t have enough coins to rob.")

    # Robbery success
    amount = random.randint(100, min(500, v_doc["wallet"], r_doc["wallet"]))
    r_doc["wallet"] += amount
    v_doc["wallet"] -= amount

    await economy_col.update_one({"_id": robber_id}, {
        "$set": {
            "wallet": r_doc["wallet"],
            "rob_cooldown": (now + timedelta(hours=3)).isoformat()
        }
    })

    await economy_col.update_one({"_id": victim_id}, {
        "$set": {
            "wallet": v_doc["wallet"],
            "last_robbed": now.isoformat()
        }
    })

    await ctx.send(f"💰 You robbed {member.display_name} and stole {amount} coins!")
    
@bot.command()
async def passive(ctx):
    user_id = f"{ctx.guild.id}-{ctx.author.id}"
    now = datetime.utcnow()
    user_data = await economy_col.find_one({"_id": user_id}) or {}

    passive_until = user_data.get("passive_until")
    if passive_until and datetime.fromisoformat(passive_until) > now:
        rem = datetime.fromisoformat(passive_until) - now
        hours = rem.seconds // 3600
        mins = (rem.seconds % 3600) // 60
        return await ctx.send(f"🕒 Passive mode already active for {rem.days}d {hours}h {mins}m.")

    until_time = now + timedelta(hours=24)
    await economy_col.update_one(
        {"_id": user_id},
        {"$set": {"passive_until": until_time.isoformat()}},
        upsert=True
    )
    await ctx.send("🛡️ Passive mode enabled for 24 hours — you can't rob or be robbed.")

class AnswerButton(discord.ui.Button):
    def __init__(self, label: str, value: int, parent_view):
        super().__init__(style=discord.ButtonStyle.primary, label=label, custom_id=str(value))
        self.value = value
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        view = self.parent_view
        if interaction.user.id != view.user_id:
            return await interaction.response.send_message("This quiz isn't yours.", ephemeral=True)

        idx = view.current_index
        if view.answered_ids.get(idx):
            return await interaction.response.send_message("You already answered this question.", ephemeral=True)

        # record answer
        view.answered_ids[idx] = True
        correct_answer = view.questions[idx]['answer']
        if self.value == correct_answer:
            view.score += 1

        # disable all buttons in this view
        view.disable_all_buttons()
        await interaction.response.edit_message(view=view)

        reply = ("✅ Correct!" if self.value == correct_answer
                 else f"❌ Wrong! Answer was: {view.questions[idx]['options'][correct_answer-1]}")
        await interaction.followup.send(reply, ephemeral=True)

        view.current_index += 1
        await view.show_next(interaction)

class QuizView(discord.ui.View):
    def __init__(self, ctx, quiz_id, questions_list):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.user_id = ctx.author.id
        self.quiz_id = quiz_id
        self.questions = questions_list
        self.current_index = 0
        self.score = 0
        self.answered_ids = {}
        # add answer buttons
        for i in range(1, 5):
            self.add_item(AnswerButton(str(i), i, self))

    def disable_all_buttons(self):
        for item in self.children:
            item.disabled = True

    async def show_next(self, interaction: discord.Interaction = None):
        if self.current_index >= len(self.questions):
            await self.finish_quiz(interaction)
            return

        q = self.questions[self.current_index]
        opts = "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(q["options"]))
        embed = discord.Embed(
            title=f"Question {self.current_index+1}/{len(self.questions)}",
            description=q["q"],
            color=discord.Color.teal()
        )
        embed.add_field(name="Options", value=opts, inline=False)
        embed.set_footer(text="Click a button below to answer.")

        # reset buttons for new question
        self.clear_items()
        for i in range(1, 5):
            self.add_item(AnswerButton(str(i), i, self))

        if interaction:
            await interaction.followup.send(embed=embed, view=self, ephemeral=True)
        else:
            await self.ctx.send(embed=embed, view=self, ephemeral=True)

    async def finish_quiz(self, interaction: discord.Interaction = None):
        pct = self.score / len(self.questions) * 100.0
        passed = pct >= PASS_PCT
    
        # update DB record
        await quiz_col.update_one(
            {"_id": self.quiz_id},
            {"$set": {
                "score": self.score,
                "completed": datetime.utcnow(),
                "passed": passed
            }}
        )
    
        # Create result message
        result = f"📊 You scored **{self.score}/{len(self.questions)}** = **{pct:.1f}%**"
        if passed:
            role = self.ctx.guild.get_role(ROLE_ID)
            if role:
                await self.ctx.author.add_roles(role)
                result += f"\n🎉 You passed and got the **{role.name}** role!"
            else:
                result += "\n⚠️ Role not found to assign."
    
        # Send result ephemerally
        if interaction:
            await interaction.followup.send(content=result, ephemeral=True)
        else:
            await self.ctx.send(content=result)
    
        self.stop()

@bot.command()
@commands.cooldown(1, 3600, commands.BucketType.user)
async def duckquiz(ctx):
    if ctx.channel.id != QUIZ_CHANNEL:
        return await ctx.send(f"❌ Please use this command in <#{QUIZ_CHANNEL}>.")

    USER, GUILD = str(ctx.author.id), str(ctx.guild.id)
    rec = await quiz_col.find_one({"guild": GUILD, "user": USER, "passed": True})
    if rec:
        await ctx.send("ℹ You’ve already passed; type `yes` within 30s to retake.")
        try:
            msg = await bot.wait_for("message", timeout=30, check=lambda m: m.author == ctx.author and m.channel == ctx.channel)
            if msg.content.strip().lower() != "yes":
                return await ctx.send("✅ Quiz cancelled.")
        except asyncio.TimeoutError:
            return await ctx.send("⌛ Timed out—quiz cancelled.")

    used = await quiz_col.distinct("qid", {"guild": GUILD, "used": True})
    pool = [q for q in questions if q["id"] not in used]
    if len(pool) < NUM_Q:
        await quiz_col.update_many({"guild": GUILD}, {"$unset": {"used": ""}})
        pool = questions.copy()
    selected = random.sample(pool, NUM_Q)

    for q in selected:
        await quiz_col.update_one({"guild": GUILD, "qid": q["id"]}, {"$set": {"used": True}}, upsert=True)

    quiz_doc = {
        "guild": GUILD, "user": USER, "started": datetime.utcnow(),
        "questions": [q["id"] for q in selected],
        "answers": {}, "score": 0, "completed": None, "passed": False
    }
    res = await quiz_col.insert_one(quiz_doc)
    view = QuizView(ctx, res.inserted_id, selected)
    await view.show_next()

@duckquiz.error
async def duckquiz_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        mins = int(error.retry_after // 60)
        await ctx.send(f"🕒 Please wait {mins} more minute(s) before doing the quiz again.")
    else:
        await ctx.send("⚠️ An error occurred, please try again.")
    
@bot.command()
async def afk(ctx, *, reason="AFK"):
    await afk_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat()
        }},
        upsert=True
    )
    await ctx.send(f"🛌 You are now AFK: {reason}")

# Kick a member
@bot.command()
@staff_only()
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    err = check_target_permission(ctx, member)
    if err: return await ctx.send(err)
    await member.kick(reason=f"{reason} (by {ctx.author})")
    await ctx.send(f"✅ {member.mention} has been kicked.")
    await log_action(ctx, f"Kicked {member} for: {reason}", user_id=member.id, action_type="kick")

# Ban a member
@bot.command()
@staff_only()
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    err = check_target_permission(ctx, member)
    if err: return await ctx.send(err)
    await member.ban(reason=f"{reason} (by {ctx.author})")
    await ctx.send(f"✅ {member.mention} has been banned.")
    await log_action(ctx, f"Banned {member} for: {reason}", user_id=member.id, action_type="ban")

# Unban a user by ID
@bot.command()
@staff_only()
async def unban(ctx, *, user_id: int):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user)
        await ctx.send(f"✅ {user.mention} has been unbanned.")
        await log_action(ctx, f"Unbanned {user}", user_id=user.id, action_type="unban")
    except Exception as e:
        await ctx.send("❌ Failed to unban that user.")
        
# Mute a member temporarily or indefinitely
@bot.command()
@staff_only()
async def mute(ctx, member: discord.Member, duration: str = None, *, reason="No reason provided"):
    err = check_target_permission(ctx, member)
    if err: return await ctx.send(err)
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if not mute_role:
        mute_role = await ctx.guild.create_role(name="Muted")
        for ch in ctx.guild.channels:
            await ch.set_permissions(mute_role, speak=False, send_messages=False)
    await member.add_roles(mute_role, reason=reason)
    await ctx.send(f"✅ {member.mention} has been muted. Duration: {duration or 'indefinite'}.")
    await log_action(ctx, f"Muted {member} for: {reason} ({duration or 'indefinite'})", user_id=member.id, action_type="mute")
    if duration:
        secs = convert_time(duration)
        if not secs:
            return await ctx.send("❌ Invalid duration format.")
        await asyncio.sleep(secs)
        await member.remove_roles(mute_role, reason="Mute expired")
        await ctx.send(f"✅ {member.mention} has been automatically unmuted.")
        await log_action(ctx, f"Auto-unmuted {member}", user_id=member.id, action_type="unmute")

# Unmute command
@bot.command()
@staff_only()
async def unmute(ctx, member: discord.Member):
    mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
    if mute_role and mute_role in member.roles:
        await member.remove_roles(mute_role, reason="Unmute command used")
        await ctx.send(f"✅ {member.mention} has been unmuted.")
        await log_action(ctx, f"Unmuted {member}", user_id=member.id, action_type="unmute")
    else:
        await ctx.send("⚠️ That member is not muted.")
        
# Warn a member
@bot.command()
@staff_only()
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    await mod_col.update_one(
        {"guild": str(ctx.guild.id), "user": str(member.id)},
        {"$push": {"warnings": {"by": str(ctx.author), "reason": reason, "time": datetime.utcnow().isoformat()}}},
        upsert=True
    )
    await ctx.send(f"⚠️ {member.mention} has been warned: {reason}")
    await log_action(ctx, f"Warned {member} for: {reason}", user_id=member.id, action_type="warn")

# Clear warnings for a member
@bot.command()
@staff_only()
async def clearwarns(ctx, member: discord.Member):
    await mod_col.update_one({"guild": str(ctx.guild.id), "user": str(member.id)}, {"$set": {"warnings": []}})
    await ctx.send(f"✅ All warnings for {member.mention} have been cleared.")
    await log_action(ctx, f"Cleared warnings for {member}", user_id=member.id, action_type="clearwarns")
    
# Purge messages
@bot.command()
@staff_only()
async def purge(ctx, count: int, member: discord.Member = None):
    def check(m):
        return m.author == member if member else True
    deleted = await ctx.channel.purge(limit=count+1, check=check)
    await ctx.send(f"🧹 Deleted {len(deleted)-1} messages.", delete_after=5)
    await log_action(ctx, f"Purged {len(deleted)-1} messages{(' from '+member.display_name) if member else ''}", action_type="purge")
    
# Slowmode command
@bot.command()
@staff_only()
async def slowmode(ctx, seconds: int):
    await ctx.channel.edit(slowmode_delay=seconds)
    await ctx.send(f"✅ Slowmode set to {seconds} seconds.")
    await log_action(ctx, f"Set slowmode to {seconds}s in #{ctx.channel.name}", action_type="slowmode")
    
# Set prefix for this server
@bot.command()
@staff_only()
async def setprefix(ctx, new: str):
    await settings_col.update_one({"guild": str(ctx.guild.id)}, {"$set": {"prefix": new}}, upsert=True)
    await ctx.send(f"✅ Prefix updated to `{new}`.")
    await log_action(ctx, f"Prefix changed to {new}", action_type="setprefix")

# Set log channel for moderation
@bot.command()
@staff_only()
async def logchannel(ctx, channel: discord.TextChannel):
    await settings_col.update_one({"guild": str(ctx.guild.id)}, {"$set": {"log_channel": channel.id}}, upsert=True)
    await ctx.send(f"✅ Log channel set to {channel.mention}.")
    await log_action(ctx, f"Log channel set to {channel}", action_type="logchannel")
    
# User Info
@bot.command()
@staff_only()
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    join = member.joined_at.strftime("%Y-%m-%d")
    created = member.created_at.strftime("%Y-%m-%d")
    doc = await mod_col.find_one({"guild": str(ctx.guild.id), "user": str(member.id)})
    warns = len(doc.get("warnings", [])) if doc else 0
    embed = discord.Embed(title="User Information", color=discord.Color.blurple())
    embed.set_thumbnail(url=member.avatar.url if member.avatar else "")
    embed.add_field(name="ID", value=member.id)
    embed.add_field(name="Joined Server", value=join)
    embed.add_field(name="Account Created", value=created)
    embed.add_field(name="Warnings", value=warns)
    await ctx.send(embed=embed)
    
@bot.command()
@staff_only()
async def reactionrole(ctx, message_id: int, emoji, role: discord.Role):
    try:
        msg = await ctx.channel.fetch_message(message_id)
        await msg.add_reaction(emoji)
        await reaction_col.update_one({"message": message_id}, {"$set": {"emoji": str(emoji), "role": role.id}}, upsert=True)
        await ctx.send(f"✅ Reaction role set: {emoji} will grant {role.mention}.")
    except Exception as e:
        print(f"[reactionrole error] {e}")
        await ctx.send("❌ Could not set reaction role. Check your permissions and message ID.")

@bot.command()
@staff_only()
async def stickynote(ctx):
    await ctx.send("📝 Please type the message to pin as sticky:")

    def check(m): return m.author == ctx.author and m.channel == ctx.channel
    try:
        reply = await bot.wait_for("message", check=check, timeout=60)

        # Delete old sticky note if exists
        doc = await sticky_col.find_one({"guild": str(ctx.guild.id), "channel": str(ctx.channel.id)})
        if doc:
            try:
                old_msg = await ctx.channel.fetch_message(doc["message"])
                await old_msg.delete()
            except Exception as e:
                print(f"[stickynote delete error] {e}")

        # Send new sticky note and save to DB
        sent = await ctx.send(reply.content)
        await sticky_col.update_one(
            {"guild": str(ctx.guild.id), "channel": str(ctx.channel.id)},
            {"$set": {"text": reply.content, "message": sent.id}},
            upsert=True
        )
        await ctx.send("✅ Sticky note created.")
    except asyncio.TimeoutError:
        await ctx.send("❌ Timeout. Sticky note creation cancelled.")

@bot.command()
@staff_only()
async def unstickynote(ctx):
    doc = await sticky_col.find_one({"guild": str(ctx.guild.id), "channel": str(ctx.channel.id)})
    if doc:
        try:
            msg = await ctx.channel.fetch_message(doc["message"])
            await msg.delete()
        except:
            print(f"[stickynote error] {e}")
            await ctx.send("❌ Could not set stickynote.")
        sticky_col.delete_one({"guild": str(ctx.guild.id), "channel": str(ctx.channel.id)})
        await ctx.send("✅ Sticky note removed.")
    else:
        await ctx.send("⚠️ No sticky note set for this channel.")

@bot.command()
@staff_only()
async def setwelcome(ctx, channel: discord.TextChannel):
    await welcome_col.update_one(
        {"guild": str(ctx.guild.id)},
        {"$set": {"welcome_channel": channel.id}},
        upsert=True
    )
    await ctx.send(f"✅ Welcome channel set to {channel.mention}.")
    
@bot.command()
@staff_only()
async def delwelcome(ctx):
    result = await welcome_col.update_one(
        {"guild": str(ctx.guild.id)},
        {"$unset": {"welcome_channel": ""}}
    )
    if result.modified_count:
        await ctx.send("✅ Welcome channel configuration has been removed.")
    else:
        await ctx.send("⚠️ No welcome channel was set.")

@bot.command()
@staff_only()
async def setboost(ctx, channel: discord.TextChannel):
    await boost_col.update_one(
        {"guild": str(ctx.guild.id)},
        {"$set": {"boost_channel": channel.id}},
        upsert=True
    )
    await ctx.send(f"✅ Boost channel set to {channel.mention}.")
    
@bot.command()
@staff_only()
async def delboost(ctx):
    result = await boost_col.update_one(
        {"guild": str(ctx.guild.id)},
        {"$unset": {"boost_channel": ""}}
    )
    if result.modified_count:
        await ctx.send("✅ Boost channel configuration has been removed.")
    else:
        await ctx.send("⚠️ No boost channel was set.")

@bot.command()
@staff_only()
async def testwelcome(ctx, member: discord.Member = None):
    member = member or ctx.author
    guild = ctx.guild
    welcome_doc = await welcome_col.find_one({"guild": str(guild.id)})
    welcome_ch = guild.get_channel(welcome_doc.get("welcome_channel")) if welcome_doc else None

    if not welcome_ch:
        return await ctx.send("❌ No welcome channel set.")

    embed = discord.Embed(
        title=f"Welcome to Duck Paradise 🦆 quack!",
        description=(
            "⭐ **Quack loud in** <#1370374734037909576> and enjoy the pond! ✨\n"
            "⭐ **Check** <#1370374725108236379> to equip tag! ✨\n"
            "⭐ **Boost our pond** and get exclusive <@&1370367716892082236> role! ✨"
        ),
        color=discord.Color.from_str("#2f3136")
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_image(url="https://cdn.discordapp.com/attachments/1370374741579534408/1386456926300409939/duckduckgo-welcome.gif")
    embed.set_footer(text=f"You are our {guild.member_count}th member!")

    await welcome_ch.send(f"welcome, {member.mention} 🐥!", embed=embed)
    await ctx.send("✅ Test welcome message sent.")

@bot.command()
@staff_only()
async def testboost(ctx, member: discord.Member = None):
    member = member or ctx.author
    guild = ctx.guild
    boost_doc = await boost_col.find_one({"guild": str(guild.id)})
    boost_ch = guild.get_channel(boost_doc.get("boost_channel")) if boost_doc else None

    if not boost_ch:
        return await ctx.send("❌ No boost channel set.")

    boost_embed = discord.Embed(
        title="🚀 Boost Alert!",
        description=f"{member.mention} just boosted the pond! 🌟\nThank you for your support!",
        color=discord.Color.fuchsia(),
        timestamp=datetime.utcnow()
    )
    boost_embed.set_thumbnail(url=member.display_avatar.url)

    await boost_ch.send(embed=boost_embed)
    await ctx.send("✅ Test boost message sent.")

@bot.event
async def on_member_join(member):
    guild = member.guild

    # WELCOME ========================
    welcome_doc = await welcome_col.find_one({"guild": str(guild.id)})
    welcome_ch = guild.get_channel(welcome_doc.get("welcome_channel")) if welcome_doc else None

    if welcome_ch:
        embed = discord.Embed(
            title=f"Welcome to Duck Paradise 🦆 quack!",
            description=(
                "⭐ **Quack loud in** <#1370374734037909576> and enjoy the pond! ✨\n"
                "⭐ **Check** <#1370374725108236379> to equip tag! ✨\n"
                "⭐ **Boost our pond** and get exclusive <@&1370367716892082236> role! ✨"
            ),
            color=discord.Color.from_str("#2f3136")
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_image(url="https://cdn.discordapp.com/attachments/1370374741579534408/1386456926300409939/duckduckgo-welcome.gif")
        embed.set_footer(text=f"You are our {guild.member_count}th member!")
        msg = await welcome_ch.send(f"welcome, {member.mention} 🐥!", embed=embed)

        # --- CUSTOM EMOJI REACTION ---
        duck_emoji = discord.utils.get(guild.emojis, name="duckwave2")
        if duck_emoji:
            await msg.add_reaction(duck_emoji)
        else:
            print("Custom emoji 'duckwave2' not found in guild.")

    # BOOST ==========================
    if member.premium_since:
        boost_doc = await boost_col.find_one({"guild": str(guild.id)})
        boost_ch = guild.get_channel(boost_doc.get("boost_channel")) if boost_doc else None

        if boost_ch:
            boost_embed = discord.Embed(
                title="🚀 Boost Alert!",
                description=f"{member.mention} just boosted the pond! 🌟\nThank you for your support!",
                color=discord.Color.fuchsia(),
                timestamp=datetime.utcnow()
            )
            boost_embed.set_thumbnail(url=member.display_avatar.url)
            await boost_ch.send(embed=boost_embed)

@bot.command()
@cooldown(1, 5, BucketType.user)
async def duck(ctx):
    """Send a random duck image (only allowed in specific channels)."""
    if ctx.channel.id not in ALLOWED_DUCK_CHANNELS:
        return await ctx.send("❌ This command can only be used in approved duck channels.")

    async with aiohttp.ClientSession() as session:
        async with session.get("https://random-d.uk/api/random") as resp:
            if resp.status != 200:
                return await ctx.send("❌ Could not get a duck right now, try again later!")
            data = await resp.json()
            url = data.get("url")
            if not url:
                return await ctx.send("❌ Duck image not found, sorry!")

    embed = discord.Embed(
        title="🦆 Quack!",
        color=discord.Color.blue()
    )
    embed.set_image(url=url)
    await ctx.send(embed=embed)
    
@bot.command()
@cooldown(1, 5, BucketType.user)
async def pun(ctx):
    """Send a random duck pun."""
    puns = [
        "Why did the duck go to therapy? It had a fowl attitude.",
        "Stop quacking jokes, you're cracking me up!",
        "I'm absolutely quackers for you!",
        "You're egg-ceptional!",
        "You really ruffled my feathers (in a good way).",
        "Have you met my down-to-earth friend?",
        "This conversation is going swimmingly.",
        "That joke really waddled its way into my heart.",
        "I feel down... must be molting season.",
        "Quack me up one more time and I'm out!",
        "Don't worry, be ducky!",
        "I'm in a fowl mood today.",
        "It's just water off a duck's back.",
        "You feather believe it!",
        "Don’t get your feathers ruffled.",
        "I can't wing it anymore!",
        "I beak to differ.",
        "Poultry in motion!",
        "Let’s get quackin’!",
        "Fowl play is not tolerated here.",
        "I'm on a feathered roll.",
        "I bill-ieve in you!",
        "That’s un-beak-lievable!",
        "Stay calm and quack on.",
        "I’m all quacked up.",
        "My life’s gone a bit south—like a migrating duck.",
        "You make my heart flap.",
        "Keep it ducky!",
    ]

    embed = discord.Embed(
        title="🦆 Duck Pun!",
        description=random.choice(puns),
        color=discord.Color.gold()
    )
    await ctx.send(embed=embed)

@bot.command()
async def serverinfo(ctx):
    await ctx.send(f"Server: {ctx.guild.name}\n👥 Members: {ctx.guild.member_count}\n🆔 ID: {ctx.guild.id}")

class CommandPages(View):
    def __init__(self, embeds):
        super().__init__(timeout=None)
        self.embeds = embeds
        self.index = 0
        self.prev = Button(label="⏮️ Prev", style=ButtonStyle.secondary)
        self.next = Button(label="⏭️ Next", style=ButtonStyle.secondary)
        self.prev.callback = self.show_prev
        self.next.callback = self.show_next
        self.add_item(self.prev)
        self.add_item(self.next)

    async def show_prev(self, interaction: Interaction):
        self.index = (self.index - 1) % len(self.embeds)
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    async def show_next(self, interaction: Interaction):
        self.index = (self.index + 1) % len(self.embeds)
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

bot.remove_command("help")
@bot.command(aliases=["help"])
async def cmds(ctx):
    doc = await settings_col.find_one({"guild": str(ctx.guild.id)})
    prefix = doc.get("prefix", "?") if doc else "?"
    staff_role = ctx.guild.get_role(doc.get("staff_role")) if doc else None
    is_staff = staff_role in ctx.author.roles if staff_role else False

    def format_field(name, value):
        return (name.replace("?", prefix), value)

    # GENERAL COMMANDS
    general = discord.Embed(title="💬 General Commands", color=discord.Color.blurple())
    for name, value in [
        ("?serverinfo", "View server information"),
        ("?cmds", "Show this help menu"),
        ("?afk [reason]", "Set your AFK status"),
        ("?duck", "Random picture of a duck"),
        ("?pun", "Random duck puns"),
        ("?duckquiz", "Standardized Duck Quiz")
    ]:
        general.add_field(name=format_field(name, value)[0], value=value, inline=False)

    # ECONOMY COMMANDS
    economy = discord.Embed(title="💰 Economy Commands", color=discord.Color.green())
    for name, value in [
        ("?balance / ?bal", "Check your balance"),
        ("?daily", "Claim your daily reward"),
        ("?work", "Work to earn coins"),
        ("?beg", "Beg for coins"),
        ("?deposit / ?dep <amount>", "Deposit to bank"),
        ("?withdraw / ?with <amount>", "Withdraw from bank"),
        ("?shop", "View the shop"),
        ("?buy <item>", "Buy an item from the shop"),
        ("?use <item>", "Use an item from your inventory"),
        ("?inventory / ?inv", "View your items"),
        ("?give / ?pay @user <amount>", "Give coins to another user"),
        ("?leaderboard / ?lb", "View the top users"),
        ("?coinflip / ?cf <amount>", "Coin flip for coins"),
        ("?fish", "Go fishing to earn coins"),
        ("?rob / ?steal @user", "Attempt to rob another user"),
        ("?lottery", "Join the lottery"),
        ("?mysterybox", "Open a mystery box"),
        ("?choosejob", "Choose your dream job"),
        ("?jobstatus", "Check your next promotion")
    ]:
        economy.add_field(name=format_field(name, value)[0], value=value, inline=False)

    pages = [general, economy]

    if is_staff:
        staff = discord.Embed(title="🛠️ Staff Commands", color=discord.Color.dark_red())
        for name, value in [
            ("?kick @user [reason]", "Kick a member"),
            ("?ban @user [reason]", "Ban a member"),
            ("?unban <user_id>", "Unban a user"),
            ("?mute @user <time> [reason]", "Mute a user temporarily"),
            ("?unmute @user", "Unmute a user"),
            ("?purge <count> [@user]", "Bulk delete messages"),
            ("?warn @user [reason]", "Warn a user"),
            ("?clearwarns @user", "Clear all warnings"),
            ("?slowmode <seconds>", "Set slowmode for this channel"),
            ("?setprefix <prefix>", "Change the bot prefix"),
            ("?logchannel #channel", "Set the moderation log channel"),
            ("?reactionrole <msg_id> <emoji> @role", "Set up a reaction role"),
            ("?stickynote", "Set a sticky note in this channel"),
            ("?unstickynote", "Remove the sticky note"),
            ("?setwelcome #channel", "Set the welcome channel"),
            ("?setboost #channel", "Set the boost message channel"),
            ("?testwelcome [@user]", "Send a test welcome message"),
            ("?testboost [@user]", "Send a test boost message"),
            ("?staffset @role", "Set the staff role"),
            ("?staffget", "Show the configured staff role"),
            ("?userinfo [@user]", "View detailed user info"),
            ("?vanityroles @role #logchannel <status>", "Track users with keyword in status"),
            ("?promoters", "View users with the vanity role"),
            ("?resetpromoters", "Clear all users from the vanity role"),
            ("?additem <item_name> <price> <description>", "Add an item to the shop"),
            ("?edititem <item_name> <new_price> <new_description>", "Edit an item in the shop"),
            ("?delitem <item_name>", "Remove an item from the shop")
        ]:
            staff.add_field(name=format_field(name, value)[0], value=value, inline=False)

        pages.append(staff)

    view = CommandPages(pages)
    await ctx.send(embed=pages[0], view=view)

@bot.command()
@staff_only()
async def stop(ctx):
    bot_locks[str(ctx.guild.id)] = True
    await ctx.send("🔒 Bot locked. Use 'override' by theofficialtruck to unlock.")

@bot.command()
async def override(ctx):
    if ctx.author.id == 1059882387590365314:
        bot_locks[str(ctx.guild.id)] = False
        await ctx.send("🚀 Bot unlocked!")
    else:
        await ctx.send("❌ You don't have permission.")

# Flask keep-alive for Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    print("Starting bot...")
    threading.Thread(target=run_flask).start()
    bot.run(TOKEN)
