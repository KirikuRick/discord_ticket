import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:

        from cogs.ticket import load_ticket_buttons, TicketPanelView, load_closed_tickets, DeleteReopenView, load_active_tickets, CloseTicketButton
        data = load_ticket_buttons()
        for guild_id, info in data.items():
            buttons = info.get("buttons", [])
            if buttons:
                bot.add_view(TicketPanelView(buttons))

        closed_tickets = load_closed_tickets()
        for ch_id, data in closed_tickets.items():
            channel = bot.get_channel(int(ch_id))
            if channel:
                user_id = data.get("user_id")
                bot.add_view(DeleteReopenView(channel, user_id))

        active_ticket_ids = load_active_tickets()
        for ch_id in active_ticket_ids:
            channel = bot.get_channel(ch_id)
            if channel:
                view = discord.ui.View(timeout=None)
                view.add_item(CloseTicketButton(channel))
                bot.add_view(view)

        synced = await bot.tree.sync()
        print(f"🔧 Synced {len(synced)} command(s)")
    except Exception as e:
        import traceback
        print(f"❌ Sync failed: {e}")
        traceback.print_exc()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"❌ Penggunaan: `{ctx.prefix}{ctx.command} {ctx.command.signature}`",
            delete_after=10
        )
    elif isinstance(error, commands.BadArgument):
        await ctx.send(
            "❌ User tidak ditemukan atau format salah.",
            delete_after=10
        )
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(
            "❌ Kamu tidak punya perm untuk menjalankan command ini.",
            delete_after=10
        )
    else:
        await ctx.send(
            f"❌ Error: {error}",
            delete_after=10
        )

async def main():
    await bot.load_extension("cogs.ticket")
    await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())