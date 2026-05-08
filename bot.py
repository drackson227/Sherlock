import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import asyncio
from datetime import datetime
import time
import re

# ─── CONFIG ───────────────────────────────────────────────
import os
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
# ──────────────────────────────────────────────────────────

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ─── CACHE EN MÉMOIRE ─────────────────────────────────────
# Structure : { "username:pseudo": {"data": [...], "ts": timestamp} }
_cache: dict = {}
CACHE_TTL = 300  # secondes (5 min)

def cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["data"]
    return None

def cache_set(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}


# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════
def embed_base(title: str, color=0x2b2d31):
    e = discord.Embed(title=f"🔍 {title}", color=color, timestamp=datetime.utcnow())
    e.set_footer(text="OSINT Bot • Usage personnel uniquement")
    return e


def parse_phone(numero: str) -> dict:
    """Normalise un numéro et retourne ses différents formats."""
    raw = numero.strip()
    # Enlève espaces, tirets, points
    cleaned = re.sub(r"[\s\-\.]", "", raw)

    num_e164 = cleaned  # ex: +33612345678
    num_digits = re.sub(r"[^\d]", "", cleaned)  # ex: 33612345678

    # Format local FR
    if num_digits.startswith("33") and len(num_digits) == 11:
        num_local = "0" + num_digits[2:]
    elif cleaned.startswith("+33"):
        num_local = "0" + re.sub(r"[^\d]", "", cleaned[3:])
    else:
        num_local = cleaned  # non-FR, on laisse tel quel

    return {
        "raw": raw,
        "e164": num_e164,
        "digits": num_digits,
        "local": num_local,
    }


# Plateformes avec profils publics (URL + mot-clé "not found" optionnel)
# Format : name -> (url_template, [patterns indiquant absence])
PLATFORMS: dict[str, tuple[str, list[str]]] = {
    # ── Français ──
    "Vinted":       ("https://www.vinted.fr/member/{u}",              ["page introuvable", "404", "not found"]),
    "Leboncoin":    ("https://www.leboncoin.fr/profil/{u}",            ["page introuvable", "404"]),
    "BlaBlaCar":    ("https://www.blablacar.fr/user/show/{u}",         ["introuvable", "404"]),
    # ── Dev / Tech ──
    "GitHub":       ("https://github.com/{u}",                         ["not found", "page not found"]),
    "GitLab":       ("https://gitlab.com/{u}",                         ["not found", "page not found"]),
    "HackerNews":   ("https://news.ycombinator.com/user?id={u}",       ["no such user"]),
    "Keybase":      ("https://keybase.io/{u}",                         ["not found", "404"]),
    # ── Réseaux sociaux ──
    "Twitter/X":    ("https://twitter.com/{u}",                        ["this account doesn't exist", "page doesn't exist"]),
    "Instagram":    ("https://www.instagram.com/{u}/",                 ["page not found", "sorry"]),
    "TikTok":       ("https://www.tiktok.com/@{u}",                    ["couldn't find this account"]),
    "Reddit":       ("https://www.reddit.com/user/{u}",                ["page not found", "sorry, nobody on reddit goes by that name"]),
    "Mastodon":     ("https://mastodon.social/@{u}",                   ["not found", "404"]),
    "Bluesky":      ("https://bsky.app/profile/{u}",                   ["not found"]),
    "Twitch":       ("https://www.twitch.tv/{u}",                      ["page not found"]),
    "Pinterest":    ("https://www.pinterest.com/{u}/",                 ["sorry! we couldn't find that page"]),
    "Snapchat":     ("https://www.snapchat.com/add/{u}",               ["page not found"]),
    "Tumblr":       ("https://{u}.tumblr.com",                         ["there's nothing here"]),
    "Flickr":       ("https://www.flickr.com/people/{u}",              ["page not found", "oops"]),
    # ── Créateurs ──
    "Patreon":      ("https://www.patreon.com/{u}",                    ["page not found"]),
    "Ko-fi":        ("https://ko-fi.com/{u}",                          ["page not found", "oops"]),
    "Linktree":     ("https://linktr.ee/{u}",                          ["sorry, this page isn't available"]),
    "Behance":      ("https://www.behance.net/{u}",                    ["page not found"]),
    "DeviantArt":   ("https://www.deviantart.com/{u}",                 ["not found"]),
    # ── Gaming ──
    "Steam":        ("https://steamcommunity.com/id/{u}",              ["the specified profile could not be found"]),
    # ── Autres ──
    "Medium":       ("https://medium.com/@{u}",                        ["page not found"]),
    "Substack":     ("https://{u}.substack.com",                       ["this page does not exist", "404"]),
    "About.me":     ("https://about.me/{u}",                           ["page not found", "oops"]),
}


async def _check_url(session: aiohttp.ClientSession, name: str, url: str, not_found_patterns: list[str]):
    """
    Vérifie si un profil existe via HTTP.
    Combine le code HTTP + analyse du contenu pour réduire les faux positifs.
    """
    try:
        async with session.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
            timeout=aiohttp.ClientTimeout(total=12),
            allow_redirects=True,
        ) as r:
            if r.status == 404:
                return name, url, False
            if r.status == 200:
                if not not_found_patterns:
                    return name, url, True
                # Lit les premiers 8 Ko pour chercher les patterns "non trouvé"
                try:
                    chunk = await r.content.read(8192)
                    text = chunk.decode("utf-8", errors="ignore").lower()
                    for pattern in not_found_patterns:
                        if pattern.lower() in text:
                            return name, url, False
                    return name, url, True
                except Exception:
                    return name, url, True  # en cas d'erreur de lecture, on suppose trouvé
            # Codes 3xx sans redirection, 5xx, etc. → inconnu
            return name, url, False
    except asyncio.TimeoutError:
        return name, url, False
    except Exception:
        return name, url, False


# ══════════════════════════════════════════════════════════
#  EMAIL
# ══════════════════════════════════════════════════════════
async def _run_email_checks(session: aiohttp.ClientSession, adresse: str) -> tuple[list[str], str | None]:
    """Effectue les vérifications email et retourne (results, photo_url)."""
    results = []
    photo_url = None

    # HaveIBeenPwned
    try:
        async with session.get(
            f"https://haveibeenpwned.com/api/v3/breachedaccount/{adresse}",
            headers={"User-Agent": "OSINTBot-Personal"},
        ) as r:
            if r.status == 200:
                breaches = await r.json()
                names = [b["Name"] for b in breaches[:10]]
                results.append(
                    f"🔴 **HaveIBeenPwned** — {len(breaches)} fuite(s)\n> " + ", ".join(names)
                )
            elif r.status == 404:
                results.append("✅ **HaveIBeenPwned** — Aucune fuite trouvée")
            else:
                results.append(
                    f"⚠️ **HIBP** — Vérifie : https://haveibeenpwned.com/account/{adresse}"
                )
    except Exception as ex:
        results.append(f"❌ **HaveIBeenPwned** — {ex}")

    results.append(f"🔗 **HIBP Manuel** → https://haveibeenpwned.com/account/{adresse}")

    # Epieos
    try:
        async with session.get(
            f"https://epieos.com/api/email/{adresse}",
            headers={"User-Agent": "Mozilla/5.0"},
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
                if photo:    photo_url = photo
                results.append(
                    "🟡 **Epieos**\n> " + "\n> ".join(info)
                    if info else "✅ **Epieos** — Aucune donnée Google"
                )
            else:
                results.append("⚠️ **Epieos** — Vérifie manuellement : https://epieos.com")
    except Exception as ex:
        results.append(f"❌ **Epieos** — {ex}")

    # Holehe (API locale)
    try:
        async with session.get(
            f"http://localhost:8080/api/holehe/{adresse}",
            timeout=aiohttp.ClientTimeout(total=30),
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

    return results, photo_url


@tree.command(name="email", description="Recherche OSINT sur un email")
@app_commands.describe(adresse="L'adresse email à analyser")
async def lookup_email(interaction: discord.Interaction, adresse: str):
    await interaction.response.defer(ephemeral=True)

    cached = cache_get(f"email:{adresse}")
    if cached:
        embed = embed_base(f"Rapport Email : {adresse} (cache)", color=0x5865F2)
        embed.description = "\n\n".join(cached["results"])
        if cached.get("photo"):
            embed.set_thumbnail(url=cached["photo"])
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    embed = embed_base(f"Rapport Email : {adresse}", color=0x5865F2)
    async with aiohttp.ClientSession() as session:
        results, photo_url = await _run_email_checks(session, adresse)

    cache_set(f"email:{adresse}", {"results": results, "photo": photo_url})

    embed.description = "\n\n".join(results)
    if photo_url:
        embed.set_thumbnail(url=photo_url)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════
#  TÉLÉPHONE
# ══════════════════════════════════════════════════════════
async def _run_phone_checks(session: aiohttp.ClientSession, phone: dict) -> list[str]:
    """Effectue les vérifications téléphone et retourne les résultats."""
    results = []
    num_e164  = phone["e164"]
    num_digits = phone["digits"]
    num_local  = phone["local"]

    # Truecaller (lien direct)
    results.append(f"🟡 **Truecaller** → https://www.truecaller.com/search/fr/{num_digits}")

    # PagesJaunes inversé
    try:
        async with session.get(
            f"https://www.pagesjaunes.fr/pagesblanches/recherche?quoiqui={num_local}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            text = await r.text()
            if r.status == 200 and "pas de résultat" not in text.lower():
                results.append(
                    f"🟢 **PagesJaunes** — Résultat potentiel\n"
                    f"> https://www.pagesjaunes.fr/pagesblanches/recherche?quoiqui={num_local}"
                )
            else:
                results.append("✅ **PagesJaunes** — Aucun résultat public")
    except Exception as ex:
        results.append(f"❌ **PagesJaunes** — {ex}")

    # Liens supplémentaires gratuits (FR + international)
    results.append(
        f"🔗 **Autres outils gratuits**\n"
        f"> NumLookup : https://www.numlookup.com/?number={num_digits}\n"
        f"> Annuaire.com : https://www.annuaire.com/recherche/?q={num_local}\n"
        f"> PhoneInfoga (local) : https://github.com/sundowndev/phoneinfoga\n"
        f"> Infobel : https://www.infobel.com/fr/france/peoplesearch/tel/{num_local}"
    )

    # Infos de format (toujours utile)
    results.append(
        f"📋 **Formats détectés**\n"
        f"> International : `{num_e164}`\n"
        f"> Local FR : `{num_local}`\n"
        f"> Chiffres bruts : `{num_digits}`"
    )

    return results


@tree.command(name="phone", description="Recherche OSINT sur un numéro de téléphone")
@app_commands.describe(numero="Format international ex: +33612345678")
async def lookup_phone(interaction: discord.Interaction, numero: str):
    await interaction.response.defer(ephemeral=True)

    phone = parse_phone(numero)

    cached = cache_get(f"phone:{phone['digits']}")
    if cached:
        embed = embed_base(f"Rapport Téléphone : {phone['raw']} (cache)", color=0xED4245)
        embed.description = "\n\n".join(cached)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    embed = embed_base(f"Rapport Téléphone : {phone['raw']}", color=0xED4245)
    async with aiohttp.ClientSession() as session:
        results = await _run_phone_checks(session, phone)

    cache_set(f"phone:{phone['digits']}", results)
    embed.description = "\n\n".join(results)
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════
#  USERNAME
# ══════════════════════════════════════════════════════════
async def _run_username_checks(pseudo: str) -> tuple[list[str], list[str]]:
    """Lance les vérifications username et retourne (found_lines, not_found_names)."""
    cached = cache_get(f"username:{pseudo}")
    if cached:
        return cached["found"], cached["not_found"]

    found, not_found = [], []
    async with aiohttp.ClientSession() as session:
        tasks = [
            _check_url(session, name, url.format(u=pseudo), patterns)
            for name, (url, patterns) in PLATFORMS.items()
        ]
        results = await asyncio.gather(*tasks)

    for name, url, exists in results:
        if exists:
            found.append(f"✅ **{name}** → {url}")
        else:
            not_found.append(name)

    cache_set(f"username:{pseudo}", {"found": found, "not_found": not_found})
    return found, not_found


@tree.command(name="username", description=f"Recherche un pseudo sur {len(PLATFORMS)} plateformes")
@app_commands.describe(pseudo="Le pseudo à rechercher")
async def lookup_username(interaction: discord.Interaction, pseudo: str):
    await interaction.response.defer(ephemeral=True)
    embed = embed_base(f"Rapport Username : {pseudo}", color=0x57F287)

    found, not_found = await _run_username_checks(pseudo)

    if found:
        # Discord limite les fields à 1024 chars — on coupe si besoin
        found_text = "\n".join(found)
        if len(found_text) > 1024:
            found_text = found_text[:1020] + "\n…"
        embed.add_field(name=f"Trouvé ({len(found)})", value=found_text, inline=False)
    if not_found:
        nf_text = " · ".join(not_found)
        if len(nf_text) > 1024:
            nf_text = nf_text[:1020] + "…"
        embed.add_field(name=f"Non trouvé ({len(not_found)})", value=nf_text, inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)


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
        f'"{nom}" site:twitter.com OR site:x.com',
        f'"{nom}" site:instagram.com',
    ]
    dork_links = "\n> ".join([
        f"[Dork {i+1}](https://www.google.com/search?q={d.replace(' ', '+').replace('\"', '%22')})"
        for i, d in enumerate(dorks)
    ])

    results = [
        f"🟡 **PagesJaunes**\n> https://www.pagesjaunes.fr/pagesblanches/recherche?quoiqui={nom_enc}",
        f"🔎 **Google Dorks** ({len(dorks)} requêtes)\n> {dork_links}",
        f"🔗 **Autres gratuits**\n"
        f"> Pipl : https://pipl.com/search/?q={nom_enc}\n"
        f"> Spokeo : https://www.spokeo.com/{nom_tiret}\n"
        f"> Infobel : https://www.infobel.com/fr/france/peoplesearch/?name={nom_enc}",
    ]

    embed.description = "\n\n".join(results)
    embed.set_footer(text="⚠️ Usage strictement personnel — RGPD applicable")
    await interaction.followup.send(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════
#  ALL — Rapport consolidé
# ══════════════════════════════════════════════════════════
@tree.command(name="all", description="Rapport OSINT complet : email + téléphone + username")
@app_commands.describe(
    email="Adresse email",
    phone="Numéro de téléphone (ex: +33612345678)",
    username="Pseudo à vérifier",
)
async def lookup_all(
    interaction: discord.Interaction,
    email: str | None = None,
    phone: str | None = None,
    username: str | None = None,
):
    if not any([email, phone, username]):
        await interaction.response.send_message(
            "⚠️ Fournis au moins un paramètre : `email`, `phone` ou `username`.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    embeds = []

    async with aiohttp.ClientSession() as session:

        # ── EMAIL ──
        if email:
            e = embed_base(f"📧 Email : {email}", color=0x5865F2)
            results, photo_url = await _run_email_checks(session, email)
            e.description = "\n\n".join(results)
            if photo_url:
                e.set_thumbnail(url=photo_url)
            embeds.append(e)

        # ── TÉLÉPHONE ──
        if phone:
            parsed = parse_phone(phone)
            e = embed_base(f"📞 Téléphone : {parsed['raw']}", color=0xED4245)
            results = await _run_phone_checks(session, parsed)
            e.description = "\n\n".join(results)
            embeds.append(e)

    # ── USERNAME (ouvre sa propre session en interne) ──
    if username:
        e = embed_base(f"👤 Username : {username}", color=0x57F287)
        found, not_found = await _run_username_checks(username)
        if found:
            found_text = "\n".join(found)
            if len(found_text) > 1024:
                found_text = found_text[:1020] + "\n…"
            e.add_field(name=f"Trouvé ({len(found)})", value=found_text, inline=False)
        if not_found:
            nf_text = " · ".join(not_found)
            if len(nf_text) > 1024:
                nf_text = nf_text[:1020] + "…"
            e.add_field(name=f"Non trouvé ({len(not_found)})", value=nf_text, inline=False)
        embeds.append(e)

    # Discord accepte max 10 embeds par message
    await interaction.followup.send(embeds=embeds[:10], ephemeral=True)


# ══════════════════════════════════════════════════════════
#  AIDE
# ══════════════════════════════════════════════════════════
@tree.command(name="osint", description="Affiche l'aide du bot OSINT")
async def osint_help(interaction: discord.Interaction):
    embed = embed_base("Commandes disponibles", color=0x99AAB5)
    embed.add_field(name="/email <adresse>",             value="HIBP + Epieos + Holehe", inline=False)
    embed.add_field(name="/phone <+33...>",              value="Truecaller + PagesJaunes + liens FR", inline=False)
    embed.add_field(name=f"/username <pseudo>",          value=f"{len(PLATFORMS)} plateformes vérifiées (contenu + HTTP)", inline=False)
    embed.add_field(name="/name <prénom nom>",           value="PagesJaunes + 7 Google Dorks", inline=False)
    embed.add_field(name="/all [email] [phone] [pseudo]", value="Rapport consolidé en un seul appel", inline=False)
    embed.add_field(name="Cache",                        value=f"Résultats mis en cache {CACHE_TTL}s pour éviter les doublons", inline=False)
    embed.set_footer(text="⚠️ Usage personnel uniquement • Respecte le RGPD")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════
#  START
# ══════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Bot connecté : {bot.user} | Slash commands synchronisées")
    print(f"   Plateformes username : {len(PLATFORMS)}")

bot.run(DISCORD_TOKEN)
