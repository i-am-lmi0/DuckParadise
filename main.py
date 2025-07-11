import os, asyncio, random, traceback
from datetime import datetime, timedelta
import discord
from discord.ext import commands
from pymongo import MongoClient
from discord.ui import View, Button
from discord import ButtonStyle, Interaction
from discord.ext.commands import Bot, when_mentioned_or
from discord import app_commands
from flask import Flask
import keep_alive

# 1. SETUP ====================================================
TOKEN = os.environ["abc123"]
mongo = MongoClient(os.getenv("MONGO_URI"))
db = mongo["discord_bot"]
settings_col = db["guild_settings"]
logs_col = db["logs"]
economy_col = db["economy"]
mod_col = db["moderation"]
afk_col = db["afk"]
vanity_col = db["vanityroles"]
sticky_col = db["stickynotes"]
reaction_col = db["reactionroles"]

try:
    print("Loading bot...")
    TOKEN = os.environ["DISCORD_TOKEN"]
    print("Token loaded.")
except Exception as e:
    print("Failed to load TOKEN:", e)

print("Top of main.py reached")

fishes = [
    ("🦐 Shrimp", 100),
    ("🐟 Fish", 200),
    ("🐠 Tropical Fish", 300),
    ("🦑 Squid", 400),
    ("🐡 Pufferfish", 500)
]

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix=lambda bot, msg: settings_col.find_one({"guild": str(msg.guild.id)})["prefix"] if msg.guild and settings_col.find_one({"guild": str(msg.guild.id)}) else "?",
    intents=intents,
    strip_after_prefix=True
)

bot_locks = {}

@bot.check
async def global_lock_check(ctx):
    if bot_locks.get(str(ctx.guild.id)):
        await ctx.send("🔒 bot is locked — only `override` by theofficialtruck works")
        return False
    return True

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"
    
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# 2. UTIL FUNCTIONS ===========================================
def staff_only():
    def predicate(ctx):
        doc = settings_col.find_one({"guild": str(ctx.guild.id)})
        role_id = doc.get("staff_role") if doc else None
        if not role_id:
            return False
        role = discord.utils.get(ctx.guild.roles, id=role_id)
        return role in ctx.author.roles if role else False
    return commands.check(predicate)

async def get_user(guild_id, user_id):
    key = f"{guild_id}-{user_id}"
    u = economy_col.find_one({"_id": key})
    if not u:
        economy_col.insert_one({"_id": key, "guild": str(guild_id), "user": str(user_id), "wallet": 0, "bank": 0, "inventory": []})
        return economy_col.find_one({"_id": key})
    return u

def convert_time(s): 
    try: return int(s[:-1]) * {"s":1,"m":60,"h":3600,"d":86400}[s[-1]]
    except: return None
        
async def resolve_member(ctx, arg):
    try:
        return await commands.MemberConverter().convert(ctx, arg)
    except:
        try:
            return await ctx.guild.fetch_member(int(arg.strip("<@!>")))
        except:
            return None
            
def check_target_permission(ctx, member: discord.Member):
    if member == ctx.author:
        return "❌ You can't perform this action on yourself."
    if member == ctx.guild.owner:
        return "❌ You can't perform this action on the server owner."
    if ctx.author.top_role <= member.top_role and ctx.author != ctx.guild.owner:
        return "❌ You can't perform this action on someone with an equal or higher role."
    return None
    
async def get_prefix(bot, message):
    if not message.guild:
        return "?"
    doc = settings_col.find_one({"guild": str(message.guild.id)})
    return doc.get("prefix", "?") if doc else "?"
    
async def log_action(ctx, message, user_id=None, action_type=None):
    try:
        guild_id = str(ctx.guild.id)
        log_channel_id = None

        settings = settings_col.find_one({"guild": guild_id})
        if settings:
            log_channel_id = settings.get("log_channel")

        # send log message to the discord channel
        if log_channel_id:
            log_channel = bot.get_channel(log_channel_id)
            if log_channel:
                timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
                embed = discord.Embed(
                    title="📋 Moderation Log",
                    description=message,
                    color=discord.Color.dark_blue(),
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text=f"By {ctx.author} • {ctx.author.id}")
                await log_channel.send(embed=embed)

        # save to mongo log database
        if user_id and action_type:
            log_doc = {
                "guild": guild_id,
                "user_id": str(user_id),
                "action": action_type,
                "by": {
                    "name": str(ctx.author),
                    "id": str(ctx.author.id)
                },
                "message": message,
                "timestamp": datetime.utcnow().isoformat()
            }
            logs_col.insert_one(log_doc)

    except Exception as e:
        print(f"[log_action ERROR] {e}")

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
        
# 3. COMMANDS =================================================
@bot.command()
@commands.guild_only()
async def staffset(ctx, role: discord.Role):
    settings_col.update_one({"guild": str(ctx.guild.id)}, {"$set": {"staff_role": role.id}}, upsert=True)
    await ctx.send(f"✅ Staff role set to {role.mention}.")
    await log_action(ctx, f"Staff role set to {role}", action_type="staffset")

@bot.command()
@commands.guild_only()
async def staffget(ctx):
    doc = settings_col.find_one({"guild": str(ctx.guild.id)})
    role = ctx.guild.get_role(doc.get("staff_role")) if doc else None
    if role:
        await ctx.send(f"ℹ️ Staff role is {role.mention}.")
    else:
        await ctx.send("⚠️ No staff role is currently set.")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def vanityroles(ctx, role: discord.Role, log_channel: discord.TextChannel, *, keyword: str):
    guild = str(ctx.guild.id)
    vanity_col.update_one({"guild": guild}, {"$set": {"role": role.id, "log": log_channel.id, "keyword": keyword, "users": []}}, upsert=True)
    await ctx.send(f"✅ set vanity role for '{keyword}' → {role.mention}")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def promoters(ctx):
    data = vanity_col.find_one({"guild": str(ctx.guild.id)})
    users = data.get("users", []) if data else []
    mentions = [ctx.guild.get_member(uid).mention for uid in users if ctx.guild.get_member(uid)]
    await ctx.send(embed=discord.Embed(title="📢 current promoters", description="\n".join(mentions) or "none", color=discord.Color.blue()))

@bot.command()
@commands.has_permissions(manage_roles=True)
async def resetpromoters(ctx):
    guild = str(ctx.guild.id)
    data = vanity_col.find_one({"guild": guild})
    if not data:
        return await ctx.send("❌ no vanity config set")
    await ctx.send("⚠️ confirm by typing exactly:\n`I confirm I want to reset all the promoters.`")
    try:
        msg = await bot.wait_for("message", check=lambda m: m.author==ctx.author and m.channel==ctx.channel, timeout=30)
    except asyncio.TimeoutError:
        return await ctx.send("❌ timeout — cancelled")
    if msg.content.strip() != "I confirm I want to reset all the promoters.":
        return await ctx.send("❌ confirmation failed — cancelled")
    r = ctx.guild.get_role(data["role"])
    removed = 0
    for uid in data["users"]:
        m = ctx.guild.get_member(uid)
        if m and r in m.roles:
            await m.remove_roles(r, reason="reset promoters")
            removed += 1
    vanity_col.update_one({"guild": guild}, {"$set": {"users": []}})
    await ctx.send(embed=discord.Embed(title="🔁 promoters reset", description=f"{removed} removed, list cleared", color=discord.Color.red()))

@bot.event
async def on_presence_update(before, after):
    if not after.guild or after.bot:
        return
    data = vanity_col.find_one({"guild": str(after.guild.id)})
    if not data: return
    kw = data["keyword"].lower()
    status = str(after.activity.name or "").lower()
    role = after.guild.get_role(data["role"])
    log = after.guild.get_channel(data["log"])
    has = role in after.roles
    if kw in status and not has:
        await after.add_roles(role, reason="vanity match")
        vanity_col.update_one({"guild": str(after.guild.id)}, {"$addToSet": {"users": after.id}})
        await log.send(embed=discord.Embed(title="🎉 granted", description=f"{after.mention} got {role.mention}", color=discord.Color.green()))
    elif kw not in status and has:
        await after.remove_roles(role, reason="vanity lost")
        vanity_col.update_one({"guild": str(after.guild.id)}, {"$pull": {"users": after.id}})

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
    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"wallet": new_balance, "last_daily": now.isoformat()}}
    )
    await ctx.send("✅ You claimed your daily reward of 500 coins!")
    
@bot.command()
async def work(ctx):
    data = await get_user(ctx.guild.id, ctx.author.id)
    now = datetime.utcnow()
    last = data.get("last_work")

    if last and now - datetime.fromisoformat(last) < timedelta(minutes=30):
        rem = timedelta(minutes=30) - (now - datetime.fromisoformat(last))
        return await ctx.send(f"🕒 You can work again in {rem.seconds//60} minutes")

    if "laptop" not in data["inventory"]:
        return await ctx.send("💻 You need a laptop to work! Buy one with `?buy laptop`.")

    earnings = 300
    new_wallet = data["wallet"] + earnings
    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"wallet": new_wallet, "last_work": now.isoformat()}}
    )
    await ctx.send(f"💼 You worked and earned {earnings} coins!")
    
@bot.command()
async def beg(ctx):
    data = await get_user(ctx.guild.id, ctx.author.id)
    now = datetime.utcnow()
    last = data.get("last_beg")

    if last and now - datetime.fromisoformat(last) < timedelta(minutes=15):
        rem = timedelta(minutes=15) - (now - datetime.fromisoformat(last))
        return await ctx.send(f"🕒 You can beg again in {rem.seconds//60} minutes")

    amount = random.randint(50, 200)
    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"wallet": data["wallet"] + amount, "last_beg": now.isoformat()}}
    )
    await ctx.send(f"🙇 You begged and received {amount} coins!")
    
@bot.command(aliases=["dep"])
async def deposit(ctx, amount: int):
    data = await get_user(ctx.guild.id, ctx.author.id)
    if amount <= 0 or amount > data["wallet"]:
        return await ctx.send("❌ Invalid deposit amount.")

    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {
            "wallet": data["wallet"] - amount,
            "bank": data["bank"] + amount
        }}
    )
    await ctx.send(f"🏦 You deposited {amount} coins.")
    
@bot.command(aliases=["with"])
async def withdraw(ctx, amount: int):
    data = await get_user(ctx.guild.id, ctx.author.id)
    if amount <= 0 or amount > data["bank"]:
        return await ctx.send("❌ Invalid withdrawal amount.")

    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {
            "wallet": data["wallet"] + amount,
            "bank": data["bank"] - amount
        }}
    )
    await ctx.send(f"💰 You withdrew {amount} coins.")
    
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
async def buy(ctx, item: str):
    item = item.lower()
    store_item = db["shop"].find_one({"_id": item})
    if not store_item:
        return await ctx.send("❌ Item not found.")

    data = await get_user(ctx.guild.id, ctx.author.id)
    if data["wallet"] < store_item["price"]:
        return await ctx.send("❌ Not enough coins.")

    data["wallet"] -= store_item["price"]
    data["inventory"].append(item)

    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {
            "wallet": data["wallet"],
            "inventory": data["inventory"]
        }}
    )
    await ctx.send(f"✅ You bought a {item}!")
    
@bot.command(aliases=["inv"])
async def inventory(ctx):
    data = await get_user(ctx.guild.id, ctx.author.id)
    inv = data.get("inventory", [])

    if not inv:
        return await ctx.send("🎒 Your inventory is empty.")

    counts = {}
    for item in inv:
        counts[item] = counts.get(item, 0) + 1

    description = "\n".join(f"{name.capitalize()} x{count}" for name, count in counts.items())
    embed = discord.Embed(title=f"{ctx.author.display_name}'s Inventory", description=description, color=discord.Color.purple())
    await ctx.send(embed=embed)
    
@bot.command(aliases=["pay"])
async def give(ctx, member: discord.Member, amount: int):
    if member == ctx.author or amount <= 0:
        return await ctx.send("❌ Invalid transaction.")

    sender = await get_user(ctx.guild.id, ctx.author.id)
    receiver = await get_user(ctx.guild.id, member.id)

    if sender["wallet"] < amount:
        return await ctx.send("❌ You don't have enough coins.")

    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"wallet": sender["wallet"] - amount}}
    )
    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{member.id}"},
        {"$set": {"wallet": receiver["wallet"] + amount}}
    )
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
    
@bot.command()
async def gamble(ctx, amount: int):
    data = await get_user(ctx.guild.id, ctx.author.id)

    if amount <= 0 or amount > data["wallet"]:
        return await ctx.send("❌ Invalid amount to gamble.")

    # add effects/boosts here
    win_chance = 0.5
    won = random.random() < win_chance

    new_wallet = data["wallet"] + amount if won else data["wallet"] - amount
    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"wallet": new_wallet}}
    )

    if won:
        await ctx.send(f"🎉 You won {amount} coins from gambling!")
    else:
        await ctx.send(f"💸 You lost {amount} coins from gambling.")

@bot.command()
async def fish(ctx):
    data = await get_user(ctx.guild.id, ctx.author.id)

    if "fishing_rod" not in data["inventory"]:
        return await ctx.send("🎣 You need a fishing rod to fish! Buy one with `?buy fishing_rod`.")

    catch = random.choice(fishes)
    data["wallet"] += catch[1]

    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"wallet": data["wallet"]}}
    )

    await ctx.send(f"🎣 You caught a {catch[0]} and earned {catch[1]} coins!")
    
@bot.command(aliases=["steal"])
async def rob(ctx, member: discord.Member):
    if member == ctx.author:
        return await ctx.send("❌ You can't rob yourself!")

    robber = await get_user(ctx.guild.id, ctx.author.id)
    victim = await get_user(ctx.guild.id, member.id)

    if robber["wallet"] < 500:
        return await ctx.send("❌ You need at least 500 coins to attempt a robbery.")
    if victim["wallet"] < 300:
        return await ctx.send("❌ That user doesn't have enough coins to be robbed.")

    amount = random.randint(100, min(500, victim["wallet"], robber["wallet"]))
    robber["wallet"] += amount
    victim["wallet"] -= amount

    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"wallet": robber["wallet"]}}
    )
    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{member.id}"},
        {"$set": {"wallet": victim["wallet"]}}
    )

    await ctx.send(f"💰 You robbed {member.display_name} and stole {amount} coins!")
    
@bot.command()
async def use(ctx, item: str):
    item = item.lower()
    data = await get_user(str(ctx.guild.id), str(ctx.author.id))
    inv = data.get("inventory", [])
    if item not in inv:
        return await ctx.send(f"❌ You don't have a {item} in your inventory.")

    if item == "fishing_rod":
        await ctx.send("🎣 You use your fishing rod to fish faster!")
    elif item == "laptop":
        await ctx.send("💻 You use your laptop to earn extra coins next time you work!")
    
    else:
        await ctx.send(f"✅ You used a {item}, but nothing special happened.")

    inv.remove(item)
    economy_col.update_one(
        {"_id": f"{ctx.guild.id}-{ctx.author.id}"},
        {"$set": {"inventory": inv}}
    )
    
# Kick a member
@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    err = check_target_permission(ctx, member)
    if err: return await ctx.send(err)
    await member.kick(reason=f"{reason} (by {ctx.author})")
    await ctx.send(f"✅ {member.mention} has been kicked.")
    await log_action(ctx, f"Kicked {member} for: {reason}", user_id=member.id, action_type="kick")

# Ban a member
@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    err = check_target_permission(ctx, member)
    if err: return await ctx.send(err)
    await member.ban(reason=f"{reason} (by {ctx.author})")
    await ctx.send(f"✅ {member.mention} has been banned.")
    await log_action(ctx, f"Banned {member} for: {reason}", user_id=member.id, action_type="ban")

# Unban a user by ID
@bot.command()
@commands.has_permissions(ban_members=True)
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
@commands.has_permissions(manage_roles=True)
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
@commands.has_permissions(manage_roles=True)
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
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    mod_col.update_one(
        {"guild": str(ctx.guild.id), "user": str(member.id)},
        {"$push": {"warnings": {"by": str(ctx.author), "reason": reason, "time": datetime.utcnow().isoformat()}}},
        upsert=True
    )
    await ctx.send(f"⚠️ {member.mention} has been warned: {reason}")
    await log_action(ctx, f"Warned {member} for: {reason}", user_id=member.id, action_type="warn")

# Clear warnings for a member
@bot.command()
@commands.has_permissions(manage_messages=True)
async def clearwarns(ctx, member: discord.Member):
    mod_col.update_one({"guild": str(ctx.guild.id), "user": str(member.id)}, {"$set": {"warnings": []}})
    await ctx.send(f"✅ All warnings for {member.mention} have been cleared.")
    await log_action(ctx, f"Cleared warnings for {member}", user_id=member.id, action_type="clearwarns")
    
# Purge messages
@bot.command()
@commands.has_permissions(manage_messages=True)
async def purge(ctx, count: int, member: discord.Member = None):
    def check(m):
        return m.author == member if member else True
    deleted = await ctx.channel.purge(limit=count+1, check=check)
    await ctx.send(f"🧹 Deleted {len(deleted)-1} messages.", delete_after=5)
    await log_action(ctx, f"Purged {len(deleted)-1} messages{(' from '+member.display_name) if member else ''}", action_type="purge")
    
# Slowmode command
@bot.command()
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):
    await ctx.channel.edit(slowmode_delay=seconds)
    await ctx.send(f"✅ Slowmode set to {seconds} seconds.")
    await log_action(ctx, f"Set slowmode to {seconds}s in #{ctx.channel.name}", action_type="slowmode")
    
# Set prefix for this server
@bot.command()
@commands.has_permissions(manage_guild=True)
async def setprefix(ctx, new: str):
    settings_col.update_one({"guild": str(ctx.guild.id)}, {"$set": {"prefix": new}}, upsert=True)
    await ctx.send(f"✅ Prefix updated to `{new}`.")
    await log_action(ctx, f"Prefix changed to {new}", action_type="setprefix")

# Set log channel for moderation
@bot.command()
@commands.has_permissions(manage_guild=True)
async def logchannel(ctx, channel: discord.TextChannel):
    settings_col.update_one({"guild": str(ctx.guild.id)}, {"$set": {"log_channel": channel.id}}, upsert=True)
    await ctx.send(f"✅ Log channel set to {channel.mention}.")
    await log_action(ctx, f"Log channel set to {channel}", action_type="logchannel")
    
# User Info
@bot.command()
@commands.has_permissions(manage_guild=True)
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    join = member.joined_at.strftime("%Y-%m-%d")
    created = member.created_at.strftime("%Y-%m-%d")
    doc = mod_col.find_one({"guild": str(ctx.guild.id), "user": str(member.id)})
    warns = len(doc.get("warnings", [])) if doc else 0
    embed = discord.Embed(title="User Information", color=discord.Color.blurple())
    embed.set_thumbnail(url=member.avatar.url if member.avatar else "")
    embed.add_field(name="ID", value=member.id)
    embed.add_field(name="Joined Server", value=join)
    embed.add_field(name="Account Created", value=created)
    embed.add_field(name="Warnings", value=warns)
    await ctx.send(embed=embed)
    
@bot.command()
@commands.has_permissions(manage_messages=True)
async def reactionrole(ctx, message_id: int, emoji, role: discord.Role):
    try:
        msg = await ctx.channel.fetch_message(message_id)
        await msg.add_reaction(emoji)
        reaction_col.update_one({"message": message_id}, {"$set": {"emoji": str(emoji), "role": role.id}}, upsert=True)
        await ctx.send(f"✅ Reaction role set: {emoji} will grant {role.mention}.")
    except:
        await ctx.send("❌ Could not set reaction role. Check your permissions and message ID.")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def stickynote(ctx):
    await ctx.send("📝 Please type the message to pin as sticky:")
    def check(m): return m.author == ctx.author and m.channel == ctx.channel
    try:
        reply = await bot.wait_for("message", check=check, timeout=60)
        sent = await ctx.send(reply.content)
        sticky_col.update_one({"guild": str(ctx.guild.id), "channel": str(ctx.channel.id)},
                              {"$set": {"text": reply.content, "message": sent.id}}, upsert=True)
        await ctx.send("✅ Sticky note created.")
    except asyncio.TimeoutError:
        await ctx.send("❌ Timeout. Sticky note creation cancelled.")

@bot.command()
@commands.has_permissions(manage_channels=True)
async def unstickynote(ctx):
    doc = sticky_col.find_one({"guild": str(ctx.guild.id), "channel": str(ctx.channel.id)})
    if doc:
        try:
            msg = await ctx.channel.fetch_message(doc["message"])
            await msg.delete()
        except: pass
        sticky_col.delete_one({"guild": str(ctx.guild.id), "channel": str(ctx.channel.id)})
        await ctx.send("✅ Sticky note removed.")
    else:
        await ctx.send("⚠️ No sticky note set for this channel.")
        
@bot.command()
async def serverinfo(ctx):
    await ctx.send(f"Server: {ctx.guild.name}\n👥 Members: {ctx.guild.member_count}\n🆔 ID: {ctx.guild.id}")
    
@bot.command()
async def cmds(ctx):
    doc = settings_col.find_one({"guild": str(ctx.guild.id)})
    staff_role = ctx.guild.get_role(doc.get("staff_role")) if doc else None
    is_staff = staff_role in ctx.author.roles if staff_role else False

    # GENERAL COMMANDS
    general = discord.Embed(title="💬 General Commands", color=discord.Color.blurple())
    general.add_field(name="?serverinfo", value="View server information", inline=False)
    general.add_field(name="?cmds", value="Show this help menu", inline=False)
    general.add_field(name="?afk [reason]", value="Set your AFK status", inline=False)

    # ECONOMY COMMANDS
    economy = discord.Embed(title="💰 Economy Commands", color=discord.Color.green())
    economy.add_field(name="?balance / ?bal", value="Check your balance", inline=False)
    economy.add_field(name="?daily", value="Claim your daily reward", inline=False)
    economy.add_field(name="?work", value="Work to earn coins", inline=False)
    economy.add_field(name="?beg", value="Beg for coins", inline=False)
    economy.add_field(name="?deposit / ?dep <amount>", value="Deposit to bank", inline=False)
    economy.add_field(name="?withdraw / ?with <amount>", value="Withdraw from bank", inline=False)
    economy.add_field(name="?shop", value="View the shop", inline=False)
    economy.add_field(name="?buy <item>", value="Buy an item from the shop", inline=False)
    economy.add_field(name="?use <item>", value="Use an item from your inventory", inline=False)
    economy.add_field(name="?inventory / ?inv", value="View your items", inline=False)
    economy.add_field(name="?give / ?pay @user <amount>", value="Give coins to another user", inline=False)
    economy.add_field(name="?leaderboard / ?lb", value="View the top users", inline=False)
    economy.add_field(name="?gamble <amount>", value="Gamble your coins", inline=False)
    economy.add_field(name="?fish", value="Go fishing to earn coins", inline=False)
    economy.add_field(name="?rob / ?steal @user", value="Attempt to rob another user", inline=False)

    pages = [general, economy]

    if is_staff:
        staff = discord.Embed(title="🛠️ Staff Commands", color=discord.Color.dark_red())
        staff.add_field(name="?kick @user [reason]", value="Kick a member", inline=False)
        staff.add_field(name="?ban @user [reason]", value="Ban a member", inline=False)
        staff.add_field(name="?unban <user_id>", value="Unban a user", inline=False)
        staff.add_field(name="?mute @user <time> [reason]", value="Mute a user temporarily", inline=False)
        staff.add_field(name="?unmute @user", value="Unmute a user", inline=False)
        staff.add_field(name="?purge <count> [@user]", value="Bulk delete messages", inline=False)
        staff.add_field(name="?warn @user [reason]", value="Warn a user", inline=False)
        staff.add_field(name="?clearwarns @user", value="Clear all warnings", inline=False)
        staff.add_field(name="?slowmode <seconds>", value="Set slowmode for this channel", inline=False)
        staff.add_field(name="?setprefix <prefix>", value="Change the bot prefix", inline=False)
        staff.add_field(name="?logchannel #channel", value="Set the moderation log channel", inline=False)
        staff.add_field(name="?reactionrole <msg_id> <emoji> @role", value="Set up a reaction role", inline=False)
        staff.add_field(name="?stickynote", value="Set a sticky note in this channel", inline=False)
        staff.add_field(name="?unstickynote", value="Remove the sticky note", inline=False)
        staff.add_field(name="?setwelcome #channel", value="Set the welcome channel", inline=False)
        staff.add_field(name="?setboost #channel", value="Set the boost message channel", inline=False)
        staff.add_field(name="?testwelcome [@user]", value="Send a test welcome message", inline=False)
        staff.add_field(name="?testboost [@user]", value="Send a test boost message", inline=False)
        staff.add_field(name="?staffset @role", value="Set the staff role", inline=False)
        staff.add_field(name="?staffget", value="Show the configured staff role", inline=False)
        staff.add_field(name="?userinfo [@user]", value="View detailed user info", inline=False)
        staff.add_field(name="?vanityroles @role #logchannel <status>", value="Track users with keyword in status", inline=False)
        staff.add_field(name="?promoters", value="View users with the vanity role", inline=False)
        staff.add_field(name="?resetpromoters", value="Clear all users from the vanity role", inline=False)
        pages.append(staff)

    view = CommandPages(pages)
    await ctx.send(embed=pages[0], view=view)

@bot.command()
async def stop(ctx):
    bot_locks[str(ctx.guild.id)] = True
    await ctx.send("🔒 bot locked. use 'override' by theofficialtruck to unlock.")

@bot.command()
async def override(ctx):
    if str(ctx.author) == "theofficialtruck":
        bot_locks[str(ctx.guild.id)] = False
        await ctx.send("🚀 bot unlocked!")
    else:
        await ctx.send("❌ you don't have permission.")

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="theofficialtruck"))
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"❌ Slash command sync failed: {e}")
    print(f"Logged in as {bot.user}")

if __name__ == "__main__":
    import keep_alive
    keep_alive.keep_alive()
    
    print("🔁 Attempting to connect to Discord...")
    bot.run(TOKEN)