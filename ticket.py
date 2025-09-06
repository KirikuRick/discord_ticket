import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import View, Button
from discord.ui import Modal, TextInput
import os
import json
from datetime import datetime, timedelta
import io

from utils.guild_config import (
    set_ticket_category, get_ticket_category,
    set_ticket_log_channel, get_ticket_log_channel,
    add_ticket_role, remove_ticket_role, get_ticket_roles
)

TICKET_JSON_FILE = "ticket_log.json"
BUTTONS_FILE = "ticket_buttons.json"
AUTO_EXPIRE_SECONDS = 259200  

active_tickets = {}
BANNED_USERS_FILE = "ticket_bans.json"
TICKET_CLOSED_FILE = "ticket_closed.json"
TICKET_ACTIVE_FILE = "ticket_active.json"

def load_banned_users():
    if os.path.exists(BANNED_USERS_FILE):
        with open(BANNED_USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_banned_users(data):
    with open(BANNED_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def now_wib():
    return datetime.utcnow() + timedelta(hours=7)

def save_ticket_log(entry):
    logs = []
    if os.path.exists(TICKET_JSON_FILE):
        with open(TICKET_JSON_FILE, "r", encoding="utf-8") as f:
            try:
                logs = json.load(f)
            except json.JSONDecodeError:
                logs = []
    logs.append(entry)
    with open(TICKET_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)

def load_ticket_buttons():
    if os.path.exists(BUTTONS_FILE):
        with open(BUTTONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_ticket_buttons(data):
    with open(BUTTONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_closed_tickets():
    if os.path.exists(TICKET_CLOSED_FILE):
        with open(TICKET_CLOSED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_closed_tickets(data):
    with open(TICKET_CLOSED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_active_tickets():
    if os.path.exists(TICKET_ACTIVE_FILE):
        with open(TICKET_ACTIVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_active_tickets(data):
    with open(TICKET_ACTIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

class TicketButton(Button):
    def __init__(self, label: str, style: discord.ButtonStyle, custom_id: str):
        super().__init__(label=label, style=style, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        banned_data = load_banned_users()
        guild_id = str(interaction.guild.id)
        if guild_id in banned_data and interaction.user.id in banned_data[guild_id]:
            await interaction.response.send_message("❌ Kamu telah diblokir dari sistem tiket.", ephemeral=True)
            return
        for ch_id, data in active_tickets.items():
            if data["user_id"] == interaction.user.id and data["ticket_type"] == self.custom_id:
                existing_channel = interaction.guild.get_channel(ch_id)
                if existing_channel:
                    await interaction.response.send_message(
                        f"❌ Kamu sudah memiliki tiket aktif untuk kategori ini: {existing_channel.mention}",
                        ephemeral=True
                    )
                    return
        guild_id = str(interaction.guild.id)
        data = load_ticket_buttons()
        ticket_info = data.get(guild_id)

        if not ticket_info:
            await interaction.response.send_message("❌ Panel ticket tidak ditemukan atau sudah direset. Silakan hubungi admin.", ephemeral=True)
            return

        channel_id = ticket_info.get("channel_id")
        message_id = ticket_info.get("message_id")
        channel = interaction.guild.get_channel(channel_id)

        if not channel:
            del data[guild_id]
            save_ticket_buttons(data)
            await interaction.response.send_message("❌ Channel panel sudah dihapus. Data dibersihkan.", ephemeral=True)
            return

        try:
            await channel.fetch_message(message_id)
        except discord.NotFound:
            del data[guild_id]
            save_ticket_buttons(data)
            await interaction.response.send_message("❌ Panel ticket sudah dihapus. Silakan minta admin kirim ulang.", ephemeral=True)
            return
        guild = interaction.guild
        user = interaction.user

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True)
        }

        reason_map = {
            "lahelu": "Customer Service Lahelu",
            "partner": "Partnership Server",
            "custom": "Custom Role Request"
        }

        category_id = get_ticket_category(guild.id)
        category = guild.get_channel(category_id) if category_id else None
        if not isinstance(category, discord.CategoryChannel):
            await interaction.response.send_message("❌ Kategori ticket belum di-set.", ephemeral=True)
            return

        role_ids = get_ticket_roles(guild.id, self.custom_id)
        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, read_message_history=True)

        channel_name = f"ticket-{user.name}".replace(" ", "-").lower()
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Ticket by {user.display_name} - {reason_map.get(self.custom_id, 'General')}"
        )

        active_tickets[ticket_channel.id] = {
            "user_id": user.id,
            "ticket_type": self.custom_id,
            "opened_at": now_wib().isoformat(),
            "channel_id": ticket_channel.id
        }

        active_ticket_ids = load_active_tickets()
        if ticket_channel.id not in active_ticket_ids:
            active_ticket_ids.append(ticket_channel.id)
            save_active_tickets(active_ticket_ids)

        view = View(timeout=None)
        view.add_item(CloseTicketButton(ticket_channel))
        interaction.client.add_view(view) 

        role_mentions = " ".join(guild.get_role(rid).mention for rid in role_ids if guild.get_role(rid))

        embed = discord.Embed(
            title="🎫 Ticket Dibuka",
            color=discord.Color.green(),
            description=f"Silakan jelaskan kebutuhan kamu terkait **{reason_map.get(self.custom_id, 'General')}**.\n\n{role_mentions}"
        )
        embed.add_field(name="👤 Ticket Owner", value=user.mention, inline=True)
        embed.add_field(name="📅 Dibuka", value=f"<t:{int(now_wib().timestamp())}:f>", inline=True)
        embed.add_field(name="📝 Tipe Ticket", value=reason_map.get(self.custom_id, self.custom_id), inline=False)
        embed.set_footer(text="Gunakan tombol di bawah untuk menutup tiket.")

        await ticket_channel.send(content=f"{user.mention} {role_mentions}", embed=embed, view=view)
        await interaction.response.send_message(f"✅ Tiket kamu telah dibuat: {ticket_channel.mention}", ephemeral=True)

class CloseTicketButton(Button):
    def __init__(self, channel: discord.TextChannel):
        super().__init__(
            label="❌ Tutup Ticket",
            style=discord.ButtonStyle.danger,
            custom_id=f"close_ticket_{channel.id}"
        )
        self.channel = channel

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        role_ids = get_ticket_roles(guild.id, active_tickets[self.channel.id]["ticket_type"])
        is_handler = any(role in user.roles for role in [guild.get_role(rid) for rid in role_ids])
        if not (user.guild_permissions.administrator or is_handler):
            await interaction.response.send_message("❌ Hanya admin atau handler yang dapat menutup ticket.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        log_channel_id = get_ticket_log_channel(interaction.guild.id)
        log_channel = interaction.guild.get_channel(log_channel_id) if log_channel_id else None
        ticket_data = active_tickets.pop(self.channel.id, {})

        ticket_data.update({
            "closed_at": datetime.utcnow().isoformat(),
            "closed_by": interaction.user.id
        })
        save_ticket_log(ticket_data)

        closed_tickets = load_closed_tickets()
        closed_tickets[str(self.channel.id)] = {
            "user_id": ticket_data.get("user_id"),
            "closed_by": interaction.user.id
        }
        save_closed_tickets(closed_tickets)

        await self.channel.set_permissions(interaction.guild.default_role, read_messages=False)
        await self.channel.set_permissions(interaction.user, read_messages=False)

        embed_ticket = discord.Embed(
            title="❌ Ticket Ditutup",
            color=discord.Color.red(),
            description="Ticket telah ditutup dan channel dikunci sebagai arsip."
        )
        embed_ticket.add_field(name="Ditutup oleh", value=interaction.user.mention, inline=True)
        embed_ticket.add_field(name="Waktu", value=f"<t:{int(datetime.utcnow().timestamp())}:f>", inline=True)
        await self.channel.send(embed=embed_ticket, view=DeleteReopenView(self.channel, ticket_data.get("user_id")))

class DeleteReopenView(View):
    def __init__(self, channel: discord.TextChannel, user_id):
        super().__init__(timeout=None)
        self.add_item(DeleteTicketButton(channel))
        self.add_item(ReopenTicketButton(channel, user_id))

class DeleteTicketButton(Button):
    def __init__(self, channel):
        super().__init__(
            label="🗑️ Hapus Ticket",
            style=discord.ButtonStyle.danger,
            custom_id=f"delete_ticket_{channel.id}"
        )
        self.channel = channel

    async def callback(self, interaction: discord.Interaction):
        closed_tickets = load_closed_tickets()
        closed = closed_tickets.get(str(self.channel.id))
        guild = interaction.guild
        user = interaction.user
        role_ids = get_ticket_roles(guild.id, closed.get("ticket_type", "")) if closed else []
        is_handler = any(role in user.roles for role in [guild.get_role(rid) for rid in role_ids])
        is_owner = closed and user.id == closed.get("user_id")
        if not (user.guild_permissions.administrator or is_owner or is_handler):
            await interaction.response.send_message("❌ Hanya admin, handler, atau pemilik ticket yang dapat menghapus ticket.", ephemeral=True)
            return
        await interaction.response.send_message("🗑️ Menghapus ticket...", ephemeral=True)
        log_channel_id = get_ticket_log_channel(interaction.guild.id)
        log_channel = interaction.guild.get_channel(log_channel_id) if log_channel_id else None

        messages = []
        async for msg in self.channel.history(limit=100, oldest_first=True):
            time_str = msg.created_at.strftime("[%Y-%m-%d %H:%M]")
            author = f"{msg.author} ({msg.author.mention})"
            content = msg.content
            messages.append(f"{time_str} {author}: {content}")
        transcript_str = "\n".join(messages) if messages else "No messages."
        transcript_file = discord.File(
            io.BytesIO(transcript_str.encode("utf-8")),
            filename=f"transcript-{self.channel.name}.txt"
        )

        if log_channel:
            embed_log = discord.Embed(
                title=f"📁 Ticket `{self.channel.name}` dihapus",
                color=discord.Color.blue()
            )
            embed_log.add_field(name="Dihapus oleh", value=interaction.user.mention, inline=True)
            embed_log.add_field(name="Waktu", value=f"<t:{int(datetime.utcnow().timestamp())}:f>", inline=True)
            await log_channel.send(embed=embed_log, file=transcript_file)

        closed_tickets.pop(str(self.channel.id), None)
        save_closed_tickets(closed_tickets)
        await self.channel.delete(reason="Ticket deleted")

class ReopenTicketButton(Button):
    def __init__(self, channel: discord.TextChannel, user_id):
        super().__init__(label="🔁 Reopen Ticket", style=discord.ButtonStyle.secondary)
        self.channel = channel
        self.user_id = user_id

    async def callback(self, interaction: discord.Interaction):
        closed_tickets = load_closed_tickets()
        closed = closed_tickets.get(str(self.channel.id))
        is_owner = closed and interaction.user.id == closed.get("user_id")
        if not (interaction.user.guild_permissions.administrator or is_owner):
            await interaction.response.send_message("❌ Hanya admin atau pemilik ticket yang dapat membuka kembali ticket.", ephemeral=True)
            return
        guild = interaction.guild
        user = guild.get_member(self.user_id)
        if user:
            await self.channel.set_permissions(user, read_messages=True, send_messages=True)
            await self.channel.send(f"{user.mention} Ticket telah dibuka kembali oleh {interaction.user.mention}")
        await interaction.response.send_message("🔓 Ticket dibuka kembali!", ephemeral=True)
        closed_tickets.pop(str(self.channel.id), None)
        save_closed_tickets(closed_tickets)

class TicketPanelView(View):
    def __init__(self, buttons=None):
        super().__init__(timeout=None)
        if buttons:
            for btn in buttons:
                self.add_item(TicketButton(btn["label"], discord.ButtonStyle(btn["style"]), btn["custom_id"]))

class TicketEmbedEditModal(Modal, title="Edit Ticket Embed"):
    def __init__(self, ticket_view_update_callback):
        super().__init__()
        self.ticket_view_update_callback = ticket_view_update_callback

        self.title_input = TextInput(
            label="Judul",
            placeholder="Masukkan judul embed",
            max_length=256,
            required=True
        )
        self.desc_input = TextInput(
            label="Deskripsi",
            placeholder="Gunakan \\n untuk newline",
            style=discord.TextStyle.paragraph,
            required=True
        )
        self.footer_input = TextInput(
            label="Footer",
            placeholder="Footer embed",
            required=True
        )

        self.add_item(self.title_input)
        self.add_item(self.desc_input)
        self.add_item(self.footer_input)

    async def on_submit(self, interaction: discord.Interaction):
        title = self.title_input.value
        description = self.desc_input.value.replace("\\n", "\n")
        footer = self.footer_input.value
        await self.ticket_view_update_callback(interaction, title, description, footer)

class Ticket(commands.Cog):

    @app_commands.command(name="checkticketban", description="Cek apakah user diblokir dari sistem ticket")
    @app_commands.checks.has_permissions(administrator=True)
    async def check_ticket_ban(self, interaction: discord.Interaction, user: discord.User):
        guild_id = str(interaction.guild.id)
        data = load_banned_users()
        if guild_id in data and user.id in data[guild_id]:
            await interaction.response.send_message(f"❌ {user.mention} sedang diblokir dari sistem tiket.", ephemeral=True)
        else:
            await interaction.response.send_message(f"✅ {user.mention} tidak diblokir dari sistem tiket.", ephemeral=True)

    @app_commands.command(name="banticketuser", description="Ban user dari penggunaan sistem ticket")
    @app_commands.checks.has_permissions(administrator=True)
    async def ban_ticket_user(self, interaction: discord.Interaction, user: discord.User):
        guild_id = str(interaction.guild.id)
        data = load_banned_users()
        if guild_id not in data:
            data[guild_id] = []
        if user.id not in data[guild_id]:
            data[guild_id].append(user.id)
            save_banned_users(data)
            await interaction.response.send_message(f"✅ {user.mention} telah diblokir dari sistem tiket.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ User sudah diblokir sebelumnya.", ephemeral=True)

    @app_commands.command(name="unbanticketuser", description="Unban user dari sistem ticket")
    @app_commands.checks.has_permissions(administrator=True)
    async def unban_ticket_user(self, interaction: discord.Interaction, user: discord.User):
        guild_id = str(interaction.guild.id)
        data = load_banned_users()
        if guild_id in data and user.id in data[guild_id]:
            data[guild_id].remove(user.id)
            save_banned_users(data)
            await interaction.response.send_message(f"✅ {user.mention} telah diizinkan kembali menggunakan sistem tiket.", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ User ini tidak diblokir.", ephemeral=True)

    @app_commands.command(name="reorderticketbutton", description="Ubah urutan tombol dalam panel ticket")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(custom_id="ID tombol yang ingin dipindah", position="Posisi baru (mulai dari 0)")
    async def reorder_ticket_button(self, interaction: discord.Interaction, custom_id: str, position: int):
        guild_id = str(interaction.guild.id)
        data = load_ticket_buttons()
        if guild_id not in data:
            await interaction.response.send_message("❌ Belum ada panel ticket untuk server ini.", ephemeral=True)
            return

        buttons = data[guild_id].get("buttons", [])
        message_id = data[guild_id].get("message_id")
        channel_id = data[guild_id].get("channel_id")

        target = next((btn for btn in buttons if btn["custom_id"] == custom_id), None)
        if not target:
            await interaction.response.send_message("❌ Tombol dengan ID tersebut tidak ditemukan.", ephemeral=True)
            return

        buttons = [btn for btn in buttons if btn["custom_id"] != custom_id]
        position = max(0, min(position, len(buttons))) 
        buttons.insert(position, target)

        data[guild_id]["buttons"] = buttons
        save_ticket_buttons(data)

        channel = interaction.guild.get_channel(channel_id)
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            del data[guild_id]
            save_ticket_buttons(data)
            await interaction.response.send_message("❌ Panel tidak ditemukan. Data dihapus dari penyimpanan.", ephemeral=True)
            return

        await message.edit(view=TicketPanelView(buttons))
        await interaction.response.send_message("✅ Urutan tombol berhasil diperbarui.", ephemeral=True)

    @app_commands.command(name="resetticketpanel", description="Hapus semua tombol dan data panel ticket untuk server ini")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_ticket_panel(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        data = load_ticket_buttons()
        if guild_id not in data:
            await interaction.response.send_message("⚠️ Tidak ada data panel ticket yang tersimpan untuk server ini.", ephemeral=True)
            return

        del data[guild_id]
        save_ticket_buttons(data)
        await interaction.response.send_message("✅ Data panel ticket berhasil dihapus dari penyimpanan.", ephemeral=True)

    @app_commands.command(name="listticketbuttons", description="Lihat semua tombol aktif di panel ticket")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_ticket_buttons(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        data = load_ticket_buttons()
        if guild_id not in data or not data[guild_id].get("buttons"):
            await interaction.response.send_message("⚠️ Tidak ada tombol yang tersimpan untuk server ini.", ephemeral=True)
            return

        buttons = data[guild_id].get("buttons", [])
        if not buttons:
            await interaction.response.send_message("⚠️ Tidak ada tombol aktif ditemukan.", ephemeral=True)
            return

        content = "**Daftar Tombol Tiket:**\n"
        for i, btn in enumerate(buttons, 1):
            role_ids = get_ticket_roles(interaction.guild.id, btn["custom_id"])
            roles = [interaction.guild.get_role(rid) for rid in role_ids if interaction.guild.get_role(rid)]
            role_mentions = ", ".join(role.mention for role in roles) if roles else "*Tidak ada handler*"
            content += (
                f"{i}. Label: `{btn['label']}`, ID: `{btn['custom_id']}`, "
                f"Style: `{btn['style']}`, Handled by: {role_mentions}\n"
            )

        await interaction.response.send_message(content, ephemeral=True)

    @app_commands.command(name="editticketembed", description="Edit embed panel ticket (via modal)")
    @app_commands.checks.has_permissions(administrator=True)
    async def edit_ticket_embed(self, interaction: discord.Interaction):
        async def update_ticket_embed(interaction, title, description, footer):
            guild_id = str(interaction.guild.id)
            data = load_ticket_buttons()
            if guild_id not in data:
                await interaction.response.send_message("❌ Tidak ada data panel ticket untuk server ini.", ephemeral=True)
                return

            message_id = data[guild_id].get("message_id")
            channel_id = data[guild_id].get("channel_id")
            buttons = data[guild_id].get("buttons", [])

            channel = interaction.guild.get_channel(channel_id)
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                del data[guild_id]
                save_ticket_buttons(data)
                await interaction.response.send_message("❌ Panel tidak ditemukan. Data dihapus dari penyimpanan.", ephemeral=True)
                return

            embed = discord.Embed(title=title, description=description, color=discord.Color.blue())
            embed.set_footer(text=footer)

            await message.edit(embed=embed, view=TicketPanelView(buttons))
            await interaction.response.send_message("✅ Embed berhasil diperbarui.", ephemeral=True)

        await interaction.response.send_modal(TicketEmbedEditModal(update_ticket_embed))

    def __init__(self, bot):
        self.bot = bot
        self.ticket_expire_loop.start()


    async def restore_closed_ticket_views(self):
        await self.bot.wait_until_ready()
        closed_tickets = load_closed_tickets()
        for ch_id, data in closed_tickets.items():
            channel = self.bot.get_channel(int(ch_id))
            if channel:
                try:
                    last_msg = [msg async for msg in channel.history(limit=1)][0]
                    has_view = last_msg.components and any(
                        c['type'] == 1 for c in last_msg.components
                    )
                except Exception:
                    has_view = False
                if not has_view:
                    embed_ticket = discord.Embed(
                        title="❌ Ticket Ditutup",
                        color=discord.Color.red(),
                        description="Ticket telah ditutup dan channel dikunci sebagai arsip."
                    )
                    user_id = data.get("user_id")
                    embed_ticket.add_field(name="Ditutup oleh", value=f"<@{data.get('closed_by')}>", inline=True)
                    embed_ticket.add_field(name="Waktu", value=f"<t:{int(datetime.utcnow().timestamp())}:f>", inline=True)
                    await channel.send(embed=embed_ticket, view=DeleteReopenView(channel, user_id))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setticketcategory(self, ctx, category: discord.CategoryChannel):
        set_ticket_category(ctx.guild.id, category.id)
        await ctx.send(f"Kategori ticket di-set ke {category.mention}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setticketlog(self, ctx, channel: discord.TextChannel):
        set_ticket_log_channel(ctx.guild.id, channel.id)
        await ctx.send(f"Log channel ticket di-set ke {channel.mention}")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def addticketrole(self, ctx, tipe: str, role: discord.Role):
        add_ticket_role(ctx.guild.id, tipe, role.id)
        await ctx.send(f"Role {role.mention} ditambahkan sebagai handler ticket tipe `{tipe}`.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def removeticketrole(self, ctx, tipe: str, role: discord.Role):
        remove_ticket_role(ctx.guild.id, tipe, role.id)
        await ctx.send(f"Role {role.mention} dihapus dari handler ticket tipe `{tipe}`.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def listticketrole(self, ctx, tipe: str):
        role_ids = get_ticket_roles(ctx.guild.id, tipe)
        if not role_ids:
            await ctx.send(f"Tidak ada role handler untuk ticket tipe `{tipe}`.")
            return
        roles = [ctx.guild.get_role(rid) for rid in role_ids if ctx.guild.get_role(rid)]
        if not roles:
            await ctx.send(f"Tidak ada role handler valid untuk ticket tipe `{tipe}`.")
            return
        role_mentions = " ".join(role.mention for role in roles)
        await ctx.send(f"Role handler untuk ticket tipe `{tipe}`:{role_mentions}")

    def cog_unload(self):
        self.ticket_expire_loop.cancel()

    @tasks.loop(minutes=30)
    async def ticket_expire_loop(self):
        now = datetime.utcnow()
        to_close = []
        for ch_id, data in active_tickets.items():
            opened = datetime.fromisoformat(data["opened_at"])
            if (now - opened).total_seconds() > AUTO_EXPIRE_SECONDS:
                to_close.append(ch_id)
        for ch_id in to_close:
            channel = self.bot.get_channel(ch_id)
            if channel:
                await channel.send("⏰ Ticket ini telah otomatis ditutup karena tidak ada aktivitas selama 3 hari.")
                await channel.edit(overwrites={role: discord.PermissionOverwrite(read_messages=False)
                                               for role in channel.overwrites})
                await channel.send(view=DeleteReopenView(channel, None))
                ticket_data = active_tickets.pop(ch_id)
                ticket_data.update({
                    "closed_at": datetime.utcnow().isoformat(),
                    "closed_by": "auto-expire"
                })
                save_ticket_log(ticket_data)

    @app_commands.command(name="sendticketpanel", description="Kirim panel ticket ke channel ini")
    @app_commands.checks.has_permissions(administrator=True)
    async def send_ticket_panel(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        data = load_ticket_buttons()
        buttons = data.get(guild_id, {}).get("buttons", [])

        view = TicketPanelView(buttons)
        embed = discord.Embed(
            title="🎫 Support Ticket",
            description="Klik tombol untuk membuat tiket sesuai kebutuhan kamu.",
            color=discord.Color.blue()
        )
        embed.set_footer(text="KirikuDev Ticket system")
        message = await interaction.channel.send(embed=embed, view=view)

        data[guild_id] = {
            "message_id": message.id,
            "channel_id": message.channel.id,
            "buttons": buttons
        }
        save_ticket_buttons(data)
        await interaction.response.send_message("✅ Panel ticket berhasil dikirim.", ephemeral=True)

    @app_commands.command(name="editticketbutton", description="Edit tombol ticket")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        action="add / remove / edit",
        label="Teks tombol",
        style="primary/success/danger/secondary",
        custom_id="ID unik tombol"
    )
    async def editticketbutton(
        self,
        interaction: discord.Interaction,
        action: str,
        label: str,
        style: str,
        custom_id: str
    ):
        guild_id = str(interaction.guild.id)
        data = load_ticket_buttons()
        if guild_id not in data:
            await interaction.response.send_message("❌ Belum ada panel yang dikirim.", ephemeral=True)
            return

        buttons = data[guild_id].get("buttons", [])
        message_id = data[guild_id]["message_id"]
        channel_id = data[guild_id]["channel_id"]

        channel = interaction.guild.get_channel(channel_id)
        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            del data[guild_id]
            save_ticket_buttons(data)
            await interaction.response.send_message("❌ Panel ticket sudah dihapus dari Discord. Data telah dibersihkan.", ephemeral=True)
            return

        buttons = [btn for btn in buttons if btn["custom_id"] != custom_id]

        if action.lower() in ["add", "edit"]:
            style_map = {
                "primary": 1,
                "secondary": 2,
                "success": 3,
                "danger": 4
            }
            buttons.append({
                "label": label,
                "style": style_map.get(style.lower(), 2),
                "custom_id": custom_id
            })

        data[guild_id]["buttons"] = buttons
        save_ticket_buttons(data)

        new_view = TicketPanelView(buttons)
        await message.edit(view=new_view)
        await interaction.response.send_message("✅ Tombol berhasil diperbarui.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Ticket(bot))
