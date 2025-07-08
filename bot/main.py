import discord
from discord.ext import commands
import asyncio
import os
import json
from keep_alive import keep_alive
from datetime import datetime
import traceback
from discord import Embed, ButtonStyle, Interaction
from discord.ui import View, Button
import discord
from discord.ext import commands
import random
from datetime import timedelta
import json

TOKEN = os.environ["DISCORD_TOKEN"]

intents = discord.Intents.all()

WARNINGS_FILE = "warnings.json"
ACTIONS_FILE = "actions.json"
CONFIG_FILE = "config.json"
REACTION_ROLE_FILE = "reaction_roles.json"
AFK_FILE = "afk.json"
STICKY_PATH = "stickynotes.json"
SHOP_PATH = "shop_items.json"
ECONOMY_PATH = "economy.json"
active_effects = {}

fishes = [
    ("🦐 Shrimp", 100),
    ("🐟 Fish", 200),
    ("🐠 Tropical Fish", 300),
    ("🦑 Squid", 400),
    ("🐡 Pufferfish", 500)
]

def load_shop_items():
    if not os.path.exists(SHOP_PATH):
        with open(SHOP_PATH, 'w') as f:
            json.dump({}, f)
    with open(SHOP_PATH, 'r') as f:
        return json.load(f)

def load_economy():
    if not os.path.exists(ECONOMY_PATH):
        with open(ECONOMY_PATH, 'w') as f:
            json.dump({}, f)
    with open(ECONOMY_PATH, 'r') as f:
        return json.load(f)

def save_economy(data):
    with open(ECONOMY_PATH, 'w') as f:
        json.dump(data, f, indent=2)

def get_user_data(guild_id, user_id):
    data = load_economy()
    g, u = str(guild_id), str(user_id)
    if g not in data:
        data[g] = {}
    if u not in data[g]:
        data[g][u] = {"wallet": 100, "bank": 0, "inventory": [], "last_daily": None, "last_work": None}
    save_economy(data)
    return data[g][u]

def update_user_data_all(guild_id, user_id, update_dict):
    data = load_economy()
    data[str(guild_id)][str(user_id)].update(update_dict)
    save_economy(data)

if not os.path.exists(economy_file):
    with open(economy_file, "w") as f:
        json.dump({}, f)

def load_sticky_notes():
    if os.path.exists(STICKY_PATH):
        with open(STICKY_PATH, "r") as f:
            return json.load(f)
    return {}

def save_sticky_notes(data):
    with open(STICKY_PATH, "w") as f:
        json.dump(data, f, indent=2)

sticky_notes = load_sticky_notes()

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

@bot.command(name="balance", aliases=["bal"])
async def balance(ctx, member: discord.Member = None):
    member = member or ctx.author
    user_data = get_user_data(ctx.guild.id, member.id)
    embed = Embed(title=f"{member.display_name}'s Balance", color=discord.Color.gold())
    embed.add_field(name="Wallet", value=f"🪙 {user_data['wallet']}", inline=True)
    embed.add_field(name="Bank", value=f"🏦 {user_data['bank']}", inline=True)
    await ctx.send(embed=embed)

@bot.command(name="daily", aliases=["collect"])
async def daily(ctx):
    user_data = get_user_data(ctx.guild.id, ctx.author.id)
    now = datetime.utcnow()
    last_claim = user_data.get("last_daily")
    if last_claim:
        last_time = datetime.fromisoformat(last_claim)
        if now - last_time < timedelta(hours=24):
            remaining = timedelta(hours=24) - (now - last_time)
            return await ctx.send(f"🕒 You can claim your daily again in {remaining.seconds//3600}h {(remaining.seconds//60)%60}m")
    user_data["wallet"] += 500
    update_user_data(ctx.guild.id, ctx.author.id, "wallet", user_data["wallet"])
    update_user_data(ctx.guild.id, ctx.author.id, "last_daily", now.isoformat())
    await ctx.send(f"✅ You claimed your daily reward of 500 coins!")

@bot.command(name="work", aliases=["earn"])
async def work(ctx):
    user_data = get_user_data(ctx.guild.id, ctx.author.id)
    now = datetime.utcnow()
    last_work = user_data.get("last_work")
    if last_work:
        last_time = datetime.fromisoformat(last_work)
        if now - last_time < timedelta(minutes=30):
            remaining = timedelta(minutes=30) - (now - last_time)
            return await ctx.send(f"🕒 You can work again in {remaining.seconds//60} minutes")
    if "laptop" not in user_data["inventory"]:
        return await ctx.send("💻 You need a laptop to work! Buy one from the shop with `?buy laptop`")
    earnings = 300
    user_data["wallet"] += earnings
    update_user_data(ctx.guild.id, ctx.author.id, "wallet", user_data["wallet"])
    update_user_data(ctx.guild.id, ctx.author.id, "last_work", now.isoformat())
    await ctx.send(f"💼 You worked and earned {earnings} coins!")
    
@bot.command()
async def beg(ctx):
    user_data = get_user_data(ctx.guild.id, ctx.author.id)
    now = datetime.utcnow()
    last_beg = user_data.get("last_beg")
    if last_beg:
        last_time = datetime.fromisoformat(last_beg)
        if now - last_time < timedelta(minutes=15):
            remaining = timedelta(minutes=15) - (now - last_time)
            return await ctx.send(f"🕒 You can beg again in {remaining.seconds//60} minutes")

    amount = random.randint(50, 200)
    user_data["wallet"] += amount
    update_user_data(ctx.guild.id, ctx.author.id, "wallet", user_data["wallet"])
    update_user_data(ctx.guild.id, ctx.author.id, "last_beg", now.isoformat())
    await ctx.send(f"🙇 You begged and received {amount} coins!")

@bot.command(name="deposit", aliases=["dep"])
async def deposit(ctx, amount: int):
    user_data = get_user_data(ctx.guild.id, ctx.author.id)
    if amount <= 0 or amount > user_data["wallet"]:
        return await ctx.send("❌ Invalid deposit amount.")
    user_data["wallet"] -= amount
    user_data["bank"] += amount
    update_user_data(ctx.guild.id, ctx.author.id, "wallet", user_data["wallet"])
    update_user_data(ctx.guild.id, ctx.author.id, "bank", user_data["bank"])
    await ctx.send(f"🏦 You deposited {amount} coins to your bank.")

@bot.command(name="withdraw", aliases=["with"])
async def withdraw(ctx, amount: int):
    user_data = get_user_data(ctx.guild.id, ctx.author.id)
    if amount <= 0 or amount > user_data["bank"]:
        return await ctx.send("❌ Invalid withdrawal amount.")
    user_data["bank"] -= amount
    user_data["wallet"] += amount
    update_user_data(ctx.guild.id, ctx.author.id, "wallet", user_data["wallet"])
    update_user_data(ctx.guild.id, ctx.author.id, "bank", user_data["bank"])
    await ctx.send(f"💰 You withdrew {amount} coins from your bank.")

@bot.command()
async def shop(ctx):
    try:
        shop_items = load_shop_items()
        if not shop_items:
            return await ctx.send("🛍️ The shop is empty. Add items to shop_items.json.")
        embed = Embed(title="🛍️ Item Shop", color=discord.Color.green())
        for item, info in shop_items.items():
            embed.add_field(name=f"{item.capitalize()} - 🪙 {info['price']}", value=info['description'], inline=False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❗ Error in shop: {e}")

@bot.command()
async def buy(ctx, item: str):
    try:
        item = item.lower()
        shop_items = load_shop_items()
        user = get_user_data(ctx.guild.id, ctx.author.id)

        if item not in shop_items:
            return await ctx.send("❌ That item doesn't exist in the shop.")
        price = shop_items[item]['price']

        if user['wallet'] < price:
            return await ctx.send("❌ You don't have enough coins.")

        user['wallet'] -= price
        user['inventory'].append(item)
        update_user_data_all(ctx.guild.id, ctx.author.id, user)

        await ctx.send(f"✅ You bought a {item}!")
    except Exception as e:
        await ctx.send(f"❗ Error in buy: {e}")

@bot.command(name="use", aliases=["consume"])
async def use(ctx, item: str):
    try:
        item = item.lower()
        user = get_user_data(ctx.guild.id, ctx.author.id)
        shop = load_shop_items()

        if item not in user.get("inventory", []):
            return await ctx.send(f"❌ You don't have a {item} in your inventory.")
        if item not in shop:
            return await ctx.send(f"❌ {item} is not a valid shop item.")
        if not shop[item].get("usable", False):
            return await ctx.send(f"⚠️ {item.capitalize()} is not usable.")

        effect = shop[item].get("effect")
        duration = shop[item].get("duration_minutes", 30)

        key = (ctx.guild.id, ctx.author.id)
        if key not in active_effects:
            active_effects[key] = {}

        if effect == "gamble_boost":
            expire = datetime.utcnow() + timedelta(minutes=duration)
            active_effects[key][effect] = expire
            await ctx.send(f"✨ You used {item} and gained a gambling boost for {duration} minutes!")
        else:
            await ctx.send(f"⚠️ Using {item} currently has no effect.")

        user["inventory"].remove(item)
        update_user_data_all(ctx.guild.id, ctx.author.id, user)
    except Exception as e:
        await ctx.send(f"❗ Error in use: {e}")

@bot.command()
async def gamble(ctx, amount: int):
    try:
        user = get_user_data(ctx.guild.id, ctx.author.id)
        if amount <= 0 or amount > user['wallet']:
            return await ctx.send("❌ Invalid amount to gamble.")

        key = (ctx.guild.id, ctx.author.id)
        now = datetime.utcnow()
        boost_active = False

        if key in active_effects:
            boost_expiry = active_effects[key].get("gamble_boost")
            if boost_expiry and boost_expiry > now:
                boost_active = True
            else:
                active_effects[key].pop("gamble_boost", None)

        win_chance = 0.75 if boost_active else 0.5

        if random.random() < win_chance:
            user['wallet'] += amount
            await ctx.send(f"🎉 You won {amount} coins from gambling!")
        else:
            user['wallet'] -= amount
            await ctx.send(f"💸 You lost {amount} coins from gambling.")

        update_user_data_all(ctx.guild.id, ctx.author.id, user)
    except Exception as e:
        await ctx.send(f"❗ Error in gamble: {e}")

@bot.command(name="inventory", aliases=["inv"])
async def inventory(ctx):
    shop_items = load_shop_items()
    user_data = get_user_data(ctx.guild.id, ctx.author.id)
    inv = user_data["inventory"]
    if not inv:
        return await ctx.send("🎒 Your inventory is empty.")
    counts = {}
    for i in inv:
        counts[i] = counts.get(i, 0) + 1
    desc = "\n".join(f"{name.capitalize()} x{count}" for name, count in counts.items())
    embed = Embed(title=f"{ctx.author.display_name}'s Inventory", description=desc, color=discord.Color.purple())
    await ctx.send(embed=embed)

@bot.command(name="give", aliases=["pay"])
async def give(ctx, member: discord.Member, amount: int):
    if member == ctx.author:
        return await ctx.send("❌ You can't give coins to yourself.")
    if amount <= 0:
        return await ctx.send("❌ Amount must be greater than 0.")
    sender_data = get_user_data(ctx.guild.id, ctx.author.id)
    receiver_data = get_user_data(ctx.guild.id, member.id)
    if sender_data["wallet"] < amount:
        return await ctx.send("❌ You don't have enough coins to give.")
    sender_data["wallet"] -= amount
    receiver_data["wallet"] += amount
    update_user_data(ctx.guild.id, ctx.author.id, "wallet", sender_data["wallet"])
    update_user_data(ctx.guild.id, member.id, "wallet", receiver_data["wallet"])
    await ctx.send(f"🤝 You gave {amount} coins to {member.mention}!")

@bot.command(name="leaderboard", aliases=["lb"])
async def leaderboard(ctx):
    data = load_economy()
    guild_id = str(ctx.guild.id)
    if guild_id not in data:
        return await ctx.send("📉 No economy data found for this server.")
    users = []
    for user_id, stats in data[guild_id].items():
        total = stats.get("wallet", 0) + stats.get("bank", 0)
        users.append((user_id, total))
    users.sort(key=lambda x: x[1], reverse=True)
    embed = Embed(title="🏆 Leaderboard - Richest Users", color=discord.Color.teal())
    for i, (user_id, total) in enumerate(users[:10], start=1):
        user = ctx.guild.get_member(int(user_id))
        name = user.display_name if user else f"User {user_id}"
        embed.add_field(name=f"#{i} {name}", value=f"🪙 {total} coins", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="rob", aliases=["steal"])
async def rob(ctx, member: discord.Member):
    if member == ctx.author:
        return await ctx.send("❌ You can't rob yourself!")

    robber_data = get_user_data(ctx.guild.id, ctx.author.id)
    victim_data = get_user_data(ctx.guild.id, member.id)

    if robber_data['wallet'] < 500:
        return await ctx.send("❌ You need at least 500 coins in your wallet to rob someone.")
    if victim_data['wallet'] < 300:
        return await ctx.send("❌ That user doesn't have enough coins to be robbed.")

    stolen = random.randint(100, min(robber_data['wallet'], victim_data['wallet'], 500))
    robber_data['wallet'] += stolen
    victim_data['wallet'] -= stolen
    update_user_data(ctx.guild.id, ctx.author.id, 'wallet', robber_data['wallet'])
    update_user_data(ctx.guild.id, member.id, 'wallet', victim_data['wallet'])

    await ctx.send(f"💰 You robbed {member.display_name} and stole {stolen} coins!")

@bot.command()
async def fish(ctx):
    user_data = get_user_data(ctx.guild.id, ctx.author.id)
    if "fishing_rod" not in user_data["inventory"]:
        return await ctx.send("🎣 You need a fishing rod to fish! Buy one from the shop with `?buy fishing_rod`")
    catch = random.choice(fishes)
    user_data['wallet'] += catch[1]
    update_user_data(ctx.guild.id, ctx.author.id, 'wallet', user_data['wallet'])
    await ctx.send(f"🎣 You caught a {catch[0]} and earned {catch[1]} coins!")

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

class CommandPages(View):
    def __init__(self, embeds):
        super().__init__(timeout=None)
        self.embeds = embeds
        self.current_page = 0
        self.total_pages = len(embeds)

        # add navigation buttons
        self.prev_button = Button(label="Previous", style=ButtonStyle.secondary)
        self.next_button = Button(label="Next", style=ButtonStyle.secondary)

        self.prev_button.callback = self.previous_page
        self.next_button.callback = self.next_page

        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    async def update_buttons(self, interaction: Interaction):
        # disable buttons when at the ends
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == self.total_pages - 1
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    async def previous_page(self, interaction: Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_buttons(interaction)

    async def next_page(self, interaction: Interaction):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await self.update_buttons(interaction)

class CommandPages(View):
    def __init__(self, embeds):
        super().__init__(timeout=None)
        self.embeds = embeds
        self.current_page = 0
        self.total_pages = len(embeds)

        # add navigation buttons
        self.prev_button = Button(label="Previous", style=ButtonStyle.secondary)
        self.next_button = Button(label="Next", style=ButtonStyle.secondary)

        self.prev_button.callback = self.previous_page
        self.next_button.callback = self.next_page

        self.add_item(self.prev_button)
        self.add_item(self.next_button)

    async def update_buttons(self, interaction: Interaction):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == self.total_pages - 1
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    async def previous_page(self, interaction: Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_buttons(interaction)

    async def next_page(self, interaction: Interaction):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await self.update_buttons(interaction)

@bot.command()
async def cmds(ctx):
    guild_id = str(ctx.guild.id)
    staff_role_id = config.get("staff_roles", {}).get(guild_id)
    staff_role = ctx.guild.get_role(staff_role_id) if staff_role_id else None
    is_staff = staff_role in ctx.author.roles if staff_role else False

    general = Embed(title="💬 General Commands", color=discord.Color.blurple())
    general.add_field(name="?serverinfo", value="*View server information*", inline=False)
    general.add_field(name="?cmds", value="*Show this help menu*", inline=False)
    general.add_field(name="?staffget", value="*Check the currently set staff role*", inline=False)
    general.add_field(name="?afk [reason]", value="*Set your AFK status*", inline=False)

    staff = Embed(title="🛠️ Staff-only Commands", color=discord.Color.blurple())
    staff.add_field(name="?kick @user [reason]", value="*Kick a member*", inline=False)
    staff.add_field(name="?ban @user [reason]", value="*Ban a member*", inline=False)
    staff.add_field(name="?unban <user_id>", value="*Unban a user*", inline=False)
    staff.add_field(name="?mute @user <time> [reason]", value="*Temporarily mute a user*", inline=False)
    staff.add_field(name="?unmute @user", value="*Unmute a user*", inline=False)
    staff.add_field(name="?purge <count>", value="*Bulk delete messages*", inline=False)
    staff.add_field(name="?warn @user [reason]", value="*Warn a user*", inline=False)
    staff.add_field(name="?clearwarns @user", value="*Clear all user warnings*", inline=False)
    staff.add_field(name="?slowmode <seconds>", value="*Set channel slowmode*", inline=False)
    staff.add_field(name="?setprefix <prefix>", value="*Change the bot prefix*", inline=False)
    staff.add_field(name="?reactionrole <msg_id> <emoji> @role", value="*Set reaction role*", inline=False)
    staff.add_field(name="?logchannel #channel", value="*Set moderation log channel*", inline=False)
    staff.add_field(name="?userinfo [@user]", value="*Detailed user info*", inline=False)
    staff.add_field(name="?staffset @role", value="*Set the staff role*", inline=False)
    staff.add_field(name="?setwelcome #channel", value="*Set welcome message channel*", inline=False)
    staff.add_field(name="?setboost #channel", value="*Set boost message channel*", inline=False)
    staff.add_field(name="?testwelcome [@user]", value="*Test welcome message*", inline=False)
    staff.add_field(name="?testboost [@user]", value="*Test boost message*", inline=False)
    staff.add_field(name="?stickynote", value="*Set a sticky message in a channel*", inline=False)
    staff.add_field(name="?unstickynote", value="*Remove sticky message*", inline=False)

    economy = Embed(title="💰 Economy Commands", color=discord.Color.blurple())
    economy.add_field(name="?bal", value="*Check your balance*", inline=False)
    economy.add_field(name="?daily", value="*Claim your daily reward*", inline=False)
    economy.add_field(name="?work", value="*Earn money by working*", inline=False)
    economy.add_field(name="?beg", value="*Beg for money*", inline=False)
    economy.add_field(name="?dep [amount]", value="*Deposit to bank*", inline=False)
    economy.add_field(name="?with [amount]", value="*Withdraw from bank*", inline=False)
    economy.add_field(name="?shop", value="*View shop items*", inline=False)
    economy.add_field(name="?buy <item>", value="*Buy an item from the shop*", inline=False)
    economy.add_field(name="?inventory", value="*View your items*", inline=False)
    economy.add_field(name="?use <item>", value="*Use an item from your inventory*", inline=False)
    economy.add_field(name="?give @user <amount>", value="*Give money to another user*", inline=False)
    economy.add_field(name="?leaderboard", value="*View the richest users*", inline=False)
    economy.add_field(name="?rob @user", value="*Rob another user*", inline=False)
    economy.add_field(name="?fish", value="*Go fishing to earn coins*", inline=False)
    economy.add_field(name="?gamble <amount>", value="*Gamble your coins*", inline=False)

    if is_staff:
        view = CommandPages([general, staff, economy])
    else:
        view = CommandPages([general, economy])

    await ctx.send(embed=view.embeds[0], view=view)

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
        await ctx.send(f"Kicked {member.mention}", delete_after=7)
        await log_action(ctx, f"kicked {member} for: {reason}", user_id=member.id, action_type="kick")

        try:
            await member.send(f"🚫 You have been kicked from **{ctx.guild.name}** for: {reason}")
        except:
            await log_action(ctx, f"Failed to DM kick message to {member} (ID: {member.id})")

    except Exception as e:
        await ctx.send("❌ Failed to kick the user.", delete_after=7)
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
async def stickynote(ctx):
    await ctx.send("📝 Please type the sticky message you'd like to set for this channel.")

    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel

    try:
        reply = await bot.wait_for("message", check=check, timeout=60.0)
    except asyncio.TimeoutError:
        return await ctx.send("⏰ Timed out. Please run `?stickynote` again.")

    guild_id = str(ctx.guild.id)
    channel_id = str(ctx.channel.id)

    # Delete old sticky if it exists
    if guild_id in sticky_notes and channel_id in sticky_notes[guild_id]:
        try:
            old_msg = await ctx.channel.fetch_message(int(sticky_notes[guild_id][channel_id]["message_id"]))
            await old_msg.delete()
        except:
            pass

    # Send and save new sticky
    sticky = await ctx.send(f"📌 **Sticky Note:** {reply.content}")

    if guild_id not in sticky_notes:
        sticky_notes[guild_id] = {}

    sticky_notes[guild_id][channel_id] = {
        "message": reply.content,
        "message_id": str(sticky.id)
    }

    save_sticky_notes(sticky_notes)

    await ctx.send("✅ Sticky note set successfully!", delete_after=7)
    await ctx.message.delete(delay=7)
    await reply.delete(delay=7)
    
@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author.bot:
        return

    channel_id = str(message.channel.id)
    if channel_id in sticky_notes:
        try:
            old_msg_id = int(sticky_notes[channel_id]["message_id"])
            old_msg = await message.channel.fetch_message(old_msg_id)
            await old_msg.delete()
        except:
            pass

        new_msg = await message.channel.send(f"📌 **Sticky Note:** {sticky_notes[channel_id]['message']}")
        sticky_notes[channel_id]["message_id"] = str(new_msg.id)
        save_sticky_notes(sticky_notes)
        
@bot.command()
@staff_only()
async def unstickynote(ctx):
    guild_id = str(ctx.guild.id)
    channel_id = str(ctx.channel.id)

    if guild_id in sticky_notes and channel_id in sticky_notes[guild_id]:
        try:
            msg_id = int(sticky_notes[guild_id][channel_id]["message_id"])
            msg = await ctx.channel.fetch_message(msg_id)
            await msg.delete()
        except:
            pass

        del sticky_notes[guild_id][channel_id]
        if not sticky_notes[guild_id]:
            del sticky_notes[guild_id]
        save_sticky_notes(sticky_notes)

        await ctx.send("✅ Sticky note removed for this channel.", delete_after=7)
        await ctx.message.delete(delay=7)
    else:
        await ctx.send("⚠️ No sticky note found for this channel.", delete_after=7)

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
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        warnings = len(warnings_data.get(guild_id, {}).get(user_id, []))

        joined_at = member.joined_at.strftime("%B %d, %Y") if member.joined_at else "Unknown"
        created_at = member.created_at.strftime("%B %d, %Y")
        join_days = (discord.utils.utcnow() - member.joined_at).days if member.joined_at else "Unknown"
        create_days = (discord.utils.utcnow() - member.created_at).days if member.created_at else "Unknown"

        embed = discord.Embed(
            title="-User Info-",
            description=f"Info for {member.mention}",
            color=discord.Color.blurple()
        )

        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)

        embed.add_field(name="🆔 User ID", value=str(member.id), inline=False)
        embed.add_field(name="👤 Nickname", value=member.nick or "None", inline=False)
        embed.add_field(name="📅 Join Date", value=f"{joined_at}, {join_days} days ago", inline=False)
        embed.add_field(name="📅 Creation Date", value=f"{created_at}, {create_days} days ago", inline=False)
        embed.add_field(name="🏅 Badges", value="None", inline=False)
        embed.add_field(name="📛 Tag", value=str(member.mention), inline=False)
        embed.add_field(name="💎 Nitro Boosting", value="Boosting" if member.premium_since else "Member not boosting.", inline=False)

        roles = [role.mention for role in member.roles if role.name != "@everyone"]
        roles_string = ", ".join(roles) if roles else "None"
        embed.add_field(name="🧷 Number of Roles", value=str(len(roles)), inline=False)
        embed.add_field(name="📌 Roles", value=roles_string, inline=False)

        embed.add_field(name="⚠️ Warnings", value=str(warnings), inline=False)

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