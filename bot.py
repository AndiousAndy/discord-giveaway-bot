import discord
from discord.ext import commands
import json
import os
import random
import uuid
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Bot configuration
intents = discord.Intents.default()
intents.members = True
intents.invites = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)  # Keep prefix for backwards compatibility

# Store invite data
invites = {}
invite_data = {}
giveaway_data = {}  # {guild_id: {giveaway_id: {data}}}
entries_data = {}  # {guild_id: {giveaway_id: [user_ids]}}
inviter_tracking = {}  # Track who invited whom: {guild_id: {invited_user_id: inviter_user_id}}
active_giveaways = {}  # {message_id: giveaway_id} - Map button clicks to giveaway IDs

# Files for persistent data
INVITE_FILE = 'invite_data.json'
GIVEAWAY_FILE = 'giveaway_data.json'
ENTRIES_FILE = 'entries_data.json'

# Configuration
MAX_EXTRA_TICKETS = 5  # Cap at 5 extra tickets from invites

def load_data():
    """Load all data from files"""
    global invite_data, giveaway_data, entries_data
    
    if os.path.exists(INVITE_FILE):
        with open(INVITE_FILE, 'r') as f:
            invite_data = json.load(f)
    else:
        invite_data = {}
    
    if os.path.exists(GIVEAWAY_FILE):
        with open(GIVEAWAY_FILE, 'r') as f:
            giveaway_data = json.load(f)
    else:
        giveaway_data = {}
    
    if os.path.exists(ENTRIES_FILE):
        with open(ENTRIES_FILE, 'r') as f:
            loaded_entries = json.load(f)
            # Migrate old format to new format
            entries_data = {}
            for guild_key, value in loaded_entries.items():
                if isinstance(value, list):
                    # Old format: {guild_id: [user_ids]} - skip it, start fresh
                    print(f'Detected old entries format for guild {guild_key}, resetting...')
                    entries_data[guild_key] = {}
                elif isinstance(value, dict):
                    # New format: {guild_id: {giveaway_id: [user_ids]}}
                    entries_data[guild_key] = value
                else:
                    entries_data[guild_key] = {}
    else:
        entries_data = {}

def save_invite_data():
    """Save invite data to file"""
    with open(INVITE_FILE, 'w') as f:
        json.dump(invite_data, f, indent=4)

def save_giveaway_data():
    """Save giveaway data to file"""
    with open(GIVEAWAY_FILE, 'w') as f:
        json.dump(giveaway_data, f, indent=4)

def save_entries_data():
    """Save entries data to file"""
    with open(ENTRIES_FILE, 'w') as f:
        json.dump(entries_data, f, indent=4)

async def get_invites(guild):
    """Get all invites for a guild"""
    try:
        return await guild.invites()
    except:
        return []

def get_user_tickets(guild_id, user_id, giveaway_id=None):
    """Calculate total tickets for a user (1 base + invite bonus, max 5 extra)"""
    guild_key = str(guild_id)
    user_key = str(user_id)
    
    # If giveaway_id is provided, check if user entered that specific giveaway
    if giveaway_id:
        if (guild_key not in entries_data or 
            giveaway_id not in entries_data[guild_key] or 
            user_key not in entries_data[guild_key][giveaway_id]):
            return 0  # No tickets if not entered this giveaway
    else:
        # Check if user has entered ANY giveaway
        user_entered = False
        if guild_key in entries_data:
            for gid in entries_data[guild_key]:
                if user_key in entries_data[guild_key][gid]:
                    user_entered = True
                    break
        if not user_entered:
            return 0  # No tickets if not entered any giveaway
    
    # Base ticket (only if entered)
    base_tickets = 1
    
    # Bonus tickets from invites (capped at 5)
    invite_count = 0
    if guild_key in invite_data and user_key in invite_data[guild_key]:
        invite_count = min(invite_data[guild_key][user_key]['invites'], MAX_EXTRA_TICKETS)
    
    return base_tickets + invite_count

@bot.event
async def on_ready():
    """Bot startup event"""
    print(f'{bot.user} has connected to Discord!')
    load_data()
    
    # Cache all invites for all guilds
    for guild in bot.guilds:
        invites[guild.id] = await get_invites(guild)
        print(f'Loaded {len(invites[guild.id])} invites for {guild.name}')
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f'Synced {len(synced)} slash command(s)')
    except Exception as e:
        print(f'Failed to sync commands: {e}')
    
    print('Bot is ready!')
    print(f'Giveaway system active - Max extra tickets from invites: {MAX_EXTRA_TICKETS}')

@bot.event
async def on_member_join(member):
    """Track when a member joins via invite"""
    guild = member.guild
    
    # Get current invites
    new_invites = await get_invites(guild)
    
    # Compare with cached invites to find which was used
    if guild.id in invites:
        old_invites = invites[guild.id]
        
        # Find the invite that was used
        for new_invite in new_invites:
            for old_invite in old_invites:
                if new_invite.code == old_invite.code and new_invite.uses > old_invite.uses:
                    inviter = new_invite.inviter
                    
                    # Don't count bot invites or self-invites
                    if inviter.bot or inviter.id == member.id:
                        break
                    
                    # Initialize inviter data if not exists
                    guild_key = str(guild.id)
                    user_key = str(inviter.id)
                    member_key = str(member.id)
                    
                    if guild_key not in invite_data:
                        invite_data[guild_key] = {}
                    
                    if user_key not in invite_data[guild_key]:
                        invite_data[guild_key][user_key] = {'invites': 0}
                    
                    # Track who invited this member
                    if guild_key not in inviter_tracking:
                        inviter_tracking[guild_key] = {}
                    inviter_tracking[guild_key][member_key] = user_key
                    
                    # Increment invite count
                    invite_data[guild_key][user_key]['invites'] += 1
                    save_invite_data()
                    
                    break
    
    # Update cached invites
    invites[guild.id] = new_invites

@bot.event
async def on_member_remove(member):
    """Track when a member leaves and deduct invite from their inviter"""
    guild = member.guild
    guild_key = str(guild.id)
    member_key = str(member.id)
    
    # Check if we know who invited this member
    if guild_key in inviter_tracking and member_key in inviter_tracking[guild_key]:
        inviter_key = inviter_tracking[guild_key][member_key]
        
        # Deduct invite from the inviter
        if guild_key in invite_data and inviter_key in invite_data[guild_key]:
            if invite_data[guild_key][inviter_key]['invites'] > 0:
                invite_data[guild_key][inviter_key]['invites'] -= 1
                save_invite_data()
        
        # Remove tracking
        del inviter_tracking[guild_key][member_key]
    
    # Update cached invites
    invites[guild.id] = await get_invites(guild)

@bot.tree.command(name='tickets', description='Check how many giveaway tickets you or another user has')
async def check_tickets(interaction: discord.Interaction, member: discord.Member = None):
    """Check how many giveaway tickets you have"""
    if member is None:
        member = interaction.user
    
    guild_key = str(interaction.guild.id)
    user_key = str(member.id)
    
    # Get invite count
    invite_count = 0
    if guild_key in invite_data and user_key in invite_data[guild_key]:
        invite_count = invite_data[guild_key][user_key]['invites']
    
    # Calculate tickets
    total_tickets = get_user_tickets(interaction.guild.id, member.id)
    extra_tickets = min(invite_count, MAX_EXTRA_TICKETS)
    
    embed = discord.Embed(
        title=f"🎫 Giveaway Tickets for {member.display_name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="Total Tickets", value=f"**{total_tickets}**", inline=False)
    embed.add_field(name="Base Ticket", value="1", inline=True)
    embed.add_field(name="Invites", value=f"{invite_count}", inline=True)
    embed.add_field(name="Extra Tickets", value=f"{extra_tickets}/{MAX_EXTRA_TICKETS}", inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    if invite_count > MAX_EXTRA_TICKETS:
        embed.set_footer(text=f"You've reached the max of {MAX_EXTRA_TICKETS} extra tickets!")
    
    await interaction.response.send_message(embed=embed)

# Button View for entering giveaway
class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id: str):
        super().__init__(timeout=None)  # No timeout
        self.giveaway_id = giveaway_id
    
    @discord.ui.button(label="🎫 Enter Giveaway", style=discord.ButtonStyle.green, custom_id="enter_giveaway")
    async def enter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_key = str(interaction.guild.id)
        user_key = str(interaction.user.id)
        giveaway_id = self.giveaway_id
        
        # Check if giveaway exists and is active
        if guild_key not in giveaway_data or giveaway_id not in giveaway_data[guild_key]:
            await interaction.response.send_message('❌ This giveaway no longer exists!', ephemeral=True)
            return
        
        if not giveaway_data[guild_key][giveaway_id].get('active'):
            await interaction.response.send_message('❌ This giveaway has ended!', ephemeral=True)
            return
        
        # Initialize entries for this giveaway
        if guild_key not in entries_data:
            entries_data[guild_key] = {}
        if giveaway_id not in entries_data[guild_key]:
            entries_data[guild_key][giveaway_id] = []
        
        # Check if user already entered
        if user_key in entries_data[guild_key][giveaway_id]:
            tickets = get_user_tickets(interaction.guild.id, interaction.user.id, giveaway_id)
            await interaction.response.send_message(
                f'✅ You are already entered with **{tickets} tickets**!',
                ephemeral=True
            )
            return
        
        # Add user to entries
        entries_data[guild_key][giveaway_id].append(user_key)
        save_entries_data()
        
        # Get user's ticket count
        tickets = get_user_tickets(interaction.guild.id, interaction.user.id, giveaway_id)
        
        prize = giveaway_data[guild_key][giveaway_id]['prize']
        await interaction.response.send_message(
            f'🎉 You have entered the giveaway for **{prize}** with **{tickets} tickets**!\n'
            f'Invite friends to get more tickets (max 5 extra)!',
            ephemeral=True
        )
    
    @discord.ui.button(label="🔗 How to Invite", style=discord.ButtonStyle.blurple, custom_id="get_invite")
    async def invite_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Get current ticket count
        guild_key = str(interaction.guild.id)
        user_key = str(interaction.user.id)
        giveaway_id = self.giveaway_id
        
        # Get user stats
        tickets = get_user_tickets(interaction.guild.id, interaction.user.id, giveaway_id)
        current_invites = 0
        if guild_key in invite_data and user_key in invite_data[guild_key]:
            current_invites = invite_data[guild_key][user_key]['invites']
        
        extra_available = MAX_EXTRA_TICKETS - current_invites
        
        # Check if user has entered this specific giveaway
        user_entered = (guild_key in entries_data and 
                       giveaway_id in entries_data[guild_key] and 
                       user_key in entries_data[guild_key][giveaway_id])
        
        if user_entered:
            embed = discord.Embed(
                title="🔗 How to Earn Extra Tickets",
                description="Invite friends to earn up to 5 extra tickets!",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="📊 Your Current Stats",
                value=(
                    f"🎫 **Total Tickets:** {tickets}\n"
                    f"👥 **Invites:** {current_invites}/{MAX_EXTRA_TICKETS}\n"
                    f"⬆️ **Extra Tickets Available:** {extra_available}"
                ),
                inline=False
            )
            embed.add_field(
                name="🛠️ How to Create Your Invite Link",
                value=(
                    "1. Click/Tap the **server name** at the top\n"
                    "2. Click/Tap **'Invite'**\n"
                    "3. Copy and share your invite link!"
                ),
                inline=False
            )
            embed.add_field(
                name="✨ Important",
                value="Make sure to create your **own** invite link! The bot tracks who created each invite.",
                inline=False
            )
            embed.set_footer(text="Each friend who joins = +1 ticket (max 5 extra)")
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(
                "⚠️ **You haven't entered the giveaway yet!**\n\n"
                "Click the **'Enter Giveaway'** button first, then you can invite friends to earn extra tickets!",
                ephemeral=True
            )

@bot.tree.command(name='giveaway', description='Create a new giveaway (Admin only)')
@discord.app_commands.describe(
    prize='The prize for the giveaway',
    channel='The channel to post the giveaway in (optional, defaults to current channel)'
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def create_giveaway(interaction: discord.Interaction, prize: str, channel: discord.TextChannel = None):
    """Create a new giveaway (Admin only)"""
    # Use specified channel or current channel
    target_channel = channel if channel else interaction.channel
    
    guild_key = str(interaction.guild.id)
    giveaway_id = str(uuid.uuid4())[:8]  # Short unique ID
    
    # Initialize guild data if needed
    if guild_key not in giveaway_data:
        giveaway_data[guild_key] = {}
    if guild_key not in entries_data:
        entries_data[guild_key] = {}
    
    # Create new giveaway
    giveaway_data[guild_key][giveaway_id] = {
        'active': True,
        'prize': prize,
        'created_at': datetime.now().isoformat(),
        'created_by': str(interaction.user.id),
        'channel_id': str(target_channel.id)
    }
    save_giveaway_data()
    
    # Initialize entries for this giveaway
    if guild_key not in entries_data:
        entries_data[guild_key] = {}
    entries_data[guild_key][giveaway_id] = []
    save_entries_data()
    
    embed = discord.Embed(
        title="🎉 NEW GIVEAWAY! 🎉",
        description=f"**Prize:** {prize}\n**Giveaway ID:** `{giveaway_id}`",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="📋 How to Enter",
        value="Click the **Enter Giveaway** button below!",
        inline=False
    )
    embed.add_field(
        name="🎫 Get More Tickets",
        value="Everyone gets **1 base ticket**!\nInvite friends **after this giveaway starts** to get **1 extra ticket per invite** (max 5 extra tickets)",
        inline=False
    )
    embed.add_field(
        name="📊 Check Your Tickets",
        value="Use `/tickets` to see how many tickets you have",
        inline=False
    )
    embed.add_field(
        name="⚠️ Important",
        value="Only invites made **after this giveaway started** count toward extra tickets!",
        inline=False
    )
    embed.set_footer(text="Good luck! 🍀")
    
    # Create view with button
    view = GiveawayView(giveaway_id)
    
    # Send confirmation to the user
    await interaction.response.send_message(
        f'✅ Giveaway created in {target_channel.mention}!\nGiveaway ID: `{giveaway_id}`',
        ephemeral=True
    )
    
    # Post the giveaway in the target channel with @everyone mention
    message = await target_channel.send(content="@everyone", embed=embed, view=view)
    
    # Store message ID for reference
    giveaway_data[guild_key][giveaway_id]['message_id'] = str(message.id)
    save_giveaway_data()

@bot.tree.command(name='endgiveaway', description='End a giveaway and pick a winner (Admin only)')
@discord.app_commands.describe(
    giveaway_id='The ID of the giveaway to end',
    channel='The channel to announce the winner in (optional, defaults to current channel)'
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def end_giveaway(interaction: discord.Interaction, giveaway_id: str, channel: discord.TextChannel = None):
    """End a giveaway and pick a winner (Admin only)"""
    # Use specified channel or current channel
    target_channel = channel if channel else interaction.channel
    
    guild_key = str(interaction.guild.id)
    
    # Check if giveaway exists
    if guild_key not in giveaway_data or giveaway_id not in giveaway_data[guild_key]:
        await interaction.response.send_message(f'❌ Giveaway `{giveaway_id}` not found!', ephemeral=True)
        return
    
    if not giveaway_data[guild_key][giveaway_id].get('active'):
        await interaction.response.send_message(f'❌ Giveaway `{giveaway_id}` has already ended!', ephemeral=True)
        return
    
    # Get all entries for this giveaway
    if guild_key not in entries_data or giveaway_id not in entries_data[guild_key] or not entries_data[guild_key][giveaway_id]:
        await interaction.response.send_message(f'❌ No one has entered giveaway `{giveaway_id}` yet!', ephemeral=True)
        return
    
    # Create ticket pool from entries only
    ticket_pool = []
    for user_id in entries_data[guild_key][giveaway_id]:
        member = interaction.guild.get_member(int(user_id))
        if member and not member.bot:
            tickets = get_user_tickets(interaction.guild.id, int(user_id), giveaway_id)
            # Add member to pool based on their ticket count
            ticket_pool.extend([int(user_id)] * tickets)
    
    if not ticket_pool:
        await interaction.response.send_message('❌ No valid entries found!', ephemeral=True)
        return
    
    # Pick a random winner
    winner_id = random.choice(ticket_pool)
    winner = interaction.guild.get_member(winner_id)
    
    # Get winner's ticket count
    winner_tickets = get_user_tickets(interaction.guild.id, winner_id, giveaway_id)
    
    # Mark giveaway as ended
    prize = giveaway_data[guild_key][giveaway_id]['prize']
    giveaway_data[guild_key][giveaway_id]['active'] = False
    giveaway_data[guild_key][giveaway_id]['winner'] = str(winner_id)
    giveaway_data[guild_key][giveaway_id]['ended_at'] = datetime.now().isoformat()
    giveaway_data[guild_key][giveaway_id]['total_entries'] = len(entries_data[guild_key][giveaway_id])
    save_giveaway_data()
    
    # Announce winner
    embed = discord.Embed(
        title="🎊 GIVEAWAY WINNER! 🎊",
        description=f"**{winner.mention}** has won **{prize}**!",
        color=discord.Color.green()
    )
    embed.add_field(name="Winner's Tickets", value=f"{winner_tickets}", inline=True)
    embed.add_field(name="Total Participants", value=f"{len(entries_data[guild_key][giveaway_id])}", inline=True)
    embed.add_field(name="Total Ticket Entries", value=f"{len(ticket_pool)}", inline=True)
    embed.add_field(name="Giveaway ID", value=f"`{giveaway_id}`", inline=True)
    embed.set_thumbnail(url=winner.display_avatar.url)
    embed.set_footer(text="Congratulations! 🎉")
    
    # Send confirmation to admin
    await interaction.response.send_message(
        f'✅ Giveaway `{giveaway_id}` ended! Winner announced in {target_channel.mention}',
        ephemeral=True
    )
    
    # Announce winner in target channel
    await target_channel.send(embed=embed)

@bot.tree.command(name='leaderboard', description='Show the ticket leaderboard for a specific giveaway')
@discord.app_commands.describe(
    giveaway_id='The ID of the giveaway to show leaderboard for'
)
async def leaderboard(interaction: discord.Interaction, giveaway_id: str):
    """Show ticket leaderboard for a specific giveaway"""
    guild_key = str(interaction.guild.id)
    
    # Check if giveaway exists
    if guild_key not in giveaway_data or giveaway_id not in giveaway_data[guild_key]:
        await interaction.response.send_message(f'❌ Giveaway `{giveaway_id}` not found!', ephemeral=True)
        return
    
    # Get giveaway info
    giveaway = giveaway_data[guild_key][giveaway_id]
    prize = giveaway['prize']
    is_active = giveaway.get('active', False)
    
    # Get all entries for this giveaway
    if guild_key not in entries_data or giveaway_id not in entries_data[guild_key]:
        await interaction.response.send_message(f'❌ No entries found for giveaway `{giveaway_id}`!', ephemeral=True)
        return
    
    # Get all members and their tickets for this giveaway
    member_tickets = []
    for user_id in entries_data[guild_key][giveaway_id]:
        member = interaction.guild.get_member(int(user_id))
        if member and not member.bot:
            tickets = get_user_tickets(interaction.guild.id, int(user_id), giveaway_id)
            invites = 0
            user_key = str(user_id)
            if guild_key in invite_data and user_key in invite_data[guild_key]:
                invites = invite_data[guild_key][user_key]['invites']
            member_tickets.append((member, tickets, invites))
    
    if not member_tickets:
        await interaction.response.send_message(f'❌ No valid entries found for giveaway `{giveaway_id}`!', ephemeral=True)
        return
    
    # Sort by ticket count
    member_tickets.sort(key=lambda x: x[1], reverse=True)
    
    # Calculate total tickets
    total_tickets = sum(t[1] for t in member_tickets)
    
    status_emoji = "🟢" if is_active else "🔴"
    status_text = "Active" if is_active else "Ended"
    
    embed = discord.Embed(
        title=f"🏆 Leaderboard: {prize}",
        description=f"**Giveaway ID:** `{giveaway_id}`\n**Status:** {status_emoji} {status_text}\n**Total Participants:** {len(member_tickets)}\n**Total Tickets:** {total_tickets}",
        color=discord.Color.gold() if is_active else discord.Color.greyple()
    )
    
    for idx, (member, tickets, invites) in enumerate(member_tickets[:10], 1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
        percentage = (tickets / total_tickets * 100) if total_tickets > 0 else 0
        embed.add_field(
            name=f"{medal} {member.display_name}",
            value=f"🎫 {tickets} tickets ({invites} invites) - {percentage:.1f}% chance",
            inline=False
        )
    
    if len(member_tickets) > 10:
        embed.set_footer(text=f"Showing top 10 of {len(member_tickets)} participants")
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='gstatus', description='Check current giveaway status')
async def giveaway_status(interaction: discord.Interaction):
    """Check current giveaway status"""
    guild_key = str(interaction.guild.id)
    
    if guild_key not in giveaway_data or not giveaway_data[guild_key].get('active'):
        await interaction.response.send_message('❌ There is no active giveaway right now.', ephemeral=True)
        return
    
    prize = giveaway_data[guild_key]['prize']
    
    # Count entries
    total_entries = len(entries_data.get(guild_key, []))
    
    # Count total tickets from entries
    total_tickets = 0
    if guild_key in entries_data:
        for user_id in entries_data[guild_key]:
            total_tickets += get_user_tickets(interaction.guild.id, int(user_id))
    
    # Check if user entered
    user_entered = str(interaction.user.id) in entries_data.get(guild_key, [])
    user_tickets = get_user_tickets(interaction.guild.id, interaction.user.id) if user_entered else 0
    
    embed = discord.Embed(
        title="🎉 Active Giveaway",
        description=f"**Prize:** {prize}",
        color=discord.Color.blue()
    )
    embed.add_field(name="Total Participants", value=f"{total_entries}", inline=True)
    embed.add_field(name="Total Tickets", value=f"{total_tickets}", inline=True)
    embed.add_field(
        name="Your Status",
        value=f"{'✅ Entered' if user_entered else '❌ Not Entered'}",
        inline=True
    )
    if user_entered:
        embed.add_field(
            name="Your Tickets",
            value=f"{user_tickets}",
            inline=True
        )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='cleargiveaway', description='Clear/reset giveaway data (Admin only)')
@discord.app_commands.checks.has_permissions(administrator=True)
async def clear_giveaway(interaction: discord.Interaction):
    """Clear giveaway data (Admin only)"""
    guild_key = str(interaction.guild.id)
    
    # Clear giveaway data
    if guild_key in giveaway_data:
        giveaway_data[guild_key] = {'active': False}
        save_giveaway_data()
    
    # Clear entries
    if guild_key in entries_data:
        entries_data[guild_key] = []
        save_entries_data()
    
    # Clear invite data
    if guild_key in invite_data:
        invite_data[guild_key] = {}
        save_invite_data()
    
    await interaction.response.send_message('✅ Giveaway data has been cleared! You can now start a new giveaway.', ephemeral=True)

@bot.tree.command(name='commands', description='Show all available commands')
async def bot_commands(interaction: discord.Interaction):
    """Show all available commands"""
    embed = discord.Embed(
        title="🤖 Giveaway Bot Commands",
        description="Invite tracking + giveaway system",
        color=discord.Color.purple()
    )
    
    embed.add_field(
        name="👥 For Everyone",
        value=(
            "`/tickets [@user]` - Check your tickets\n"
            "`/leaderboard` - View top ticket holders\n"
            "`/gstatus` - Check active giveaway status\n"
            "`/commands` - Show this message"
        ),
        inline=False
    )
    
    embed.add_field(
        name="👑 Admin Only",
        value=(
            "`/giveaway <prize>` - Start a new giveaway\n"
            "`/endgiveaway` - End giveaway and pick winner\n"
            "`/cleargiveaway` - Clear/reset giveaway data"
        ),
        inline=False
    )
    
    embed.add_field(
        name="📋 How It Works",
        value=(
            f"• Everyone gets **1 base ticket**\n"
            f"• Invite friends to get **+1 ticket per invite**\n"
            f"• Maximum **{MAX_EXTRA_TICKETS} extra tickets** from invites\n"
            f"• More tickets = better chance to win!"
        ),
        inline=False
    )
    
    await interaction.response.send_message(embed=embed)

# Run the bot
if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    if not TOKEN:
        print('Error: DISCORD_BOT_TOKEN environment variable not set!')
        print('Please create a .env file with: DISCORD_BOT_TOKEN=your_token_here')
    else:
        bot.run(TOKEN)
