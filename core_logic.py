import discord
import csv
import re
import sys
from datetime import datetime

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
    """Generates a CSV file from the extracted post data."""
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
    markdown = "🏆 **Photo Challenge Results** 🏆\n\n"
    markdown += f"📊 **Summary:**\n"
    markdown += f"• Total photos: `{total_image_posts_count}`\n"
    markdown += f"• Total votes (excluding authors): `{total_thread_reactions}`\n"
    markdown += f"• Unique voters: `{total_unique_reactors_count}`\n\n"
    
    if not data or all(d['reactions'] == 0 for d in data):
        markdown += "📷 No posts found with external votes to display."
        return markdown
    
    markdown += f"🥇 **Top {min(num_top_posts, len([d for d in data if d['reactions'] > 0]))} Image Posts:**\n\n"

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
        if current_rank > num_top_posts:
            break

        posts_in_group = grouped_posts[reactions]
        
        # Determine rank emoji
        rank_emoji = "🥇" if current_rank == 1 else "🥈" if current_rank == 2 else "🥉" if current_rank == 3 else f"{current_rank}️⃣"
        
        # Start a new rank entry
        group_lines = []
        
        # Conditionally include vote count for detailed version
        vote_info = f" (`{reactions}` votes)" if include_image_links else ""
        group_lines.append(f"{rank_emoji} **Rank {current_rank}**{vote_info}")
        
        for post in posts_in_group:
            # Post link and author
            group_lines.append(f"   📸 **[{post['author']}]({post['post_link']})**")
            
            # Conditionally include image links (Full version)
            if include_image_links:
                image_link = post['image_links'].split(', ')[0]
                if image_link:
                    group_lines.append(f"      🔗 [View Image]({image_link})")
            
            # Conditionally include individual reactions (Full version)
            if include_image_links:
                reactions_str = ""
                if post['individual_reactions']:
                    reactions_emojis = [r['emoji'] for r in post['individual_reactions']]
                    reactions_str = " " + " ".join(reactions_emojis)
                
                group_lines.append(f"      ⭐ {post['reactions']} votes{reactions_str}")

        output_lines.extend(group_lines)
        output_lines.append("")  # Add spacing between ranks
        current_rank += 1
        
    return markdown + "\n".join(output_lines).rstrip()
