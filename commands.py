import discord
from discord import app_commands
from discord.ext import commands
import sys
import re

# Import the core logic functions
from core_logic import (
    extract_thread_id_from_url,
    get_thread_messages,
    filter_image_posts,
    get_post_data,
    generate_csv,
    generate_markdown_output
)

def setup_commands(bot):
    """Set up all slash commands for the bot."""
    
    @bot.tree.command(name="photochallenge", description="Photo challenge analysis and help commands.")
    @app_commands.describe(
        operation="Choose the operation to perform"
    )
    @app_commands.choices(operation=[
        app_commands.Choice(name="full", value="full"),
        app_commands.Choice(name="short", value="short"),
        app_commands.Choice(name="help", value="help")
    ])
    async def photochallenge_command(interaction: discord.Interaction, operation: str):
        """Main photo challenge command with operations."""
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        if operation == "help":
            await handle_help_command(interaction)
        elif operation == "full":
            await handle_full_analysis(interaction)
        elif operation == "short":
            await handle_short_analysis(interaction)
        else:
            await interaction.followup.send("⚠️ Invalid operation. Use 'full' for complete analysis, 'short' for summary only, or 'help' for information.", ephemeral=True)

async def handle_help_command(interaction: discord.Interaction):
    """Handle the help command."""
    help_markdown = """**🤖 Photo Challenge Counter Bot Help**

This bot analyzes Discord threads to identify image posts and count reactions (excluding self-reactions) to determine top submissions.

**Available Commands:**
• `/photochallenge help` - Displays this help message (sent via DM)
• `/photochallenge full` - Runs complete analysis with rankings, names, and CSV data
• `/photochallenge short` - Runs basic analysis with summary statistics only (no names/rankings)

**How it works:**
1. Run the command in the thread you want to analyze
2. The bot scans all messages in that thread for images
3. It counts reactions on image posts (excluding the author's own reactions)
4. All results are sent privately to your DMs

**Command Details:**

**`/photochallenge full`** (Complete Analysis):
- Summary with total photos, votes, and unique voters
- Top 5 rankings with participant names and links
- Detailed breakdown with image links and reaction counts
- Downloadable CSV file with all data

**`/photochallenge short`** (Summary Only):
- Total photos submitted
- Total votes cast (excluding authors)
- Number of unique voters
- No names, rankings, or detailed data

*Note: The bot needs read access to the thread and permission to send you DMs.*
"""
    
    try:
        await interaction.user.send(help_markdown)
        print(f"LOG: Sent help DM to user {interaction.user.name}.", file=sys.stderr, flush=True)
        await interaction.followup.send("✅ Help guide sent to your Direct Messages.", ephemeral=True)
    except discord.Forbidden:
        print(f"WARNING: Failed to send help DM to {interaction.user.name}. User likely disabled DMs.", file=sys.stderr, flush=True)
        await interaction.followup.send("⚠️ I cannot send you a DM. Please check your privacy settings or enable DMs from this server.", ephemeral=True)
    except Exception as e:
        print(f"ERROR: Unexpected error sending help DM to {interaction.user.name}. Details: {e}", file=sys.stderr, flush=True)
        await interaction.followup.send("⚠️ An unexpected error occurred while sending the DM.", ephemeral=True)

async def handle_full_analysis(interaction: discord.Interaction):
    """Handle the full analysis command."""
    
    # Check if command is run in a guild
    if not interaction.guild:
        print("WARNING: Command executed outside of a guild context (DM?). Ignoring.", file=sys.stderr, flush=True)
        await interaction.followup.send("This command must be run inside a Discord server channel.", ephemeral=True)
        return
    
    # Use the current thread/channel for analysis
    thread_id = interaction.channel.id
    print(f"LOG: Full analysis command received from {interaction.user.name} for thread ID: {thread_id}", file=sys.stderr, flush=True)
        
    await interaction.followup.send(f"🔍 Analyzing this thread for photo submissions... This may take a moment.")

    # 1. Fetch Data
    all_messages = await get_thread_messages(thread_id, interaction.client) 
    
    if not all_messages:
        print(f"WARNING: No messages were returned for thread {thread_id}. Terminating analysis.", file=sys.stderr, flush=True)
        await interaction.followup.send("⚠️ Could not fetch any messages. Check thread permissions.", ephemeral=True)
        return

    # 2. Filter and Process
    image_messages = filter_image_posts(all_messages)
    print(f"LOG: Found {len(image_messages)} image posts to process.", file=sys.stderr, flush=True)
    
    if len(image_messages) == 0:
        await interaction.followup.send("📷 No image posts found in this thread.", ephemeral=True)
        return
        
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
    thread_name = interaction.channel.name if hasattr(interaction.channel, 'name') else f"Thread_{thread_id}"
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

    # 6. Generate enhanced report with vote counts per rank
    enhanced_report = generate_enhanced_ranking(processed_data, total_image_posts_count, total_thread_reactions, total_unique_reactors_count)
    
    # 7. Send results via DM only (2 messages total)
    try:
        # Send CSV file first
        if csv_filepath:
            await interaction.user.send(
                "📊 **Photo Challenge Analysis Complete!**\n\nHere's your detailed analysis with CSV data:",
                file=discord.File(csv_filepath),
            )
            print("LOG: CSV file sent via DM.", file=sys.stderr, flush=True)
        else:
             await interaction.user.send(
                "📊 **Photo Challenge Analysis Complete!**\n\nHere's your detailed analysis (CSV generation failed):",
            )

        # Send enhanced ranking report with vote counts per rank
        if len(enhanced_report) > 2000:
            parts = split_message(enhanced_report, 2000)
            for part in parts:
                await interaction.user.send(part)
        else:
            await interaction.user.send(enhanced_report)

        print("LOG: Complete analysis sent via DM.", file=sys.stderr, flush=True)
        await interaction.followup.send("✅ Analysis complete! Results sent to your DMs.", ephemeral=True)
    except Exception as e:
        print(f"ERROR: Failed to send DM to user {interaction.user.name}. Check if user allows DMs from this guild. Details: {e}", file=sys.stderr, flush=True)
        await interaction.followup.send(f"⚠️ Could not send analysis results to your DMs. Check your privacy settings and ensure you allow DMs from this server. Error: {e}", ephemeral=True)

async def handle_short_analysis(interaction: discord.Interaction):
    """Handle the short analysis command - summary only without names."""
    
    # Check if command is run in a guild
    if not interaction.guild:
        print("WARNING: Command executed outside of a guild context (DM?). Ignoring.", file=sys.stderr, flush=True)
        await interaction.followup.send("This command must be run inside a Discord server channel.", ephemeral=True)
        return
    
    # Use the current thread/channel for analysis
    thread_id = interaction.channel.id
    print(f"LOG: Short analysis command received from {interaction.user.name} for thread ID: {thread_id}", file=sys.stderr, flush=True)
        
    await interaction.followup.send(f"🔍 Analyzing this thread for photo submission summary... This may take a moment.")

    # 1. Fetch Data
    all_messages = await get_thread_messages(thread_id, interaction.client) 
    
    if not all_messages:
        print(f"WARNING: No messages were returned for thread {thread_id}. Terminating analysis.", file=sys.stderr, flush=True)
        await interaction.followup.send("⚠️ Could not fetch any messages. Check thread permissions.", ephemeral=True)
        return

    # 2. Filter and Process
    image_messages = filter_image_posts(all_messages)
    print(f"LOG: Found {len(image_messages)} image posts to process.", file=sys.stderr, flush=True)
    
    if len(image_messages) == 0:
        await interaction.followup.send("📷 No image posts found in this thread.", ephemeral=True)
        return
        
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
    print(f"LOG: Short analysis complete. Total reactions: {total_thread_reactions}, Unique reactors: {total_unique_reactors_count}", file=sys.stderr, flush=True)

    # 4. Generate summary-only output (no names, no rankings)
    summary_only = f"""🏆 **Photo Challenge Summary** 🏆

📊 **Statistics:**
• Total photos submitted: `{total_image_posts_count}`
• Total votes (excluding authors): `{total_thread_reactions}`
• Unique voters: `{total_unique_reactors_count}`

📷 Analysis complete for this thread."""

    # 5. Send summary via DM
    try:
        await interaction.user.send(summary_only)
        print("LOG: Summary-only analysis sent via DM.", file=sys.stderr, flush=True)
        await interaction.followup.send("✅ Summary complete! Results sent to your DMs.", ephemeral=True)
    except Exception as e:
        print(f"ERROR: Failed to send DM to user {interaction.user.name}. Check if user allows DMs from this guild. Details: {e}", file=sys.stderr, flush=True)
        await interaction.followup.send(f"⚠️ Could not send summary to your DMs. Check your privacy settings and ensure you allow DMs from this server. Error: {e}", ephemeral=True)

def generate_enhanced_ranking(data, total_image_posts_count, total_thread_reactions, total_unique_reactors_count):
    """Generates enhanced ranking report with vote counts per rank, no image links."""
    markdown = "🏆 **Photo Challenge Results** 🏆\n\n"
    markdown += f"📊 **Summary:**\n"
    markdown += f"• Total photos: `{total_image_posts_count}`\n"
    markdown += f"• Total votes (excluding authors): `{total_thread_reactions}`\n"
    markdown += f"• Unique voters: `{total_unique_reactors_count}`\n\n"
    
    if not data or all(d['reactions'] == 0 for d in data):
        markdown += "📷 No posts found with external votes to display."
        return markdown
    
    markdown += f"🥇 **Top {min(5, len([d for d in data if d['reactions'] > 0]))} Image Posts:**\n\n"

    sorted_data = sorted(data, key=lambda x: x["reactions"], reverse=True)
    grouped_posts = {}
    for post in sorted_data:
        reactions = post['reactions']
        if reactions > 0:  # Only show posts with votes
            if reactions not in grouped_posts:
                grouped_posts[reactions] = []
            grouped_posts[reactions].append(post)

    if not grouped_posts:
        markdown += "No posts found with external votes to display."
        return markdown

    sorted_groups = sorted(grouped_posts.keys(), reverse=True)

    current_rank = 1
    output_lines = []

    for reactions in sorted_groups:
        if current_rank > 5:  # Limit to top 5
            break

        posts_in_group = grouped_posts[reactions]
        
        # Determine rank emoji
        rank_emoji = "🥇" if current_rank == 1 else "🥈" if current_rank == 2 else "🥉" if current_rank == 3 else f"{current_rank}️⃣"
        
        # Start a new rank entry with vote count
        group_lines = []
        group_lines.append(f"{rank_emoji} **Rank {current_rank}** (`{reactions}` votes)")
        
        for post in posts_in_group:
            # Post link and author
            group_lines.append(f"   📸 **[{post['author']}]({post['post_link']})**")
            
            # Include individual reaction emojis
            reactions_str = ""
            if post['individual_reactions']:
                reactions_emojis = [r['emoji'] for r in post['individual_reactions']]
                reactions_str = " " + " ".join(reactions_emojis)
            
            group_lines.append(f"      ⭐ {post['reactions']} votes{reactions_str}")

        output_lines.extend(group_lines)
        output_lines.append("")  # Add spacing between ranks
        current_rank += 1
        
    return markdown + "\n".join(output_lines).rstrip()

def split_message(message: str, max_length: int = 2000):
    """Split a message into chunks that fit Discord's character limit."""
    if len(message) <= max_length:
        return [message]
    
    parts = []
    current_part = ""
    lines = message.split('\n')
    
    for line in lines:
        # If adding this line would exceed the limit
        if len(current_part) + len(line) + 1 > max_length:
            if current_part:
                parts.append(current_part.strip())
                current_part = line + '\n'
            else:
                # Single line is too long, split it further
                while len(line) > max_length:
                    parts.append(line[:max_length])
                    line = line[max_length:]
                current_part = line + '\n' if line else ""
        else:
            current_part += line + '\n'
    
    if current_part.strip():
        parts.append(current_part.strip())
    
    return parts
