import discord
from discord.ext import commands
import json
import os
import random
import uuid
import asyncio
from datetime import datetime, timedelta
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
# Use /app/data for Railway persistent volume, fallback to current directory for local dev
DATA_DIR = '/app/data' if os.path.exists('/app/data') else '.'
INVITE_FILE = os.path.join(DATA_DIR, 'invite_data.json')
GIVEAWAY_FILE = os.path.join(DATA_DIR, 'giveaway_data.json')
ENTRIES_FILE = os.path.join(DATA_DIR, 'entries_data.json')

# Configuration
MAX_EXTRA_TICKETS = 5  # Cap at 5 extra tickets from invites
BONUS_ROLE_NAME = "+EV"  # Role name that gives +1 bonus ticket
BONUS_ROLE_TICKETS = 1  # Extra tickets for having the bonus role

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
            try:
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
            except (json.JSONDecodeError, ValueError):
                print('Error loading entries_data.json, starting fresh...')
                entries_data = {}
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

async def auto_end_giveaway(guild_key, giveaway_id, delay_seconds, channel):
    """Automatically end a giveaway after the specified delay"""
    await asyncio.sleep(delay_seconds)
    
    # Check if giveaway is still active
    if guild_key not in giveaway_data or giveaway_id not in giveaway_data[guild_key]:
        return
    
    if not giveaway_data[guild_key][giveaway_id].get('active'):
        return  # Already ended
    
    # Get entries
    if guild_key not in entries_data or giveaway_id not in entries_data[guild_key] or not entries_data[guild_key][giveaway_id]:
        # No entries, just mark as ended
        giveaway_data[guild_key][giveaway_id]['active'] = False
        giveaway_data[guild_key][giveaway_id]['ended_at'] = datetime.now().isoformat()
        save_giveaway_data()
        
        embed = discord.Embed(
            title="🚫 Giveaway Ended - No Entries",
            description=f"The giveaway for **{giveaway_data[guild_key][giveaway_id]['prize']}** has ended with no entries.",
            color=discord.Color.red()
        )
        embed.add_field(name="Giveaway ID", value=f"`{giveaway_id}`", inline=False)
        await channel.send(embed=embed)
        return
    
    # Create ticket pool
    ticket_pool = []
    guild = channel.guild
    for user_id in entries_data[guild_key][giveaway_id]:
        member = guild.get_member(int(user_id))
        if member and not member.bot:
            tickets = get_user_tickets(guild.id, int(user_id), giveaway_id)
            ticket_pool.extend([int(user_id)] * tickets)
    
    if not ticket_pool:
        # No valid entries
        giveaway_data[guild_key][giveaway_id]['active'] = False
        giveaway_data[guild_key][giveaway_id]['ended_at'] = datetime.now().isoformat()
        save_giveaway_data()
        
        embed = discord.Embed(
            title="🚫 Giveaway Ended - No Valid Entries",
            description=f"The giveaway for **{giveaway_data[guild_key][giveaway_id]['prize']}** has ended with no valid entries.",
            color=discord.Color.red()
        )
        embed.add_field(name="Giveaway ID", value=f"`{giveaway_id}`", inline=False)
        await channel.send(embed=embed)
        return
    
    # Get number of winners
    num_winners = giveaway_data[guild_key][giveaway_id].get('winners', 1)
    num_winners = min(num_winners, len(set(ticket_pool)))  # Can't have more winners than unique participants
    
    # Pick winners (without replacement)
    winner_ids = []
    temp_pool = ticket_pool.copy()
    for _ in range(num_winners):
        if not temp_pool:
            break
        winner_id = random.choice(temp_pool)
        winner_ids.append(winner_id)
        # Remove all tickets from this winner to prevent duplicate wins
        temp_pool = [uid for uid in temp_pool if uid != winner_id]
    
    # Mark as ended
    prize = giveaway_data[guild_key][giveaway_id]['prize']
    giveaway_data[guild_key][giveaway_id]['active'] = False
    giveaway_data[guild_key][giveaway_id]['winners_list'] = [str(wid) for wid in winner_ids]
    giveaway_data[guild_key][giveaway_id]['ended_at'] = datetime.now().isoformat()
    giveaway_data[guild_key][giveaway_id]['total_entries'] = len(entries_data[guild_key][giveaway_id])
    save_giveaway_data()
    
    # Announce winners
    title = "🎊 GIVEAWAY WINNER! 🎊" if len(winner_ids) == 1 else f"🎊 GIVEAWAY WINNERS! 🎊"
    
    # Check if there's prize distribution
    prize_dist = giveaway_data[guild_key][giveaway_id].get('prize_distribution')
    
    winners_text = ""
    for idx, winner_id in enumerate(winner_ids, 1):
        winner = guild.get_member(winner_id)
        winner_tickets = get_user_tickets(guild.id, winner_id, giveaway_id)
        
        if prize_dist and len(prize_dist) >= idx:
            # Show specific prize for this position
            winner_prize = prize_dist[idx - 1]
            winners_text += f"**{idx}.** {winner.mention} - **{winner_prize}** ({winner_tickets} tickets)\n"
        elif len(winner_ids) == 1:
            winners_text = f"**{winner.mention}** has won **{prize}**!"
        else:
            winners_text += f"**{idx}.** {winner.mention} ({winner_tickets} tickets)\n"
    
    if len(winner_ids) > 1:
        if prize_dist:
            description = f"**Winners:**\n{winners_text}"
        else:
            description = f"**Prize:** {prize}\n\n**Winners:**\n{winners_text}"
    else:
        description = winners_text
    
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.green()
    )
    embed.add_field(name="Total Participants", value=f"{len(entries_data[guild_key][giveaway_id])}", inline=True)
    embed.add_field(name="Total Ticket Entries", value=f"{len(ticket_pool)}", inline=True)
    embed.add_field(name="Giveaway ID", value=f"`{giveaway_id}`", inline=True)
    
    if len(winner_ids) == 1:
        embed.set_thumbnail(url=guild.get_member(winner_ids[0]).display_avatar.url)
    
    embed.set_footer(text="Congratulations! 🎉")
    
    await channel.send(embed=embed)

def get_user_tickets(guild_id, user_id, giveaway_id=None):
    """Calculate total tickets for a user (1 base + invite bonus + role bonus)"""
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
        invite_count = min(invite_data[guild_key][user_key].get('invites', 0), MAX_EXTRA_TICKETS)
    
    # Manual bonus tickets (no cap)
    manual_bonus = 0
    if guild_key in invite_data and user_key in invite_data[guild_key]:
        manual_bonus = invite_data[guild_key][user_key].get('manual_bonus', 0)
    
    # Bonus ticket for having the special role
    role_bonus = 0
    try:
        guild = bot.get_guild(int(guild_id))
        if guild:
            member = guild.get_member(int(user_id))
            if member:
                bonus_role = discord.utils.get(member.roles, name=BONUS_ROLE_NAME)
                if bonus_role:
                    role_bonus = BONUS_ROLE_TICKETS
    except:
        pass
    
    return base_tickets + invite_count + role_bonus + manual_bonus

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
    manual_bonus = 0
    if guild_key in invite_data and user_key in invite_data[guild_key]:
        invite_count = invite_data[guild_key][user_key].get('invites', 0)
        manual_bonus = invite_data[guild_key][user_key].get('manual_bonus', 0)
    
    # Check for bonus role
    has_bonus_role = discord.utils.get(member.roles, name=BONUS_ROLE_NAME) is not None
    role_bonus = BONUS_ROLE_TICKETS if has_bonus_role else 0
    
    # Calculate tickets
    total_tickets = get_user_tickets(interaction.guild.id, member.id)
    extra_tickets = min(invite_count, MAX_EXTRA_TICKETS)
    
    embed = discord.Embed(
        title=f"🎫 Giveaway Tickets for {member.display_name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="Total Tickets", value=f"**{total_tickets}**", inline=False)
    embed.add_field(name="Base Ticket", value="1", inline=True)
    embed.add_field(name=f"{BONUS_ROLE_NAME} Server Tag", value=f"{'✅' if has_bonus_role else '❌'} (+{role_bonus})", inline=True)
    embed.add_field(name="Invite Tickets", value=f"{extra_tickets}/{MAX_EXTRA_TICKETS}", inline=True)
    if manual_bonus != 0:
        embed.add_field(name="Manual Bonus", value=f"+{manual_bonus}", inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    if invite_count > MAX_EXTRA_TICKETS:
        embed.set_footer(text=f"You've reached the max of {MAX_EXTRA_TICKETS} invite tickets!")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

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
    prize='The main prize (or use prize_distribution for multiple)',
    duration_hours='Duration in hours (e.g., 24 for 1 day, 168 for 1 week)',
    winners='Number of winners (default: 1, max: 10)',
    prize_distribution='Optional: Prizes for each place, separated by commas (e.g., "$100, $50, $25")',
    custom_title='Optional: Custom title for the giveaway (e.g., "MEGA GIVEAWAY")',
    channel='The channel to post the giveaway in (optional, defaults to current channel)'
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def create_giveaway(interaction: discord.Interaction, prize: str, duration_hours: int, winners: int = 1, prize_distribution: str = None, custom_title: str = None, channel: discord.TextChannel = None):
    """Create a new giveaway (Admin only)"""
    # Use specified channel or current channel
    target_channel = channel if channel else interaction.channel
    
    # Validate duration
    if duration_hours < 1:
        await interaction.response.send_message('❌ Duration must be at least 1 hour!', ephemeral=True)
        return
    if duration_hours > 720:  # 30 days max
        await interaction.response.send_message('❌ Duration cannot exceed 720 hours (30 days)!', ephemeral=True)
        return
    
    # Validate winners
    if winners < 1:
        await interaction.response.send_message('❌ Must have at least 1 winner!', ephemeral=True)
        return
    if winners > 10:
        await interaction.response.send_message('❌ Cannot have more than 10 winners!', ephemeral=True)
        return
    
    guild_key = str(interaction.guild.id)
    giveaway_id = str(uuid.uuid4())[:8]  # Short unique ID
    
    # Initialize guild data if needed
    if guild_key not in giveaway_data:
        giveaway_data[guild_key] = {}
    if guild_key not in entries_data:
        entries_data[guild_key] = {}
    
    # Calculate end time
    start_time = datetime.now()
    end_time = start_time + timedelta(hours=duration_hours)
    
    # Parse prize distribution if provided
    prizes_list = []
    if prize_distribution:
        prizes_list = [p.strip() for p in prize_distribution.split(',')]
        if len(prizes_list) != winners:
            await interaction.response.send_message(
                f'❌ Prize distribution must have {winners} prizes separated by commas (you provided {len(prizes_list)})',
                ephemeral=True
            )
            return
    
    # Create new giveaway
    giveaway_data[guild_key][giveaway_id] = {
        'active': True,
        'prize': prize,
        'created_at': start_time.isoformat(),
        'created_by': str(interaction.user.id),
        'channel_id': str(target_channel.id),
        'duration_hours': duration_hours,
        'end_time': end_time.isoformat(),
        'winners': winners,
        'prize_distribution': prizes_list if prizes_list else None
    }
    save_giveaway_data()
    
    # Initialize entries for this giveaway
    if guild_key not in entries_data:
        entries_data[guild_key] = {}
    # Safety check: ensure it's a dict, not a list
    if not isinstance(entries_data[guild_key], dict):
        entries_data[guild_key] = {}
    entries_data[guild_key][giveaway_id] = []
    save_entries_data()
    
    # Format end time for Discord timestamp
    end_timestamp = int(end_time.timestamp())
    
    # Build prize display and title
    if custom_title:
        title = f"🎉 {custom_title.upper()} 🎉"
    elif prizes_list:
        title = f"🎉 {prize.upper()} GIVEAWAY! 🎉"
    else:
        title = "🎉 NEW GIVEAWAY! 🎉"
    
    if prizes_list:
        prize_display = "\n".join([f"**{i+1}.** {p}" for i, p in enumerate(prizes_list)])
        prize_text = f"**Prizes:**\n{prize_display}"
    else:
        winners_text = f"{winners} winner" if winners == 1 else f"{winners} winners"
        prize_text = f"**Prize:** {prize}\n**Winners:** {winners_text}"
    
    embed = discord.Embed(
        title=title,
        description=f"{prize_text}\n**Giveaway ID:** `{giveaway_id}`\n**Ends:** <t:{end_timestamp}:R> (<t:{end_timestamp}:F>)",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="📋 How to Enter",
        value="Click the **Enter Giveaway** button below!",
        inline=False
    )
    embed.add_field(
        name="🎫 Get More Tickets",
        value=(
            "Everyone gets **1 base ticket**!\n"
            f"✨ **{BONUS_ROLE_NAME}** server tag: **+{BONUS_ROLE_TICKETS} bonus ticket**\n"
            f"👥 Invite friends: **+1 ticket per invite** (max {MAX_EXTRA_TICKETS})\n"
            f"**Max total: {1 + MAX_EXTRA_TICKETS + BONUS_ROLE_TICKETS} tickets**"
        ),
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
        f'✅ Giveaway created in {target_channel.mention}!\nGiveaway ID: `{giveaway_id}`\nWinners: {winners}\nDuration: {duration_hours} hours\nEnds: <t:{end_timestamp}:F>',
        ephemeral=True
    )
    
    # Post the giveaway in the target channel with @everyone mention
    message = await target_channel.send(content="@everyone", embed=embed, view=view)
    
    # Store message ID for reference
    giveaway_data[guild_key][giveaway_id]['message_id'] = str(message.id)
    save_giveaway_data()
    
    # Schedule automatic ending
    asyncio.create_task(auto_end_giveaway(guild_key, giveaway_id, duration_hours * 3600, target_channel))

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
    
    # Get number of winners
    num_winners = giveaway_data[guild_key][giveaway_id].get('winners', 1)
    num_winners = min(num_winners, len(set(ticket_pool)))  # Can't have more winners than unique participants
    
    # Pick winners (without replacement)
    winner_ids = []
    temp_pool = ticket_pool.copy()
    for _ in range(num_winners):
        if not temp_pool:
            break
        winner_id = random.choice(temp_pool)
        winner_ids.append(winner_id)
        # Remove all tickets from this winner to prevent duplicate wins
        temp_pool = [uid for uid in temp_pool if uid != winner_id]
    
    # Mark giveaway as ended
    prize = giveaway_data[guild_key][giveaway_id]['prize']
    giveaway_data[guild_key][giveaway_id]['active'] = False
    giveaway_data[guild_key][giveaway_id]['winners_list'] = [str(wid) for wid in winner_ids]
    giveaway_data[guild_key][giveaway_id]['ended_at'] = datetime.now().isoformat()
    giveaway_data[guild_key][giveaway_id]['total_entries'] = len(entries_data[guild_key][giveaway_id])
    save_giveaway_data()
    
    # Announce winners
    title = "🎊 GIVEAWAY WINNER! 🎊" if len(winner_ids) == 1 else f"🎊 GIVEAWAY WINNERS! 🎊"
    
    # Check if there's prize distribution
    prize_dist = giveaway_data[guild_key][giveaway_id].get('prize_distribution')
    
    winners_text = ""
    for idx, winner_id in enumerate(winner_ids, 1):
        winner = interaction.guild.get_member(winner_id)
        winner_tickets = get_user_tickets(interaction.guild.id, winner_id, giveaway_id)
        
        if prize_dist and len(prize_dist) >= idx:
            # Show specific prize for this position
            winner_prize = prize_dist[idx - 1]
            winners_text += f"**{idx}.** {winner.mention} - **{winner_prize}** ({winner_tickets} tickets)\n"
        elif len(winner_ids) == 1:
            winners_text = f"**{winner.mention}** has won **{prize}**!"
        else:
            winners_text += f"**{idx}.** {winner.mention} ({winner_tickets} tickets)\n"
    
    if len(winner_ids) > 1:
        if prize_dist:
            description = f"**Winners:**\n{winners_text}"
        else:
            description = f"**Prize:** {prize}\n\n**Winners:**\n{winners_text}"
    else:
        description = winners_text
    
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.green()
    )
    embed.add_field(name="Total Participants", value=f"{len(entries_data[guild_key][giveaway_id])}", inline=True)
    embed.add_field(name="Total Ticket Entries", value=f"{len(ticket_pool)}", inline=True)
    embed.add_field(name="Giveaway ID", value=f"`{giveaway_id}`", inline=True)
    
    if len(winner_ids) == 1:
        embed.set_thumbnail(url=interaction.guild.get_member(winner_ids[0]).display_avatar.url)
    
    embed.set_footer(text="Congratulations! 🎉")
    
    # Send confirmation to admin
    winners_count_text = "Winner" if len(winner_ids) == 1 else f"{len(winner_ids)} winners"
    await interaction.response.send_message(
        f'✅ Giveaway `{giveaway_id}` ended! {winners_count_text} announced in {target_channel.mention}',
        ephemeral=True
    )
    
    # Announce winner in target channel
    await target_channel.send(embed=embed)

class LeaderboardView(discord.ui.View):
    def __init__(self, member_tickets, prize, giveaway_id, is_active, total_tickets, page=0):
        super().__init__(timeout=180)
        self.member_tickets = member_tickets
        self.prize = prize
        self.giveaway_id = giveaway_id
        self.is_active = is_active
        self.total_tickets = total_tickets
        self.page = page
        self.per_page = 10
        self.max_pages = (len(member_tickets) - 1) // self.per_page
        
        # Update button states
        self.update_buttons()
    
    def update_buttons(self):
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= self.max_pages
    
    def get_embed(self):
        status_emoji = "🟢" if self.is_active else "🔴"
        status_text = "Active" if self.is_active else "Ended"
        
        embed = discord.Embed(
            title=f"🏆 Leaderboard: {self.prize}",
            description=f"**Giveaway ID:** `{self.giveaway_id}`\n**Status:** {status_emoji} {status_text}\n**Total Participants:** {len(self.member_tickets)}\n**Total Tickets:** {self.total_tickets}",
            color=discord.Color.gold() if self.is_active else discord.Color.greyple()
        )
        
        start_idx = self.page * self.per_page
        end_idx = start_idx + self.per_page
        page_members = self.member_tickets[start_idx:end_idx]
        
        for idx, (member, tickets, invites) in enumerate(page_members, start_idx + 1):
            medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
            percentage = (tickets / self.total_tickets * 100) if self.total_tickets > 0 else 0
            embed.add_field(
                name=f"{medal} {member.display_name}",
                value=f"🎫 {tickets} tickets ({invites} invites) - {percentage:.1f}% chance",
                inline=False
            )
        
        embed.set_footer(text=f"Page {self.page + 1}/{self.max_pages + 1} • Showing {start_idx + 1}-{min(end_idx, len(self.member_tickets))} of {len(self.member_tickets)}")
        return embed
    
    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.gray)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)
    
    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.max_pages, self.page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

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
    
    # Create view with pagination
    view = LeaderboardView(member_tickets, prize, giveaway_id, is_active, total_tickets)
    embed = view.get_embed()
    
    await interaction.response.send_message(embed=embed, view=view)

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

@bot.tree.command(name='debuginvites', description='Debug invite data (Admin only)')
@discord.app_commands.checks.has_permissions(administrator=True)
async def debug_invites(interaction: discord.Interaction):
    """Debug invite data"""
    guild_key = str(interaction.guild.id)
    
    if guild_key not in invite_data or not invite_data[guild_key]:
        await interaction.response.send_message('❌ No invite data found for this server!', ephemeral=True)
        return
    
    debug_text = "**Invite Data:**\n"
    for user_id, data in invite_data[guild_key].items():
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"User {user_id}"
        debug_text += f"{name}: {data['invites']} invites\n"
    
    await interaction.response.send_message(debug_text, ephemeral=True)

@bot.tree.command(name='addtickets', description='Manually add bonus tickets to a user (Admin only)')
@discord.app_commands.describe(
    user='The user to give bonus tickets to',
    tickets='Number of bonus tickets to add (can be negative to remove)'
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def add_tickets(interaction: discord.Interaction, user: discord.Member, tickets: int):
    """Manually add bonus tickets to a user"""
    guild_key = str(interaction.guild.id)
    user_key = str(user.id)
    
    # Initialize data structures
    if guild_key not in invite_data:
        invite_data[guild_key] = {}
    
    if user_key not in invite_data[guild_key]:
        invite_data[guild_key][user_key] = {'invites': 0, 'manual_bonus': 0}
    
    if 'manual_bonus' not in invite_data[guild_key][user_key]:
        invite_data[guild_key][user_key]['manual_bonus'] = 0
    
    # Add bonus tickets
    invite_data[guild_key][user_key]['manual_bonus'] += tickets
    save_invite_data()
    
    # Get updated ticket count
    total_tickets = get_user_tickets(interaction.guild.id, user.id)
    manual_bonus = invite_data[guild_key][user_key]['manual_bonus']
    
    action = "added" if tickets > 0 else "removed"
    await interaction.response.send_message(
        f'✅ {action.capitalize()} {abs(tickets)} bonus ticket(s) for {user.mention}!\n'
        f'Manual bonus: {manual_bonus} | Total tickets: {total_tickets}',
        ephemeral=True
    )

@bot.tree.command(name='removetickets', description='Remove bonus tickets from a user (Admin only)')
@discord.app_commands.describe(
    user='The user to remove bonus tickets from',
    tickets='Number of bonus tickets to remove'
)
@discord.app_commands.checks.has_permissions(administrator=True)
async def remove_tickets(interaction: discord.Interaction, user: discord.Member, tickets: int):
    """Remove bonus tickets from a user"""
    guild_key = str(interaction.guild.id)
    user_key = str(user.id)
    
    # Initialize data structures
    if guild_key not in invite_data:
        invite_data[guild_key] = {}
    
    if user_key not in invite_data[guild_key]:
        invite_data[guild_key][user_key] = {'invites': 0, 'manual_bonus': 0}
    
    if 'manual_bonus' not in invite_data[guild_key][user_key]:
        invite_data[guild_key][user_key]['manual_bonus'] = 0
    
    # Remove bonus tickets (make tickets negative)
    invite_data[guild_key][user_key]['manual_bonus'] -= tickets
    save_invite_data()
    
    # Get updated ticket count
    total_tickets = get_user_tickets(interaction.guild.id, user.id)
    manual_bonus = invite_data[guild_key][user_key]['manual_bonus']
    
    await interaction.response.send_message(
        f'✅ Removed {tickets} bonus ticket(s) from {user.mention}!\n'
        f'Manual bonus: {manual_bonus} | Total tickets: {total_tickets}',
        ephemeral=True
    )

# Run the bot
if __name__ == '__main__':
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    if not TOKEN:
        print('Error: DISCORD_BOT_TOKEN environment variable not set!')
        print('Please create a .env file with: DISCORD_BOT_TOKEN=your_token_here')
    else:
        bot.run(TOKEN)
