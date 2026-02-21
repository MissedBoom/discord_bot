import discord
from discord.ext import commands
import json
import os
import asyncio

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

import asyncio

# Nom du channel admin
ADMIN_CHANNEL = "erreur-result"

# Dictionnaire pour stocker les duels actifs
active_duels = {}

# Vue pour les boutons du duel
class DuelView(discord.ui.View):
    def __init__(self, challenger, opponent):
        super().__init__(timeout=60)
        self.challenger = challenger
        self.opponent = opponent

    @discord.ui.button(label="Accepter ⚔️", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            await interaction.response.send_message("Ce duel ne te concerne pas !", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            self.challenger: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            self.opponent: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        channel = await guild.create_text_channel(
            f"duel-{self.challenger.display_name}-vs-{self.opponent.display_name}",
            overwrites=overwrites
        )

        active_duels[channel.id] = {
            "challenger": self.challenger,
            "opponent": self.opponent,
            "votes": {}
        }

        await interaction.response.send_message(f"✅ Duel accepté ! Rendez-vous dans {channel.mention} !")
        await channel.send(
            f"⚔️ **Duel : {self.challenger.mention} VS {self.opponent.mention}**\n\n"
            f"Que le meilleur gagne ! Quand le duel est terminé, tapez `!result` pour déclarer le résultat."
        )

    @discord.ui.button(label="Refuser ❌", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.opponent:
            await interaction.response.send_message("Ce duel ne te concerne pas !", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message(f"❌ **{self.opponent.display_name}** a refusé le combat.")

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# Vue pour les boutons du résultat
class ResultView(discord.ui.View):
    def __init__(self, challenger, opponent, duel_channel):
        super().__init__(timeout=120)
        self.challenger = challenger
        self.opponent = opponent
        self.duel_channel = duel_channel
        self.votes = {}  # {user_id: "challenger" | "opponent" | "draw"}

    async def process_votes(self, interaction):
        # Attendre que les deux aient voté
        if len(self.votes) < 2:
            await interaction.response.send_message(
                f"✅ Vote enregistré ! En attente du vote de l'autre joueur...",
                ephemeral=True
            )
            return

        # Désactiver les boutons
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        vote_challenger = self.votes.get(str(self.challenger.id))
        vote_opponent = self.votes.get(str(self.opponent.id))

        scores = load_scores()

        # Les deux votes sont identiques
        if vote_challenger == vote_opponent:
            if vote_challenger == "draw":
                await interaction.response.send_message(
                    "🤝 **Match nul validé par les deux joueurs !** Aucun point gagné ni perdu."
                )
            else:
                # Déterminer gagnant et perdant
                if vote_challenger == "challenger":
                    winner = self.challenger
                    loser = self.opponent
                else:
                    winner = self.opponent
                    loser = self.challenger

                winner_id = str(winner.id)
                loser_id = str(loser.id)
                scores[winner_id] = scores.get(winner_id, 0) + 10
                scores[loser_id] = max(0, scores.get(loser_id, 0) - 10)
                save_scores(scores)

                await interaction.response.send_message(
                    f"🏆 **{winner.mention}** remporte le duel !\n"
                    f"➕ **+10 points** pour {winner.display_name} ({scores[winner_id]} pts)\n"
                    f"➖ **-10 points** pour {loser.display_name} ({scores[loser_id]} pts)\n\n"
                    f"Channel supprimé dans 5 secondes..."
                )

            await asyncio.sleep(5)
            del active_duels[self.duel_channel.id]
            await self.duel_channel.delete()

        # Les votes sont différents → litige
        else:
            admin_channel = discord.utils.get(interaction.guild.text_channels, name=ADMIN_CHANNEL)

            await interaction.response.send_message(
                "⚠️ **Les résultats ne correspondent pas !** Un admin va trancher. Le channel reste ouvert."
            )

            if admin_channel:
                await admin_channel.send(
                    f"⚠️ **Litige de duel !**\n"
                    f"Channel : {self.duel_channel.mention}\n"
                    f"**{self.challenger.display_name}** a voté : `{vote_challenger}`\n"
                    f"**{self.opponent.display_name}** a voté : `{vote_opponent}`\n\n"
                    f"Utilisez `!winner @joueur` ou `!draw` dans le channel du duel pour trancher."
                )

    @discord.ui.button(label="J'ai gagné 🏆", style=discord.ButtonStyle.success)
    async def i_won(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in [self.challenger, self.opponent]:
            await interaction.response.send_message("Tu ne fais pas partie de ce duel !", ephemeral=True)
            return
        if str(interaction.user.id) in self.votes:
            await interaction.response.send_message("Tu as déjà voté !", ephemeral=True)
            return

        # Le joueur vote pour lui-même
        if interaction.user == self.challenger:
            self.votes[str(self.challenger.id)] = "challenger"
        else:
            self.votes[str(self.opponent.id)] = "opponent"

        active_duels[self.duel_channel.id]["votes"] = self.votes
        await self.process_votes(interaction)

    @discord.ui.button(label="J'ai perdu 💀", style=discord.ButtonStyle.danger)
    async def i_lost(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in [self.challenger, self.opponent]:
            await interaction.response.send_message("Tu ne fais pas partie de ce duel !", ephemeral=True)
            return
        if str(interaction.user.id) in self.votes:
            await interaction.response.send_message("Tu as déjà voté !", ephemeral=True)
            return

        # Le joueur vote contre lui-même (donc pour l'autre)
        if interaction.user == self.challenger:
            self.votes[str(self.challenger.id)] = "opponent"
        else:
            self.votes[str(self.opponent.id)] = "challenger"

        active_duels[self.duel_channel.id]["votes"] = self.votes
        await self.process_votes(interaction)

    @discord.ui.button(label="Égalité 🤝", style=discord.ButtonStyle.secondary)
    async def draw(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in [self.challenger, self.opponent]:
            await interaction.response.send_message("Tu ne fais pas partie de ce duel !", ephemeral=True)
            return
        if str(interaction.user.id) in self.votes:
            await interaction.response.send_message("Tu as déjà voté !", ephemeral=True)
            return

        self.votes[str(interaction.user.id)] = "draw"
        active_duels[self.duel_channel.id]["votes"] = self.votes
        await self.process_votes(interaction)


# --- COMMANDES DUEL ---

@bot.command()
async def duel(ctx, opponent: discord.Member):
    """Lance un défi à un autre joueur"""
    if ctx.channel.name != "duel":
        await ctx.send("❌ Cette commande ne peut être utilisée que dans le salon **#duel** !", delete_after=5)
        return
    if opponent == ctx.author:
        await ctx.send("Tu ne peux pas te défier toi-même !")
        return
    if opponent.bot:
        await ctx.send("Tu ne peux pas défier un bot !")
        return

    view = DuelView(ctx.author, opponent)
    await ctx.send(
        f"⚔️ **{ctx.author.mention} défie {opponent.mention} en duel !**\n"
        f"{opponent.mention}, acceptes-tu le combat ?",
        view=view
    )

@bot.command()
async def result(ctx):
    """Lance le vote du résultat dans un channel de duel"""
    if ctx.channel.id not in active_duels:
        await ctx.send("Cette commande ne peut être utilisée que dans un channel de duel !")
        return

    duel = active_duels[ctx.channel.id]
    view = ResultView(duel["challenger"], duel["opponent"], ctx.channel)
    await ctx.send(
        f"📊 **Résultat du duel — {duel['challenger'].mention} VS {duel['opponent'].mention}**\n"
        f"Chaque joueur vote honnêtement. En cas de désaccord, un admin sera notifié.",
        view=view
    )

@bot.command()
@commands.has_permissions(administrator=True)
async def winner(ctx, member: discord.Member):
    """(Admin) Déclare le vainqueur en cas de litige"""
    if ctx.channel.id not in active_duels:
        await ctx.send("Cette commande ne peut être utilisée que dans un channel de duel !")
        return

    duel = active_duels[ctx.channel.id]
    if member not in [duel["challenger"], duel["opponent"]]:
        await ctx.send("Ce joueur ne fait pas partie de ce duel !")
        return

    loser = duel["opponent"] if member == duel["challenger"] else duel["challenger"]
    scores = load_scores()
    scores[str(member.id)] = scores.get(str(member.id), 0) + 10
    scores[str(loser.id)] = max(0, scores.get(str(loser.id), 0) - 10)
    save_scores(scores)

    await ctx.send(
        f"⚖️ **Décision admin : {member.mention} remporte le duel !**\n"
        f"➕ +10 pts pour {member.display_name} | ➖ -10 pts pour {loser.display_name}\n"
        f"Channel supprimé dans 5 secondes..."
    )
    await asyncio.sleep(5)
    del active_duels[ctx.channel.id]
    await ctx.channel.delete()

@bot.command(name="draw")
@commands.has_permissions(administrator=True)
async def admin_draw(ctx):
    """(Admin) Déclare un match nul en cas de litige"""
    if ctx.channel.id not in active_duels:
        await ctx.send("Cette commande ne peut être utilisée que dans un channel de duel !")
        return

    await ctx.send(
        f"⚖️ **Décision admin : Match nul !** Aucun point modifié.\n"
        f"Channel supprimé dans 5 secondes..."
    )
    await asyncio.sleep(5)
    del active_duels[ctx.channel.id]
    await ctx.channel.delete()

@bot.command(name="help")
async def help_command(ctx):
    """Affiche la liste des commandes disponibles"""
    embed = discord.Embed(title="📖 Commandes disponibles", color=0x5865f2)
    
    embed.add_field(
        name="🎮 Commandes joueurs",
        value=(
            "`!duel @joueur` — Défier un joueur (dans #duel uniquement)\n"
            "`!leaderboard` — Afficher le classement\n"
            "`!points @joueur` — Voir les points d'un joueur\n"
            "`!result` — Déclarer le résultat d'un duel (dans le channel du duel)"
        ),
        inline=False
    )

    if ctx.author.guild_permissions.administrator:
        embed.add_field(
            name="🔒 Commandes admin",
            value=(
                "`!addpoints @joueur X` — Ajouter des points\n"
                "`!removepoints @joueur X` — Retirer des points\n"
                "`!reset @joueur` — Remettre un joueur à zéro\n"
                "`!winner @joueur` — Déclarer un vainqueur (litige)\n"
                "`!draw` — Déclarer un match nul (litige)"
            ),
            inline=False
        )

    embed.set_footer(text="Tape !help pour revoir cette liste")
    await ctx.send(embed=embed)
    
bot.run(TOKEN)
