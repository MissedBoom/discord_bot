import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import asyncio

# Configuration
TOKEN = os.getenv("TOKEN")
ADMIN_CHANNEL = "erreur-result"
DUEL_CHANNEL = "duel"

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
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Dictionnaire pour stocker les duels actifs
active_duels = {}

# ─────────────────────────────────────────────
# VIEWS
# ─────────────────────────────────────────────

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
            f"Que le meilleur gagne ! Quand le duel est terminé, tapez `/result` pour déclarer le résultat."
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


class ResultView(discord.ui.View):
    def __init__(self, challenger, opponent, duel_channel):
        super().__init__(timeout=120)
        self.challenger = challenger
        self.opponent = opponent
        self.duel_channel = duel_channel
        self.votes = {}

    async def process_votes(self, interaction):
        if len(self.votes) < 2:
            await interaction.response.send_message(
                "✅ Vote enregistré ! En attente du vote de l'autre joueur...",
                ephemeral=True
            )
            return

        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

        vote_challenger = self.votes.get(str(self.challenger.id))
        vote_opponent = self.votes.get(str(self.opponent.id))
        scores = load_scores()

        if vote_challenger == vote_opponent:
            if vote_challenger == "draw":
                await interaction.response.send_message(
                    "🤝 **Match nul validé par les deux joueurs !** Aucun point gagné ni perdu.\nChannel supprimé dans 5 secondes..."
                )
            else:
                winner = self.challenger if vote_challenger == "challenger" else self.opponent
                loser = self.opponent if vote_challenger == "challenger" else self.challenger
                scores[str(winner.id)] = scores.get(str(winner.id), 0) + 10
                scores[str(loser.id)] = max(0, scores.get(str(loser.id), 0) - 10)
                save_scores(scores)
                await interaction.response.send_message(
                    f"🏆 **{winner.mention}** remporte le duel !\n"
                    f"➕ **+10 points** pour {winner.display_name} ({scores[str(winner.id)]} pts)\n"
                    f"➖ **-10 points** pour {loser.display_name} ({scores[str(loser.id)]} pts)\n\n"
                    f"Channel supprimé dans 5 secondes..."
                )
            await asyncio.sleep(5)
            del active_duels[self.duel_channel.id]
            await self.duel_channel.delete()
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
                    f"Utilisez `/winner @joueur` ou `/draw` dans le channel du duel pour trancher."
                )

    @discord.ui.button(label="J'ai gagné 🏆", style=discord.ButtonStyle.success)
    async def i_won(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user not in [self.challenger, self.opponent]:
            await interaction.response.send_message("Tu ne fais pas partie de ce duel !", ephemeral=True)
            return
        if str(interaction.user.id) in self.votes:
            await interaction.response.send_message("Tu as déjà voté !", ephemeral=True)
            return
        self.votes[str(interaction.user.id)] = "challenger" if interaction.user == self.challenger else "opponent"
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
        self.votes[str(interaction.user.id)] = "opponent" if interaction.user == self.challenger else "challenger"
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


# ─────────────────────────────────────────────
# EVENTS
# ─────────────────────────────────────────────

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot connecté en tant que {bot.user}")
    print("✅ Commandes slash synchronisées")


# ─────────────────────────────────────────────
# COMMANDES SLASH — JOUEURS
# ─────────────────────────────────────────────

@bot.tree.command(name="leaderboard", description="Affiche le classement des joueurs")
async def leaderboard(interaction: discord.Interaction):
    scores = load_scores()
    if not scores:
        await interaction.response.send_message("Aucun score enregistré pour l'instant !")
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
            name = "Joueur inconnu"
        description += f"{medal} {name} — {score} pts\n"
    embed.description = description
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="points", description="Affiche les points d'un joueur")
@app_commands.describe(membre="Le joueur dont tu veux voir les points")
async def points(interaction: discord.Interaction, membre: discord.Member = None):
    if membre is None:
        membre = interaction.user
    scores = load_scores()
    total = scores.get(str(membre.id), 0)
    await interaction.response.send_message(f"🎮 **{membre.display_name}** a **{total} points**")


@bot.tree.command(name="duel", description="Défier un joueur (uniquement dans #duel)")
@app_commands.describe(adversaire="Le joueur que tu veux défier")
async def duel(interaction: discord.Interaction, adversaire: discord.Member):
    if interaction.channel.name != DUEL_CHANNEL:
        await interaction.response.send_message(
            f"❌ Cette commande ne peut être utilisée que dans le salon **#{DUEL_CHANNEL}** !",
            ephemeral=True
        )
        return
    if adversaire == interaction.user:
        await interaction.response.send_message("Tu ne peux pas te défier toi-même !", ephemeral=True)
        return
    if adversaire.bot:
        await interaction.response.send_message("Tu ne peux pas défier un bot !", ephemeral=True)
        return

    view = DuelView(interaction.user, adversaire)
    await interaction.response.send_message(
        f"⚔️ **{interaction.user.mention} défie {adversaire.mention} en duel !**\n"
        f"{adversaire.mention}, acceptes-tu le combat ?",
        view=view
    )


@bot.tree.command(name="result", description="Déclarer le résultat d'un duel (dans le channel du duel)")
async def result(interaction: discord.Interaction):
    if interaction.channel.id not in active_duels:
        await interaction.response.send_message(
            "Cette commande ne peut être utilisée que dans un channel de duel !",
            ephemeral=True
        )
        return
    duel = active_duels[interaction.channel.id]
    view = ResultView(duel["challenger"], duel["opponent"], interaction.channel)
    await interaction.response.send_message(
        f"📊 **Résultat du duel — {duel['challenger'].mention} VS {duel['opponent'].mention}**\n"
        f"Chaque joueur vote honnêtement. En cas de désaccord, un admin sera notifié.",
        view=view
    )


# ─────────────────────────────────────────────
# COMMANDES SLASH — ADMIN
# ─────────────────────────────────────────────

@bot.tree.command(name="addpoints", description="[Admin] Ajouter des points à un joueur")
@app_commands.describe(membre="Le joueur", points="Nombre de points à ajouter")
@app_commands.checks.has_permissions(administrator=True)
async def addpoints(interaction: discord.Interaction, membre: discord.Member, points: int):
    scores = load_scores()
    scores[str(membre.id)] = scores.get(str(membre.id), 0) + points
    save_scores(scores)
    await interaction.response.send_message(
        f"✅ **{membre.display_name}** a reçu **{points} points** ! Total : {scores[str(membre.id)]} pts"
    )


@bot.tree.command(name="removepoints", description="[Admin] Retirer des points à un joueur")
@app_commands.describe(membre="Le joueur", points="Nombre de points à retirer")
@app_commands.checks.has_permissions(administrator=True)
async def removepoints(interaction: discord.Interaction, membre: discord.Member, points: int):
    scores = load_scores()
    scores[str(membre.id)] = max(0, scores.get(str(membre.id), 0) - points)
    save_scores(scores)
    await interaction.response.send_message(
        f"✅ **{membre.display_name}** a perdu **{points} points** ! Total : {scores[str(membre.id)]} pts"
    )


@bot.tree.command(name="reset", description="[Admin] Remettre les points d'un joueur à zéro")
@app_commands.describe(membre="Le joueur à remettre à zéro")
@app_commands.checks.has_permissions(administrator=True)
async def reset(interaction: discord.Interaction, membre: discord.Member):
    scores = load_scores()
    scores[str(membre.id)] = 0
    save_scores(scores)
    await interaction.response.send_message(
        f"🔄 Les points de **{membre.display_name}** ont été remis à zéro."
    )


@bot.tree.command(name="winner", description="[Admin] Déclarer le vainqueur en cas de litige")
@app_commands.describe(membre="Le joueur vainqueur")
@app_commands.checks.has_permissions(administrator=True)
async def winner(interaction: discord.Interaction, membre: discord.Member):
    if interaction.channel.id not in active_duels:
        await interaction.response.send_message(
            "Cette commande ne peut être utilisée que dans un channel de duel !",
            ephemeral=True
        )
        return
    duel = active_duels[interaction.channel.id]
    if membre not in [duel["challenger"], duel["opponent"]]:
        await interaction.response.send_message("Ce joueur ne fait pas partie de ce duel !", ephemeral=True)
        return

    loser = duel["opponent"] if membre == duel["challenger"] else duel["challenger"]
    scores = load_scores()
    scores[str(membre.id)] = scores.get(str(membre.id), 0) + 10
    scores[str(loser.id)] = max(0, scores.get(str(loser.id), 0) - 10)
    save_scores(scores)

    await interaction.response.send_message(
        f"⚖️ **Décision admin : {membre.mention} remporte le duel !**\n"
        f"➕ +10 pts pour {membre.display_name} | ➖ -10 pts pour {loser.display_name}\n"
        f"Channel supprimé dans 5 secondes..."
    )
    await asyncio.sleep(5)
    del active_duels[interaction.channel.id]
    await interaction.channel.delete()


@bot.tree.command(name="draw", description="[Admin] Déclarer un match nul en cas de litige")
@app_commands.checks.has_permissions(administrator=True)
async def admin_draw(interaction: discord.Interaction):
    if interaction.channel.id not in active_duels:
        await interaction.response.send_message(
            "Cette commande ne peut être utilisée que dans un channel de duel !",
            ephemeral=True
        )
        return
    await interaction.response.send_message(
        "⚖️ **Décision admin : Match nul !** Aucun point modifié.\nChannel supprimé dans 5 secondes..."
    )
    await asyncio.sleep(5)
    del active_duels[interaction.channel.id]
    await interaction.channel.delete()


bot.run(TOKEN)
