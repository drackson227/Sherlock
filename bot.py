import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ {bot.user} est connecté et en ligne sur Render !")

@bot.command()
async def simulate(ctx):
    await ctx.send("🕵️ **Simulation activée !**\nEnvoie-moi tes infos (nom, email, ID Discord, etc.)")

# Lancement du bot
bot.run(os.getenv("TOKEN"))
