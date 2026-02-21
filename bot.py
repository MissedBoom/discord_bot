import discord
from discord.ext import commands
import json
import os

# Configuration
TOKEN = os.getenv("TOKEN")  # Remplace par ton token
PREFIX = "!"

# Chargement des données
def load_scores():
    if os.path.exists("scores.json"):
        with open("scores.json", "r") as f:
            return json.load(f)
    return {}

def save_scores(scores):
    with open("scores.json", "w") as f:
        json.dump(scores, f, indent=4)

# Initialisation du bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Bot connecté en tant que {bot.user}")

# --- COMMANDES ---

@bot.command()
@commands.has_permissions(administrator=True)
async def addpoints(ctx, member: discord.Member, points: int):
    """Ajoute des points à un joueur"""
    scores = load_scores()
    user_id = str(member.id)
    scores[user_id] = scores.get(user_id, 0) + points
    save_scores(scores)
    await ctx.send(f"✅ **{member.display_name}** a reçu **{points} points** ! Total : {scores[user_id]} pts")

@bot.command()
@commands.has_permissions(administrator=True)
async def removepoints(ctx, member: discord.Member, points: int):
    """Retire des points à un joueur"""
    scores = load_scores()
    user_id = str(member.id)
    scores[user_id] = max(0, scores.get(user_id, 0) - points)
    save_scores(scores)
    await ctx.send(f"✅ **{member.display_name}** a perdu **{points} points** ! Total : {scores[user_id]} pts")

@bot.command()
async def points(ctx, member: discord.Member = None):
    """Affiche les points d'un joueur"""
    if member is None:
        member = ctx.author
    scores = load_scores()
    user_id = str(member.id)
    total = scores.get(user_id, 0)
    await ctx.send(f"🎮 **{member.display_name}** a **{total} points**")

@bot.command()
async def leaderboard(ctx):
    """Affiche le classement"""
    scores = load_scores()
    if not scores:
        await ctx.send("Aucun score enregistré pour l'instant !")
        return
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"]
    embed = discord.Embed(title="🏆 Classement", color=0x5865f2)
    description = ""
    for i, (user_id, score) in enumerate(sorted_scores):
        medal = medals[i] if i < 3 else f"**#{i+1}**"
        try:
            user = await bot.fetch_user(int(user_id))
            name = user.display_name
        except:
            name = f"Joueur inconnu"
        description += f"{medal} {name} — {score} pts\n"
    embed.description = description
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def reset(ctx, member: discord.Member):
    """Remet les points d'un joueur à zéro"""
    scores = load_scores()
    scores[str(member.id)] = 0
    save_scores(scores)
    await ctx.send(f"🔄 Les points de **{member.display_name}** ont été remis à zéro.")

bot.run(TOKEN)
