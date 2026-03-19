import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import asyncio
from datetime import datetime
from discord.ext import tasks

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
# SAISONS
# ─────────────────────────────────────────────

ANNOUNCE_CHANNEL = "saison"

def load_saison():
    if os.path.exists("saison.json"):
        with open("saison.json", "r") as f:
            return json.load(f)
    # Première fois : on initialise
    data = {
        "numero": 1,
        "debut": datetime.utcnow().isoformat()
    }
    save_saison(data)
    return data

def save_saison(data):
    with open("saison.json", "w") as f:
        json.dump(data, f, indent=4)

async def fin_de_saison(guild):
    scores = load_scores()
    saison = load_saison()

    # Trouver le vainqueur
    if scores:
        winner_id = max(scores, key=scores.get)
        winner_score = scores[winner_id]
        try:
            winner = await bot.fetch_user(int(winner_id))
            winner_name = winner.display_name
        except:
            winner_name = "Joueur inconnu"
    else:
        winner_name = None
        winner_score = 0

    # Annoncer dans le salon
    channel = discord.utils.get(guild.text_channels, name=ANNOUNCE_CHANNEL)
    if channel:
        embed = discord.Embed(
            title=f"🏁 Fin de la Saison {saison['numero']} !",
            color=0xf1c40f
        )
        if winner_name:
            embed.description = (
                f"🏆 **Vainqueur : {winner_name}** avec **{winner_score} points** !\n\n"
                f"Félicitations à tous les participants !\n"
                f"La Saison {saison['numero'] + 1} commence maintenant. 🚀"
            )
        else:
            embed.description = (
                f"Aucun score cette saison.\n"
                f"La Saison {saison['numero'] + 1} commence maintenant. 🚀"
            )
        await channel.send(embed=embed)

    # Reset des scores et nouvelle saison
    save_scores({})
    save_saison({
        "numero": saison["numero"] + 1,
        "debut": datetime.utcnow().isoformat()
    })

# Tâche automatique — vérifie chaque jour si 30 jours sont écoulés
@tasks.loop(hours=24)
async def check_saison():
    saison = load_saison()
    debut = datetime.fromisoformat(saison["debut"])
    if (datetime.utcnow() - debut).days >= 30:
        for guild in bot.guilds:
            await fin_de_saison(guild)

@check_saison.before_loop
async def before_check_saison():
    await bot.wait_until_ready()

# Commandes saison
saison_group = app_commands.Group(name="saison", description="Gère les saisons")

@saison_group.command(name="info", description="Affiche les infos de la saison en cours")
async def saison_info(interaction: discord.Interaction):
    saison = load_saison()
    debut = datetime.fromisoformat(saison["debut"])
    jours_ecoules = (datetime.utcnow() - debut).days
    jours_restants = max(0, 30 - jours_ecoules)
    embed = discord.Embed(
        title=f"📅 Saison {saison['numero']}",
        description=(
            f"🗓️ Début : <t:{int(debut.timestamp())}:D>\n"
            f"⏳ Jours écoulés : **{jours_ecoules}/30**\n"
            f"🔜 Fin dans : **{jours_restants} jours**"
        ),
        color=0x5865f2
    )
    await interaction.response.send_message(embed=embed)

@saison_group.command(name="forcer", description="[Admin] Force la fin de la saison immédiatement")
@app_commands.checks.has_permissions(administrator=True)
async def saison_forcer(interaction: discord.Interaction):
    await interaction.response.send_message("⏳ Fin de saison en cours...")
    await fin_de_saison(interaction.guild)

bot.tree.add_command(saison_group)

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

# ─────────────────────────────────────────────
# FAIBLESSES
# ─────────────────────────────────────────────

def load_faiblesses():
    if os.path.exists("faiblesses.json"):
        with open("faiblesses.json", "r") as f:
            return json.load(f)
    return {}

def save_faiblesses(faiblesses):
    with open("faiblesses.json", "w") as f:
        json.dump(faiblesses, f, indent=4)

# Stocke les utilisateurs en attente d'ajout
attente_faiblesse = set()

faiblesse_group = app_commands.Group(name="faiblesse", description="Gère tes faiblesses")

@faiblesse_group.command(name="ajouter", description="Ajoute des faiblesses à ta liste")
async def faiblesse_ajouter(interaction: discord.Interaction):
    attente_faiblesse.add(interaction.user.id)
    await interaction.response.send_message(
        "✏️ Envoie ton prochain message avec ta liste de faiblesses. Il sera enregistré automatiquement !",
        ephemeral=True
    )

@faiblesse_group.command(name="effacer", description="Efface toute ta liste de faiblesses")
async def faiblesse_effacer(interaction: discord.Interaction):
    faiblesses = load_faiblesses()
    faiblesses[str(interaction.user.id)] = ""
    save_faiblesses(faiblesses)
    await interaction.response.send_message("🗑️ Ta liste de faiblesses a été effacée.", ephemeral=True)

bot.tree.add_command(faiblesse_group)

@faiblesse_group.command(name="voir", description="Affiche la liste de faiblesses d'un joueur")
@app_commands.describe(membre="Le joueur dont tu veux voir les faiblesses")
async def faiblesse_voir(interaction: discord.Interaction, membre: discord.Member):
    faiblesses_data = load_faiblesses()
    contenu = faiblesses_data.get(str(membre.id), "")
    if not contenu:
        await interaction.response.send_message(
            f"📋 **{membre.display_name}** n'a pas encore renseigné ses faiblesses."
        )
        return
    embed = discord.Embed(
        title=f"📋 Faiblesses de {membre.display_name}",
        description=contenu,
        color=0x5865f2
    )
    await interaction.response.send_message(embed=embed)
    
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.author.id in attente_faiblesse:
        attente_faiblesse.remove(message.author.id)
        faiblesses = load_faiblesses()
        user_id = str(message.author.id)
        # Ajouter à la liste existante
        if faiblesses.get(user_id):
            faiblesses[user_id] += "\n" + message.content
        else:
            faiblesses[user_id] = message.content
        save_faiblesses(faiblesses)
        await message.reply("✅ Tes faiblesses ont bien été enregistrées !")
        await message.delete()
        return
    await bot.process_commands(message)
    
bot.run(TOKEN)
