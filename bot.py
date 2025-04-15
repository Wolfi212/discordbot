import discord
from discord.ext import commands, tasks
import json
import asyncio
from datetime import datetime, timedelta
import re

# Config laden
with open('config.json') as f:
    config = json.load(f)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=config['prefix'], intents=intents)

@bot.event
async def on_ready():
    print(f'Eingeloggt als {bot.user.name}')
    await bot.change_presence(activity=discord.Game(name=f"{config['prefix']}help"))
    check_inactive_tickets.start()

@bot.event
async def on_member_join(member):
    channel = bot.get_channel(config['welcome_channel_id'])
    if channel:
        welcome_msg = config['welcome_message'].format(member=member)
        await channel.send(welcome_msg)

class TicketButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Ticket erstellen", style=discord.ButtonStyle.green, custom_id="create_ticket")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(config['ticket_create_message'], ephemeral=True)
        
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        
        try:
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            reason = msg.content
        except asyncio.TimeoutError:
            return await interaction.followup.send("Zeitüberschreitung. Bitte versuche es erneut.", ephemeral=True)
        
        category = bot.get_channel(config['ticket_category_id'])
        if not category:
            return await interaction.followup.send("Kategorie nicht gefunden. Bitte einen Admin benachrichtigen.", ephemeral=True)
        
        ticket_id = len([c for c in category.channels if isinstance(c, discord.TextChannel)]) + 1
        ticket_name = config['ticket_name_format'].format(user=interaction.user.name, id=ticket_id)
        ticket_name = re.sub(r'[^a-zA-Z0-9-_]', '', ticket_name)[:100]
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.get_role(config['support_team_role_id']): discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)
        }
        
        try:
            ticket_channel = await category.create_text_channel(
                name=ticket_name,
                overwrites=overwrites,
                topic=f"Ticket von {interaction.user} | Grund: {reason}"
            )
            
            embed = discord.Embed(
                title="Neues Ticket",
                description=config['ticket_message'],
                color=config['color']
            )
            embed.add_field(name="Benutzer", value=interaction.user.mention)
            embed.add_field(name="Grund", value=reason)
            embed.set_footer(text=f"Ticket ID: {ticket_id}")
            
            close_button = CloseTicketButton()
            await ticket_channel.send(embed=embed, view=close_button)
            
            log_channel = bot.get_channel(config['ticket_log_channel_id'])
            if log_channel:
                log_embed = discord.Embed(
                    title="Ticket erstellt",
                    description=f"**Benutzer:** {interaction.user.mention}\n**Grund:** {reason}\n**Kanal:** {ticket_channel.mention}",
                    color=config['color'],
                    timestamp=datetime.now()
                )
                await log_channel.send(embed=log_embed)
            
            await interaction.followup.send(f"Dein Ticket wurde erstellt: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Fehler beim Erstellen des Tickets: {e}", ephemeral=True)

class CloseTicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Ticket schließen", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(role.id == config['support_team_role_id'] for role in interaction.user.roles) and interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("Nur das Support-Team kann Tickets schließen.", ephemeral=True)
        
        embed = discord.Embed(
            title="Ticket geschlossen",
            description=f"Dieses Ticket wurde von {interaction.user.mention} geschlossen.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed)
        
        # Channel nach einer Minute löschen
        await asyncio.sleep(60)
        await interaction.channel.delete()

@tasks.loop(hours=24)
async def check_inactive_tickets():
    if not config['auto_close_days'] or config['auto_close_days'] <= 0:
        return
    
    category = bot.get_channel(config['ticket_category_id'])
    if not category:
        return
    
    for channel in category.channels:
        if isinstance(channel, discord.TextChannel):
            last_message = None
            async for message in channel.history(limit=1):
                last_message = message
            
            if last_message and (datetime.now() - last_message.created_at).days >= config['auto_close_days']:
                embed = discord.Embed(
                    title="Ticket automatisch geschlossen",
                    description=f"Dieses Ticket wurde wegen Inaktivität geschlossen.",
                    color=discord.Color.red()
                )
                await channel.send(embed=embed)
                await asyncio.sleep(60)
                await channel.delete()

@bot.command()
@commands.has_role(config['admin_role_id'])
async def setup(ctx):
    """Setup den Ticket-Bot"""
    embed = discord.Embed(
        title="Support-Ticket",
        description="Klicke auf den Button unten, um ein Ticket zu erstellen.",
        color=config['color']
    )
    await ctx.send(embed=embed, view=TicketButtons())
    await ctx.message.delete()

@bot.command()
@commands.has_role(config['admin_role_id'])
async def closeall(ctx):
    """Schließt alle Tickets (Admin only)"""
    category = bot.get_channel(config['ticket_category_id'])
    if not category:
        return await ctx.send("Kategorie nicht gefunden.")
    
    count = 0
    for channel in category.channels:
        if isinstance(channel, discord.TextChannel):
            await channel.delete()
            count += 1
            await asyncio.sleep(1)
    
    await ctx.send(f"{count} Tickets wurden geschlossen.")

bot.run(config['token'])
