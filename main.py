import discord
from discord.ext import commands
import os
import sys
import asyncio
import threading
import time

# Import Flask for the required HTTP health check listener
from flask import Flask

# Import the command setup function
from commands import setup_commands

# --- Configuration using Environment Variables (Injected by Cloud Run) ---
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
DISCORD_CLIENT_ID = os.environ.get('DISCORD_CLIENT_ID')
DISCORD_THREAD_URL = os.environ.get('DISCORD_THREAD_URL')
PORT = int(os.environ.get('PORT', 8080))

# --- Global Bot State ---
bot = None
bot_thread = None

# Create Flask app first - this MUST happen immediately
app = Flask(__name__)

print(f"LOG: Flask app created and ready to serve on port {PORT}", file=sys.stderr, flush=True)

# --- Simple Routes First ---
@app.route('/', methods=['GET'])
def health_check():
    """Health check route for Cloud Run."""
    return "Flask server is running. Discord bot status: " + ("Running" if bot_thread and bot_thread.is_alive() else "Starting"), 200

@app.route('/health', methods=['GET'])
def simple_health():
    """Simple health check that always returns 200."""
    return "OK", 200

# --- Bot Setup ---
class PhotoBot(commands.Bot):
    def __init__(self, intents):
        super().__init__(command_prefix="!", intents=intents)
        self.default_thread_url = DISCORD_THREAD_URL

    async def setup_hook(self):
        # Set up slash commands
        setup_commands(self)
        
        # Sync the application commands (slash commands) with Discord
        if DISCORD_CLIENT_ID:
            try:
                # Sync commands globally
                synced = await self.tree.sync()
                print(f"LOG: Slash commands synced successfully. {len(synced)} commands registered.", file=sys.stderr, flush=True)
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


def run_bot_in_thread():
    """Run the Discord bot in a separate thread with its own event loop."""
    try:
        print("LOG: Starting Discord bot in background thread...", file=sys.stderr, flush=True)
        
        # Create intents and bot
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        intents.members = True
        
        global bot
        bot = PhotoBot(intents=intents)
        
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

def start_bot_thread():
    """Start the Discord bot in a background thread."""
    global bot_thread
    if bot_thread is None:
        print("LOG: Creating Discord bot thread...", file=sys.stderr, flush=True)
        bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
        bot_thread.start()
        print("LOG: Discord bot thread started.", file=sys.stderr, flush=True)
        # Give the thread a moment to start
        time.sleep(0.1)

# Start bot thread but don't wait for it
print("LOG: Initializing Discord bot in background...", file=sys.stderr, flush=True)
start_bot_thread()

# This is required for Gunicorn to find the Flask app
print("LOG: Flask app is ready for Gunicorn", file=sys.stderr, flush=True)

if __name__ == "__main__":
    print("LOG: Running Flask app directly (development mode)", file=sys.stderr, flush=True)
    app.run(host="0.0.0.0", port=PORT, debug=False)
