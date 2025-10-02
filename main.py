import discord
from discord.ext import commands
from discord import app_commands
import os
import csv
import re
import sys
import asyncio
from datetime import datetime

# Import Flask for the required HTTP health check listener
from flask import Flask
import threading

# --- Configuration using Environment Variables (Injected by Cloud Run) ---
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID')
DISCORD_THREAD_URL = os.environ.get('DISCORD_THREAD_URL')
PORT = int(os.environ.get('PORT', 8080))

# --- Global Bot State ---
bot = None
bot_task = None

# --- Bot Setup ---
class PhotoBot(commands.Bot):
    def __init__(self, intents):
        super().__init__(command_prefix="!", intents=intents)
        self.default_thread_url = DISCORD_THREAD_URL

    async def setup_hook(self):
        # Sync the application commands (slash commands) with Discord
        if DISCORD_CLIENT_ID:
            try:
                # Sync commands globally
                await self.tree.sync()
                print("LOG: Slash commands synced successfully.", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"ERROR: Failed to sync slash commands. Check bot permissions and application ID. Details: {e}", file=sys.stderr, flush=True)

    async def on_ready(self):
        print(f'LOG: Bot is running. Logged in as {self.user} (ID: {self.user.id})', file=sys.stderr, flush=True)
        print(f'LOG: Default Thread URL from ENV: {self.default_thread_url}', file=sys.stderr, flush=True)

    async def on_error(self, event_method, *args, **kwargs):
        # Log Discord internal errors
        print(f'ERROR: Ignoring exception in Discord event handler: {event_method}', file=sys.stderr, flush=True)

    async def on_command_error(self, context, exception):
        if isinstance(exception, commands.CommandNotFound):
            return
        # Log command-specific errors
        print(f"ERROR: Command execution failed. Command: {context.command}. Details: {exception}", file=sys.stderr, flush=True)

# --- Core Logic Functions (No changes here) ---
def extract_thread_id_from_url(url):
    """Extracts the thread ID from a Discord URL."""
    match = re.search(r'/(\d+)$', url)
    if match:
        return int(match.group(1))
    else:
        print(f"ERROR: Failed to extract thread ID from URL: {url}. Regex did not match.", file=sys.stderr, flush=True)
        return None

async def get_thread_messages(thread_id, client):
    """Fetches messages from a specific Discord thread."""
    try:
        thread = client.get_channel(thread_id)
        if not thread:
            print(f"LOG: Attempting to fetch thread {thread_id} using client.fetch_channel...", file=sys.stderr, flush=True)
            thread = await client.fetch_channel(thread_id)
        
        if not thread:
            print(f"ERROR: Could not find thread with ID {thread_id}. Ensure bot is in the server and the ID is correct.", file=sys.stderr, flush=True)
            return []

        print(f"LOG: Successfully found thread '{thread.name}'. Starting message history fetch.", file=sys.stderr, flush=True)
        messages = []
        async for message in thread.history(limit=None):
            messages.append(message)
        print(f"LOG: Successfully fetched {len(messages)} messages.", file=sys.stderr, flush=True)
        return messages
    except discord.errors.Forbidden as e:
        print(f"ERROR: Permission denied to access thread {thread_id}. Check bot's roles/permissions. Details: {e}", file=sys.stderr, flush=True)
        return []
    except discord.errors.NotFound as e:
        print(f"ERROR: Thread {thread_id} not found on Discord. Details: {e}", file=sys.stderr, flush=True)
        return []
    except Exception as e:
        print(f"ERROR: Unexpected error fetching messages from thread {thread_id}. Details: {e}", file=sys.stderr, flush=True)
        return []

def filter_image_posts(messages):
    """Filters messages to include only those with images."""
    image_posts = []
    for message in messages:
        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith('image/'):
                    image_posts.append(message)
                    break
    return image_posts

async def get_post_data(message):
    """Extracts data from a message, excluding author's own reactions."""
    guild_id = message.guild.id if message.guild else "unknown_guild"
    post_link = f"https://discord.com/channels/{guild_id}/{message.channel.id}/{message.id}"
    image_links = [att.url for att in message.attachments if att.content_type and att.content_type.startswith('image/')]

    total_reactions = 0
    individual_reaction_counts = {}
    author_id = message.author.id

    for reaction in message.reactions:
        try:
            async for user in reaction.users():
                if user.id != author_id:
                    total_reactions += 1
                    emoji_str = str(reaction.emoji)
                    individual_reaction_counts[emoji_str] = individual_reaction_counts.get(emoji_str, 0) + 1
        except Exception as e:
            print(f"WARNING: Failed to fetch users for reaction {reaction.emoji} on message {message.id}. Details: {e}", file=sys.stderr, flush=True)
            continue # Continue to the next reaction

    individual_reactions = [{"emoji": emoji, "count": count} for emoji, count in individual_reaction_counts.items()]
    sorted_individual_reactions = sorted(individual_reactions, key=lambda x: x["count"], reverse=True)

    return {
        "post_link": post_link,
        "image_links": ", ".join(image_links),
        "posted_at": message.created_at.isoformat(),
        "author": message.author.display_name,
        "reactions": total_reactions,
        "individual_reactions": sorted_individual_reactions
    }

def generate_csv(data, filename):
    """
    Generates a CSV file from the extracted post data.
    Saves to /tmp/ which is the only writable path in Cloud Run.
    """
    if not data:
        print(f"WARNING: No data to write to {filename}. Skipping CSV generation.", file=sys.stderr, flush=True)
        return None

    fieldnames = ["post_link", "image_links", "posted_at", "author", "reactions"]
    csv_data = []
    for item in data:
        temp_item = item.copy()
        temp_item.pop('individual_reactions', None)
        csv_data.append(temp_item)

    try:
        # Use /tmp for writable storage in Cloud Run
        filepath = f"/tmp/{filename}"
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_data)
        print(f"LOG: Data successfully written to temporary CSV file: {filepath}", file=sys.stderr, flush=True)
        return filepath
    except IOError as e:
        print(f"ERROR: Failed to write CSV file to {filepath}. Check /tmp directory permissions (should be fine in GCR). Details: {e}", file=sys.stderr, flush=True)
        return None

def generate_markdown_output(data, num_top_posts, total_image_posts_count,
                             total_thread_reactions, total_unique_reactors_count,
                             include_image_links):
    """Generates Discord-formatted Markdown for the top posts."""
    # (Markdown generation logic remains the same for brevity)
    markdown = "__Photo Challenge Report__\n\n"
    markdown += f"- Total photos: `{total_image_posts_count}`\n"
    markdown += f"- Total votes (excluding author's own): `{total_thread_reactions}`\n"
    markdown += f"- Total unique users who voted : `{total_unique_reactors_count}`\n\n"
    markdown += "__Top Image Posts by Reactions:__\n\n"

    if not data or all(d['reactions'] == 0 for d in data):
        markdown += "No posts found with external votes to display."
        return markdown

    sorted_data = sorted(data, key=lambda x: x["reactions"], reverse=True)
    grouped_posts = {}
    for post in sorted_data:
        reactions = post['reactions']
        if reactions not in grouped_posts:
            grouped_posts[reactions] = []
        grouped_posts[reactions].append(post)

    sorted_groups = sorted(grouped_posts.keys(), reverse=True)

    current_rank = 1
    output_lines = []

    for reactions in sorted_groups:
        if current_rank > num_top_posts:
            break

        posts_in_group = grouped_posts[reactions]
        
        # Start a new rank entry
        group_lines = []
        
        # Conditionally include reactions for the rank spot only in the full version
        rank_reactions_info = f" (Votes: `{reactions}`)" if include_image_links else ""
        group_lines.append(f"**{current_rank}.**{rank_reactions_info}")
        
        for post in posts_in_group:
            # Post link and author
            group_lines.append(f"   - **[Post by {post['author']}]({post['post_link']})**")
            
            # Conditionally include image links (Full version)
            if include_image_links:
                image_link = post['image_links'].split(', ')[0]
                if image_link:
                    group_lines.append(f"      - [Image URL]({image_link})")
            
            # Conditionally include individual reactions (Full version)
            if include_image_links:
                reactions_str = ""
                if post['individual_reactions']:
                    reactions_emojis = [r['emoji'] for r in post['individual_reactions']]
                    reactions_str = " (" + " ".join(reactions_emojis) + ")"
                
                group_lines.append(f"      - Post Votes: `{post['reactions']}`{reactions_str}")

        output_lines.extend(group_lines)
        current_rank += 1
        
    return markdown + "\n".join(output_lines)

# --- Discord Command Implementation (No changes here) ---

async def run_photo_challenge(interaction: discord.Interaction, target_url: str):
    """Core logic to fetch data, process, and send results."""
    
    print(f"LOG: Command received from {interaction.user.name}. Analyzing URL: {target_url}", file=sys.stderr, flush=True)
    
    thread_id = extract_thread_id_from_url(target_url)

    if not thread_id:
        print(f"ERROR: Command failed due to invalid thread ID extracted from URL: {target_url}", file=sys.stderr, flush=True)
        await interaction.followup.send(
            "⚠️ **Invalid URL:** Please provide a full, valid Discord thread URL.",
            ephemeral=True
        )
        return
        
    await interaction.followup.send(f"Fetching data from thread ID `{thread_id}`... This may take a moment.")

    # 1. Fetch Data
    all_messages = await get_thread_messages(thread_id, interaction.client) 
    
    if not all_messages:
        print(f"WARNING: No messages were returned for thread {thread_id}. Terminating analysis.", file=sys.stderr, flush=True)
        await interaction.followup.send("⚠️ Could not fetch any messages. Check thread ID and bot permissions.", ephemeral=True)
        return

    # 2. Filter and Process
    image_messages = filter_image_posts(all_messages)
    print(f"LOG: Found {len(image_messages)} image posts to process.", file=sys.stderr, flush=True)
    processed_data = [await get_post_data(msg) for msg in image_messages]
    
    # 3. Calculate Summary Metrics
    total_image_posts_count = len(processed_data)
    total_thread_reactions = 0
    unique_reactors_ids = set()

    for message in image_messages:
        author_id = message.author.id
        for reaction in message.reactions:
            async for user in reaction.users():
                if user.id != author_id:
                    total_thread_reactions += 1
                    unique_reactors_ids.add(user.id)
    total_unique_reactors_count = len(unique_reactors_ids)
    print(f"LOG: Analysis complete. Total reactions: {total_thread_reactions}, Unique reactors: {total_unique_reactors_count}", file=sys.stderr, flush=True)


    # 4. Generate CSV (Save to temporary storage)
    thread_name = interaction.channel.name if isinstance(interaction.channel, (discord.Thread, discord.TextChannel)) else "Unknown_Thread"
    sanitized_name = re.sub(r'[^\w\s-]', '', thread_name)
    sanitized_name = re.sub(r'\s+', '_', sanitized_name).strip()
    csv_filename = f"{sanitized_name}_results.csv" if sanitized_name else "image_posts_reactions_results.csv"
    csv_filepath = generate_csv(processed_data, filename=csv_filename)
    
    # 5. Generate Markdown Outputs
    markdown_output_full = generate_markdown_output(
        processed_data, 5, total_image_posts_count, total_thread_reactions, total_unique_reactors_count, True
    )
    markdown_output_short = generate_markdown_output(
        processed_data, 5, total_image_posts_count, total_thread_reactions, total_unique_reactors_count, False
    )

    # 6. Send Results to Discord
    
    # Send the short version directly to the channel
    try:
        await interaction.channel.send(markdown_output_short)
        print("LOG: Short report posted to channel.", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"ERROR: Failed to post short report to channel {interaction.channel.id}. Details: {e}", file=sys.stderr, flush=True)
        await interaction.followup.send(f"Error posting results to channel: {e}", ephemeral=True)
        
    # Send CSV file and full report to the user as a DM
    try:
        if csv_filepath:
            await interaction.user.send(
                "Attached is the full CSV data. Here is the detailed report:",
                file=discord.File(csv_filepath),
            )
            print("LOG: CSV file sent via DM.", file=sys.stderr, flush=True)
        else:
             await interaction.user.send(
                "Could not generate CSV file due to an error. Here is the detailed report:",
            )

        await interaction.user.send(markdown_output_full)
        print("LOG: Full report sent via DM.", file=sys.stderr, flush=True)
        await interaction.followup.send("✅ Results successfully posted to the channel and sent to you via DM with the full CSV file.", ephemeral=True)
    except Exception as e:
        print(f"ERROR: Failed to send DM to user {interaction.user.name}. Check if user allows DMs from this guild. Details: {e}", file=sys.stderr, flush=True)
        await interaction.followup.send(f"⚠️ Could not send full report or CSV to your DM. Check bot permissions and your privacy settings. Error: {e}", ephemeral=True)
        
# --- Flask Server and Bot Integration ---

app = Flask(__name__)

# Intents required for messages, reactions, and thread content
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.members = True

# Initialize the Bot instance
bot = PhotoBot(intents=intents)

# Register the slash command functions with the bot's command tree
@bot.tree.command(name="photocommand", description="Runs the photo challenge counter and generates reports.")
@app_commands.describe(
    target_url="The full URL of the Discord thread to analyze. Overrides default."
)
async def run_command(interaction: discord.Interaction, target_url: str = None):
    """Slash command handler."""
    await interaction.response.defer(thinking=True, ephemeral=True)

    url = target_url or bot.default_thread_url
    if not url:
         print("ERROR: Command executed without URL and DISCORD_THREAD_URL environment variable is missing.", file=sys.stderr, flush=True)
         await interaction.followup.send("Error: No thread URL provided. Please use `/photocommand <URL>` or ensure the `DISCORD_THREAD_URL` environment variable is set in Cloud Run.", ephemeral=True)
         return

    if not interaction.guild:
        print("WARNING: Command executed outside of a guild context (DM?). Ignoring.", file=sys.stderr, flush=True)
        await interaction.followup.send("This command must be run inside a Discord server channel.", ephemeral=True)
        return

    await run_photo_challenge(interaction, url)


@bot.tree.command(name="photocommandhelp", description="Displays basic info and commands.")
async def help_command(interaction: discord.Interaction):
    """Help command handler that sends a DM to the user."""
    await interaction.response.defer(thinking=True, ephemeral=True)

    help_markdown = f"""
    **🤖 Photo Challenge Counter Bot Help**
    
    This bot analyzes a Discord thread, identifies image posts, and counts reactions (excluding self-reactions) to determine the top submissions.
    
    **Available Commands:**
    1. `/photocommandhelp`: Displays this help message (DM).
    2. `/photocommand run [target_url]`: Runs the analysis on a specified thread.
       - `target_url` (optional): The full URL of the Discord thread you want to analyze. If omitted, the bot uses the default URL configured in its settings.
    
    **Output:**
    - A summarized report is posted directly to the channel.
    - The full detailed report (with image links) and a CSV file are sent to your Direct Messages (DM).
    
    *Note: The bot must have read access to the channel and the thread to function.*
    """
    try:
        await interaction.user.send(help_markdown)
        print(f"LOG: Sent help DM to user {interaction.user.name}.", file=sys.stderr, flush=True)
        await interaction.followup.send("✅ Help guide sent to your Direct Messages.", ephemeral=True)
    except discord.Forbidden:
        print(f"WARNING: Failed to send help DM to {interaction.user.name}. User likely disabled DMs.", file=sys.stderr, flush=True)
        await interaction.followup.send("⚠️ I cannot send you a DM. Please check your privacy settings or enable DMs from this guild.", ephemeral=True)
    except Exception as e:
        print(f"ERROR: Unexpected error sending help DM to {interaction.user.name}. Details: {e}", file=sys.stderr, flush=True)
        await interaction.followup.send("⚠️ An unexpected error occurred while sending the DM.", ephemeral=True)


# --- Flask Routes ---
@app.route('/', methods=['GET'])
def health_check():
    """
    HTTP route for the Cloud Run health check.
    Responds 200 OK to keep the container running.
    """
    if bot_thread and bot_thread.is_alive():
        if bot and bot.is_ready():
            return "Bot is running and ready.", 200
        else:
            # Bot thread is running but not fully connected/ready yet. This is a valid state during startup.
            return "Bot thread is running but not ready.", 200
    else:
        # If the bot thread is down, the service is unhealthy.
        print("WARNING: Web server running, but Discord Bot thread is detected as DOWN.", file=sys.stderr, flush=True)
        return "Web server running. Bot thread status: DOWN.", 503 # Service Unavailable


# --- Asynchronous Bot Management ---

async def run_bot_async():
    """Starts the Discord bot client asynchronously without blocking the event loop."""
    global bot
    try:
        token = os.environ.get('DISCORD_BOT_TOKEN')
        if not token:
            print("CRITICAL ERROR: DISCORD_BOT_TOKEN environment variable is not set. Bot cannot connect.", file=sys.stderr, flush=True)
            return

        print("LOG: Attempting to login and connect Discord bot...", file=sys.stderr, flush=True)
        # Use login() and connect() instead of start() to integrate with Uvicorn's event loop
        await bot.login(token)
        await bot.connect(reconnect=True)

    except discord.errors.LoginFailure:
        print("CRITICAL ERROR: Discord Login Failure. Check DISCORD_BOT_TOKEN value in Secret Manager.", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"CRITICAL ERROR: An unexpected, unhandled error occurred in the bot task: {e}", file=sys.stderr, flush=True)


def run_bot_in_thread():
    """Run the Discord bot in a separate thread with its own event loop."""
    global bot_task
    try:
        print("LOG: Starting Discord bot in background thread...", file=sys.stderr, flush=True)
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run the bot
        token = os.environ.get('DISCORD_BOT_TOKEN')
        if not token:
            print("CRITICAL ERROR: DISCORD_BOT_TOKEN environment variable is not set. Bot cannot connect.", file=sys.stderr, flush=True)
            return
            
        print("LOG: Attempting to start Discord bot...", file=sys.stderr, flush=True)
        loop.run_until_complete(bot.start(token))
    except Exception as e:
        print(f"CRITICAL ERROR: Discord bot thread failed: {e}", file=sys.stderr, flush=True)

# Start the Discord bot in a background thread when the module loads
bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
bot_thread.start()
print("LOG: Discord bot thread started.", file=sys.stderr, flush=True)
