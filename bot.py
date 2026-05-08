import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import asyncio
from datetime import datetime

# ─── CONFIG ───────────────────────────────────────────────
DISCORD_TOKEN = "TON_TOKEN_ICI"
NUMVERIFY_KEY = "TA_CLE_NUMVERIFY"  # Gratuit 250 req/mois → https://numverify.com
# ──────────────────────────────────────────────────────────

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


def embed_base(title: str, color=0x2b2d31):
    e = discord.Embed(title=f"🔍 {title}", color=color, timestamp=datetime.utcnow())
    e.set_footer(text="OSINT Bot • Usage personnel uniquement")
    return e


# ══════════════════════════════════════════════════════════
#  EMAIL
# ══════════════════════════════════════════════════════════
@tree.command(name="email", description="Recherche OSINT sur un email")
@app_commands.describe(adresse="L'adresse email à analyser")
async def lookup_email(interaction: discord.Interaction, adresse: str):
    await interaction.response.defer(ephemeral=True)
    embed = embed_base(f"Rapport Email : {adresse}", color=0x5865F2)
    results = []

    async with aiohttp.ClientSession() as session:

        # HaveIBeenPwned (endpoint public gratuit)
        try:
            async with session.get(
                f"https://haveibeenpwned.com/api/v3/breachedaccount/{adresse}",
                headers={"User-Agent": "OSINTBot-Personal"}
            ) as r:
                if r.status == 200:
                    breaches = await r.json()
                    names = [b["Name"] for b in breaches[:10]]
                    results.append(f"🔴 **HaveIBeenPwned** — {len(breaches)} fuite(s)\n> " + ", ".join(names))
                elif r.status == 404:
                    results.append("✅ **HaveIBeenPwned** — Aucune fuite trouvée")
                else:
                    results.append(f"⚠️ **HIBP** — Vérifie manuellement : https://haveibeenpwned.com/account/{adresse}")
        except Exception as ex:
            results.append(f"❌ **HaveIBeenPwned** — {ex}")

        results.append(f"🔗 **HIBP Manuel** → https://haveibeenpwned.com/account/{adresse}")

        # Epieos
        try:
            async with session.get(
                f"https://epieos.com/api/email/{adresse}",
                headers={"User-Agent": "Mozilla/5.0"}
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    info = []
                    gaiaId   = data.get("google", {}).get("gaiaId")
                    name     = data.get("google", {}).get("name")
                    photo    = data.get("google", {}).get("photo")
                    services = data.get("services", [])
                    if gaiaId:   info.append(f"Google ID : `{gaiaId}`")
                    if name:     info.append(f"Nom Google : **{name}**")
                    if services: info.append(f"Services : {', '.join(services[:8])}")
                    if photo:    embed.set_thumbnail(url=photo)
                    results.append("🟡 **Epieos**\n> " + "\n> ".join(info) if info else "✅ **Epieos** — Aucune donnée Google")
                else:
                    results.append("⚠️ **Epieos** — Vérifie manuellement : https://epieos.com")
        except Exception as ex:
            results.append(f"❌ **Epieos** — {ex}")

        # Holehe (API locale gratuite)
        try:
            async with session.get(
                f"http://localhost:8080/api/holehe/{adresse}",
                timeout=aiohttp.ClientTimeout(total=30)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    found = [s["name"] for s in data if s.get("exists")]
                    results.append(
                        f"🔵 **Holehe** — Inscrit sur {len(found)} site(s)\n> " + ", ".join(found)
                        if found else "✅ **Holehe** — Aucun site détecté"
                    )
                else:
                    results.append("⚠️ **Holehe** — Lance `holehe --api` en local")
        except Exception:
            results.append("⚠️ **Holehe** — Lance `pip install holehe` puis `holehe --api`")

    embed.description = "\n\n".join(results)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════
#  TÉLÉPHONE
# ══════════════════════════════════════════════════════════
@tree.command(name="phone", description="Recherche OSINT sur un numéro de téléphone")
@app_commands.describe(numero="Format international ex: +33612345678")
async def lookup_phone(interaction: discord.Interaction, numero: str):
    await interaction.response.defer(ephemeral=True)
    embed = embed_base(f"Rapport Téléphone : {numero}", color=0xED4245)
    num_clean = numero.replace("+", "").replace(" ", "")
    num_local = numero.replace("+33", "0").replace(" ", "")
    results = []

    async with aiohttp.ClientSession() as session:

        # NumVerify (gratuit 250 req/mois)
        try:
            async with session.get(
                f"http://apilayer.net/api/validate?access_key={NUMVERIFY_KEY}&number={num_clean}&format=1"
            ) as r:
                if r.status == 200:
                    d = await r.json()
                    if d.get("valid"):
                        info = [
                            f"Pays : {d.get('country_name', '?')} ({d.get('country_code', '?')})",
                            f"Opérateur : {d.get('carrier', '?')}",
                            f"Type de ligne : {d.get('line_type', '?')}",
                            f"Format local : {d.get('local_format', '?')}",
                        ]
                        results.append("🟢 **NumVerify**\n> " + "\n> ".join(info))
                    else:
                        results.append("❌ **NumVerify** — Numéro invalide ou non trouvé")
                else:
                    results.append(f"⚠️ **NumVerify** — Erreur {r.status} (vérifie ta clé)")
        except Exception as ex:
            results.append(f"❌ **NumVerify** — {ex}")

        # Truecaller (lien direct)
        results.append(f"🟡 **Truecaller** → https://www.truecaller.com/search/fr/{num_clean}")

        # PagesJaunes inversé
        try:
            async with session.get(
                f"https://www.pagesjaunes.fr/pagesblanches/recherche?quoiqui={num_local}",
                headers={"User-Agent": "Mozilla/5.0"}
            ) as r:
                text = await r.text()
                if r.status == 200 and "pas de résultat" not in text.lower():
                    results.append(f"🟢 **PagesJaunes** — Résultat potentiel\n> https://www.pagesjaunes.fr/pagesblanches/recherche?quoiqui={num_local}")
                else:
                    results.append("✅ **PagesJaunes** — Aucun résultat public")
        except Exception as ex:
            results.append(f"❌ **PagesJaunes** — {ex}")

        # Liens alternatifs gratuits
        results.append(
            f"🔗 **Autres (gratuits)**\n"
            f"> NumLookup : https://www.numlookup.com/?number={num_clean}\n"
            f"> PhoneInfoga (local) : https://github.com/sundowndev/phoneinfoga"
        )

    embed.description = "\n\n".join(results)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════
#  USERNAME
# ══════════════════════════════════════════════════════════
PLATFORMS = {
    "Vinted":     "https://www.vinted.fr/member/{u}",
    "Leboncoin":  "https://www.leboncoin.fr/profil/{u}",
    "BlaBlaCar":  "https://www.blablacar.fr/user/show/{u}",
    "GitHub":     "https://github.com/{u}",
    "Twitter/X":  "https://twitter.com/{u}",
    "Instagram":  "https://www.instagram.com/{u}/",
    "TikTok":     "https://www.tiktok.com/@{u}",
    "Reddit":     "https://www.reddit.com/user/{u}",
    "Twitch":     "https://www.twitch.tv/{u}",
    "Pinterest":  "https://www.pinterest.com/{u}/",
    "Snapchat":   "https://www.snapchat.com/add/{u}",
    "Steam":      "https://steamcommunity.com/id/{u}",
    "Flickr":     "https://www.flickr.com/people/{u}",
    "Patreon":    "https://www.patreon.com/{u}",
}

@tree.command(name="username", description="Recherche un pseudo sur 14 plateformes")
@app_commands.describe(pseudo="Le pseudo à rechercher")
async def lookup_username(interaction: discord.Interaction, pseudo: str):
    await interaction.response.defer(ephemeral=True)
    embed = embed_base(f"Rapport Username : {pseudo}", color=0x57F287)
    found, not_found = [], []

    async with aiohttp.ClientSession() as session:
        tasks = [_check_url(session, name, url.format(u=pseudo)) for name, url in PLATFORMS.items()]
        results = await asyncio.gather(*tasks)

    for name, url, exists in results:
        if exists:
            found.append(f"✅ **{name}** → {url}")
        else:
            not_found.append(f"❌ {name}")

    if found:
        embed.add_field(name=f"Trouvé ({len(found)})", value="\n".join(found), inline=False)
    if not_found:
        embed.add_field(name="Non trouvé", value=" · ".join(not_found), inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)


async def _check_url(session, name, url):
    try:
        async with session.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=aiohttp.ClientTimeout(total=10),
            allow_redirects=True
        ) as r:
            return name, url, r.status == 200
    except Exception:
        return name, url, False


# ══════════════════════════════════════════════════════════
#  NOM COMPLET
# ══════════════════════════════════════════════════════════
@tree.command(name="name", description="Recherche OSINT sur un nom complet")
@app_commands.describe(nom="Prénom et nom ex: Jean Dupont")
async def lookup_name(interaction: discord.Interaction, nom: str):
    await interaction.response.defer(ephemeral=True)
    embed = embed_base(f"Rapport Nom : {nom}", color=0xFEE75C)
    nom_enc   = nom.replace(" ", "+")
    nom_tiret = nom.replace(" ", "-")

    dorks = [
        f'"{nom}" site:linkedin.com',
        f'"{nom}" site:facebook.com',
        f'"{nom}" site:vinted.fr OR site:leboncoin.fr',
        f'"{nom}" site:pagesjaunes.fr',
        f'"{nom}" filetype:pdf',
    ]
    dork_links = "\n> ".join([
        f"https://www.google.com/search?q={d.replace(' ', '+').replace('\"', '%22')}"
        for d in dorks
    ])

    results = [
        f"🟡 **PagesJaunes**\n> https://www.pagesjaunes.fr/pagesblanches/recherche?quoiqui={nom_enc}",
        f"🔎 **Google Dorks**\n> {dork_links}",
        f"🔗 **Autres gratuits**\n> Pipl : https://pipl.com/search/?q={nom_enc}\n> Spokeo : https://www.spokeo.com/{nom_tiret}",
    ]

    embed.description = "\n\n".join(results)
    embed.set_footer(text="⚠️ Usage strictement personnel — RGPD applicable")
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════
#  AIDE
# ══════════════════════════════════════════════════════════
@tree.command(name="osint", description="Affiche l'aide du bot OSINT")
async def osint_help(interaction: discord.Interaction):
    embed = embed_base("Commandes disponibles", color=0x99AAB5)
    embed.add_field(name="/email <adresse>",   value="HIBP + Epieos + Holehe", inline=False)
    embed.add_field(name="/phone <+33...>",    value="NumVerify + Truecaller + PagesJaunes", inline=False)
    embed.add_field(name="/username <pseudo>", value="14 plateformes vérifiées", inline=False)
    embed.add_field(name="/name <prénom nom>", value="PagesJaunes + Google Dorks", inline=False)
    embed.set_footer(text="⚠️ Usage personnel uniquement • Respecte le RGPD")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════
#  START
# ══════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot connecté : {bot.user} | Slash commands synchronisées")

bot.run(DISCORD_TOKEN)
