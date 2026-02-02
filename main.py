import discord
from discord import app_commands, ui
from discord.ext import commands
import logging
import os
import asyncio
import aiosqlite
from datetime import datetime
from dotenv import load_dotenv

# ------------------------------------------------------------------
# 1. CONFIGURATION & SETUP
# ------------------------------------------------------------------

# Load .env file
load_dotenv()

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler("astra_home.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('astra_home')

# Constants / Branding
BRAND_COLOR = 0x5865F2  # Blurple
SUCCESS_COLOR = 0x57F287  # Green
WARNING_COLOR = 0xFEE75C  # Gold
ERROR_COLOR = 0xED4245    # Red
DB_NAME = os.getenv("DB_NAME", "astra_home.db")
REVIEW_CHANNEL_ID = int(os.getenv("REVIEW_CHANNEL_ID", 0))

# ------------------------------------------------------------------
# 2. DATABASE MANAGER
# ------------------------------------------------------------------

class DatabaseManager:
    """
    Handles all SQLite interactions.
    """
    def __init__(self, db_name: str):
        self.db_name = db_name

    async def initialize(self):
        """Creates tables if they don't exist."""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS faq (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_text TEXT NOT NULL,
                    answer_text TEXT NOT NULL,
                    author_id INTEGER,
                    approver_id INTEGER,
                    created_at TIMESTAMP,
                    use_count INTEGER DEFAULT 0
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_question ON faq(question_text)")
            await db.commit()
        logger.info(f"Connected to Database: {self.db_name}")

    async def add_qa(self, question: str, answer: str, author_id: int, approver_id: int):
        """Inserts a new approved Q&A pair."""
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """INSERT INTO faq (question_text, answer_text, author_id, approver_id, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (question, answer, author_id, approver_id, datetime.now())
            )
            await db.commit()

    async def find_answer(self, query: str):
        """
        Searches for an answer using SQL LIKE.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                "SELECT answer_text, id, use_count FROM faq WHERE question_text LIKE ? ORDER BY use_count DESC LIMIT 1",
                (f"%{query}%",)
            )
            row = await cursor.fetchone()
            
            if row:
                answer, qa_id, count = row
                await db.execute("UPDATE faq SET use_count = ? WHERE id = ?", (count + 1, qa_id))
                await db.commit()
                return answer
            return None

# Initialize global DB instance
db_manager = DatabaseManager(DB_NAME)

# ------------------------------------------------------------------
# 3. UI COMPONENTS (VIEWS & MODALS)
# ------------------------------------------------------------------

class AdminReviewView(ui.View):
    def __init__(self):
        super().__init__(timeout=None) 

    @ui.button(label="Draft Answer", style=discord.ButtonStyle.primary, emoji="✍️", custom_id="qa_btn_answer")
    async def answer_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = interaction.message.embeds[0]
        description = embed.description or ""
        # Remove markdown bolding to get raw text
        question_text = description.replace("**Inquiry:**\n", "").strip()
        
        await interaction.response.send_modal(AnswerModal(question_text))

    @ui.button(label="Discard", style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="qa_btn_delete")
    async def delete_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.message.delete()
        await interaction.response.send_message("🗑️ Ticket discarded.", ephemeral=True)


class AnswerModal(ui.Modal, title="Astra Home | Draft Response"):
    answer_input = ui.TextInput(
        label="Official Response",
        style=discord.TextStyle.paragraph,
        placeholder="Type the official answer here...",
        min_length=10,
        max_length=2000,
        required=True
    )

    def __init__(self, question_text):
        super().__init__()
        self.question_text = question_text

    async def on_submit(self, interaction: discord.Interaction):
        original_embed = interaction.message.embeds[0]
        
        new_embed = discord.Embed(
            title="🛡️ Response Pending Approval",
            description=f"**Inquiry:** {self.question_text}\n\n**Proposed Answer:**\n{self.answer_input.value}",
            color=WARNING_COLOR
        )
        
        # Persist metadata fields
        for field in original_embed.fields:
            new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
            
        new_embed.set_footer(text=f"Drafted by {interaction.user.display_name} • Approval Required")

        await interaction.message.edit(embed=new_embed, view=ApprovalView(self.answer_input.value))
        await interaction.response.defer() 


class ApprovalView(ui.View):
    def __init__(self, answer_text):
        super().__init__(timeout=None)
        self.answer_text = answer_text

    @ui.button(label="Publish Response", style=discord.ButtonStyle.success, emoji="✅", custom_id="qa_btn_approve")
    async def approve(self, interaction: discord.Interaction, button: ui.Button):
        embed = interaction.message.embeds[0]
        
        user_id_field = discord.utils.get(embed.fields, name="User ID")
        channel_id_field = discord.utils.get(embed.fields, name="Channel ID")
        
        if not user_id_field or not channel_id_field:
            await interaction.response.send_message("❌ Error: Metadata corruption. Cannot approve.", ephemeral=True)
            return

        user_id = int(user_id_field.value)
        channel_id = int(channel_id_field.value)
        
        # Extract question cleanly
        desc_parts = embed.description.split("\n\n**Proposed Answer:**")
        question_text = desc_parts[0].replace("**Inquiry:** ", "").strip()
        
        # 1. Save to Astra Home Database
        await db_manager.add_qa(question_text, self.answer_text, user_id, interaction.user.id)

        # 2. Notify User
        target_channel = interaction.guild.get_channel(channel_id)
        if target_channel:
            success_embed = discord.Embed(
                title="✨ Astra Home Support | Update",
                description=f"**Q:** {question_text}\n\n**A:** {self.answer_text}",
                color=SUCCESS_COLOR,
                timestamp=discord.utils.utcnow()
            )
            success_embed.set_footer(text=f"Verified by {interaction.user.display_name}")
            
            try:
                await target_channel.send(f"<@{user_id}>", embed=success_embed)
            except discord.Forbidden:
                await interaction.followup.send("⚠️ Saved to DB, but failed to message user (Permissions).", ephemeral=True)
        
        await interaction.message.delete()
        await interaction.response.send_message(f"✅ Response published and database updated.", ephemeral=True)

    @ui.button(label="Reject & Edit", style=discord.ButtonStyle.danger, emoji="✏️", custom_id="qa_btn_reject")
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        embed = interaction.message.embeds[0]
        
        # Revert to original state
        desc_parts = embed.description.split("\n\n**Proposed Answer:**")
        question_only = desc_parts[0].replace("**Inquiry:** ", "").strip()
        
        revert_embed = discord.Embed(
            title="📨 Support Ticket (Returned)",
            description=f"**Inquiry:**\n{question_only}",
            color=BRAND_COLOR
        )
        for field in embed.fields:
            revert_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        
        revert_embed.set_footer(text="Astra Home Admin Panel • Returned for Edit")
            
        await interaction.message.edit(embed=revert_embed, view=AdminReviewView())
        await interaction.response.send_message("↩️ Ticket returned to queue.", ephemeral=True)

# ------------------------------------------------------------------
# 4. BOT COMMANDS & LOGIC
# ------------------------------------------------------------------

class AstraHomeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True 
        
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            activity=discord.Activity(type=discord.ActivityType.listening, name="/ask | Astra Home Support")
        )

    async def setup_hook(self):
        await db_manager.initialize()
        # Add the Cog holding our commands
        await self.add_cog(QACog(self))
        logger.info("🔄 Syncing commands globally...")
        await self.tree.sync()
        logger.info("✅ Commands synced successfully.")

    async def on_ready(self):
        logger.info(f'🚀 Astra Home Bot logged in as {self.user} (ID: {self.user.id})')
        logger.info('------ Systems Online ------')

class QACog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ask", description="Submit an inquiry to Astra Home Support.")
    @app_commands.describe(question="How can we assist you today?")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer(ephemeral=True)

        # 1. Search Knowledge Base
        answer = await db_manager.find_answer(question)

        if answer:
            # Answer Found
            embed = discord.Embed(
                title="✨ Astra Home | Solution Found",
                description=answer,
                color=SUCCESS_COLOR
            )
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            embed.add_field(name="Original Query", value=f"_{question}_", inline=False)
            embed.set_footer(text="Astra Home Automated Support System")
            
            await interaction.followup.send(content=f"{interaction.user.mention}", embed=embed)
        else:
            # No Answer - Forward to Expert Review
            review_channel = self.bot.get_channel(REVIEW_CHANNEL_ID)
            
            if not review_channel:
                await interaction.followup.send("⚠️ System Error: Review channel unavailable. Please contact an administrator.", ephemeral=True)
                return

            embed = discord.Embed(
                title="📨 New Support Ticket",
                description=f"**Inquiry:**\n{question}",
                color=BRAND_COLOR,
                timestamp=discord.utils.utcnow()
            )
            embed.set_author(name=f"{interaction.user.display_name} ({interaction.user.name})", icon_url=interaction.user.display_avatar.url)
            
            embed.add_field(name="User ID", value=str(interaction.user.id), inline=True)
            embed.add_field(name="Channel ID", value=str(interaction.channel_id), inline=True)
            embed.add_field(name="Source", value=interaction.channel.mention if interaction.channel else "Unknown", inline=True)
            embed.set_footer(text="Astra Home Admin Panel • Pending Review")

            await review_channel.send(embed=embed, view=AdminReviewView())
            
            confirm_embed = discord.Embed(
                description=f"✅ **Ticket Received.** Your question has been forwarded to the **Astra Home** expert team.",
                color=BRAND_COLOR
            )
            await interaction.followup.send(embed=confirm_embed, ephemeral=True)

# ------------------------------------------------------------------
# 5. ENTRY POINT
# ------------------------------------------------------------------

async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.critical("⛔ DISCORD_TOKEN not found in .env file.")
        return

    bot = AstraHomeBot()
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot shutting down...")