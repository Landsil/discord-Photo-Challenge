import discord
from discord.ext import commands
from discord import app_commands
import os
import csv
import re
import sys
import threading # Used to run the bot and the web server simultaneously
from datetime import datetime

# Import Flask for the required HTTP health check listener
from flask import Flask

# --- Configuration using Environment Variables (Injected by Cloud Run) ---
# These variables are securely injected from GCP Secret Manager.
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID')
DISCORD_THREAD_URL = os.environ.get('DISCORD_THREAD_URL') 
PORT = int(os.environ.get('PORT', 8080))

# --- Bot Setup ---
class PhotoBot(commands.Bot):
    def __init__(self, intents):
        # We use a placeholder prefix as the bot will rely on slash commands
        super().__init__(command_prefix="!", intents=intents) 
        self.default_thread_url = DISCORD_THREAD_URL

    async def setup_hook(self):
        # Sync the application commands (slash commands) with Discord
        if DISCORD_CLIENT_ID:
            try:
                # Sync commands globally
                await self.tree.sync()
                print("Slash commands synced successfully.")
            except Exception as e:
                print(f"Failed to sync commands: {e}")

    async def on_ready(self):
        print(f'Bot is running. Logged in as {self.user} (ID: {self.user.id})')
        print(f'Default Thread URL: {self.default_thread_url}')
        
    async def on_error(self, event_method, *args, **kwargs):
        print(f'Ignoring exception in {event_method}', file=sys.stderr)
        
    async def on_command_error(self, context, exception):
        if isinstance(exception, commands.CommandNotFound):
            return
        print(f"Command Error: {exception}", file=sys.stderr)

# --- Core Logic Functions (Retained from previous versions) ---

def extract_thread_id_from_url(url):
    """Extracts the thread ID from a Discord URL."""
    match = re.search(r'/(\d+)$', url)
    return int(match.group(1)) if match else None

async def get_thread_messages(thread_id, client):
    """Fetches messages from a specific Discord thread."""
    try:
        thread = client.get_channel(thread_id)
        if not thread:
            thread = await client.fetch_channel(thread_id)
        
        if not thread:
            print(f"Error: Could not find thread with ID {thread_id}.")
            return []

        messages = []
        async for message in thread.history(limit=None):
            messages.append(message)
        return messages
    except (discord.errors.Forbidden, discord.errors.NotFound) as e:
        print(f"Permission/Access Error: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error fetching messages: {e}")
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
        async for user in reaction.users():
            if user.id != author_id:
                total_reactions += 1
                emoji_str = str(reaction.emoji)
                individual_reaction_counts[emoji_str] = individual_reaction_counts.get(emoji_str, 0) + 1

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
        print(f"No data to write to {filename}.")
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
        print(f"Data successfully written to temporary file {filepath}")
        return filepath
    except IOError as e:
        print(f"Error writing to CSV file {filepath}: {e}")
        return None

def generate_markdown_output(data, num_top_posts, total_image_posts_count,
                             total_thread_reactions, total_unique_reactors_count,
                             include_image_links):
    """Generates Discord-formatted Markdown for the top posts."""
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

# --- Discord Command Implementation ---

async def run_photo_challenge(interaction: discord.Interaction, target_url: str):
    """Core logic to fetch data, process, and send results."""
    
    thread_id = extract_thread_id_from_url(target_url)

    if not thread_id:
        await interaction.followup.send(
            "⚠️ **Invalid URL:** Please provide a full, valid Discord thread URL.",
            ephemeral=True
        )
        return
        
    await interaction.followup.send(f"Fetching data from thread ID `{thread_id}`... This may take a moment.")

    # 1. Fetch Data
    # interaction.client refers to the running bot instance
    all_messages = await get_thread_messages(thread_id, interaction.client) 
    
    # 2. Filter and Process
    image_messages = filter_image_posts(all_messages)
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

    # 4. Generate CSV (Save to temporary storage)
    thread_name = interaction.channel.name if isinstance(interaction.channel, (discord.Thread, discord.TextChannel)) else "Unknown_Thread"
    sanitized_name = re.sub(r'[^\w\s-]', '', thread_name)
    sanitized_name = re.sub(r'\s+', '_', sanitized_name).strip()
    csv_filename = f"{sanitized_name}_results.csv" if sanitized_name else "image_posts_reactions_results.csv"
    csv_filepath = generate_csv(processed_data, filename=csv_filename)
    
    # 5. Generate Markdown Outputs
    
    # Full Version
    markdown_output_full = generate_markdown_output(
        processed_data, 5, total_image_posts_count, total_thread_reactions, total_unique_reactors_count, True
    )

    # Short Version
    markdown_output_short = generate_markdown_output(
        processed_data, 5, total_image_posts_count, total_thread_reactions, total_unique_reactors_count, False
    )

    # 6. Send Results to Discord
    
    # Send the short version directly to the channel
    try:
        await interaction.channel.send(markdown_output_short)
    except Exception as e:
        await interaction.followup.send(f"Error posting results to channel: {e}", ephemeral=True)
        
    # Send CSV file and full report to the user as a DM
    try:
        if csv_filepath:
            await interaction.user.send(
                "Attached is the full CSV data. Here is the detailed report:",
                file=discord.File(csv_filepath),
            )
        else:
             await interaction.user.send(
                "Could not generate CSV file due to an error. Here is the detailed report:",
            )

        await interaction.user.send(markdown_output_full)
        await interaction.followup.send("✅ Results successfully posted to the channel and sent to you via DM with the full CSV file.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Could not send full report or CSV to your DM: {e}. Check bot permissions.", ephemeral=True)
        
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
         await interaction.followup.send("Error: No thread URL provided. Please use `/photocommand <URL>` or set the `DISCORD_THREAD_URL` environment variable.", ephemeral=True)
         return

    if not interaction.guild:
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
        await interaction.followup.send("✅ Help guide sent to your Direct Messages.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("⚠️ I cannot send you a DM. Please check your privacy settings or enable DMs from this guild.", ephemeral=True)
    except Exception as e:
        print(f"Error sending help DM: {e}")
        await interaction.followup.send("⚠️ An error occurred while sending the DM.", ephemeral=True)


# --- Flask Routes ---
@app.route('/', methods=['GET'])
def health_check():
    """
    HTTP route for the Cloud Run health check. 
    Responds 200 OK to keep the container running.
    """
    return "Bot is running.", 200

# --- Execution ---

def run_bot():
    """Starts the Discord bot client."""
    if not DISCORD_BOT_TOKEN:
        print("FATAL ERROR: DISCORD_BOT_TOKEN environment variable is not set.", file=sys.stderr)
        sys.exit(1)
        
    try:
        # This runs the bot on its own thread, managing the Discord WebSocket connection
        bot.run(DISCORD_BOT_TOKEN)
    except discord.errors.LoginFailure:
        print("Login Failure: Check DISCORD_BOT_TOKEN environment variable.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred in the bot thread: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    print("Starting hybrid application...")
    
    # 1. Start the Discord bot in a separate thread
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    print("Discord Bot thread started.")
    
    # 2. Start the Flask web server (required for Cloud Run health checks)
    # Gunicorn, configured in the Dockerfile, will invoke 'app' and handle this.
    # The container will stay alive as long as this Flask app is responsive.
    print(f"Starting Flask server on port {PORT}...")
    # Using 'gunicorn' command is safer for Cloud Run; this direct app.run is mainly for local dev.
    # The Gunicorn command in the Dockerfile is the primary entrypoint.
    # app.run(host="0.0.0.0", port=PORT, debug=False) # Uncomment for local testing
