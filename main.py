import discord
from discord import app_commands, ui
from discord.ext import commands
import logging
import os
import asyncio
import aiosqlite
import json
from datetime import datetime
from dotenv import load_dotenv

# ------------------------------------------------------------------
# 1. CONFIGURATION & SETUP
# ------------------------------------------------------------------

load_dotenv()

# Advanced Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('astra_home')

# Branding & Colors
BRAND_COLOR = 0x5865F2  # Blurple
SUCCESS_COLOR = 0x57F287  # Green
WARNING_COLOR = 0xFEE75C  # Gold
ERROR_COLOR = 0xED4245    # Red
INFO_COLOR = 0x3498db     # Blue

DB_NAME = os.getenv("DB_NAME", "astra_home.db")
REVIEW_CHANNEL_ID = int(os.getenv("REVIEW_CHANNEL_ID", 0))

# Global In-Memory Knowledge Base
STATIC_KNOWLEDGE_BASE = []

def load_knowledge_base():
    """Loads the JSONL file into memory at startup."""
    global STATIC_KNOWLEDGE_BASE
    file_path = os.path.join("data", "hinduism.jsonl")
    
    try:
        # Check if file exists first
        if not os.path.exists(file_path):
            logger.warning(f"⚠️ Static Knowledge Base file not found at: {file_path}")
            return

        count = 0
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():  # Skip empty lines
                    try:
                        entry = json.loads(line)
                        if "q" in entry and "a" in entry:
                            STATIC_KNOWLEDGE_BASE.append(entry)
                            count += 1
                    except json.JSONDecodeError:
                        logger.error(f"Skipping malformed JSON line in {file_path}")
                        
        logger.info(f"✅ Loaded {count} static entries from {file_path}")
        
    except Exception as e:
        logger.error(f"❌ Failed to load Knowledge Base: {e}")

# ------------------------------------------------------------------
# 2. DATABASE MANAGER (For Dynamic/User Data)
# ------------------------------------------------------------------

class DatabaseManager:
    def __init__(self, db_name: str):
        self.db_name = db_name

    async def initialize(self):
        """Creates tables for dynamic Q&A (User submitted)."""
        directory = os.path.dirname(self.db_name)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

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
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """INSERT INTO faq (question_text, answer_text, author_id, approver_id, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (question, answer, author_id, approver_id, datetime.now())
            )
            await db.commit()

    async def find_answer(self, query: str):
        """
        Smart Search: Checks substrings and keywords in SQLite.
        """
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """
                SELECT answer_text, id, use_count, question_text
                FROM faq 
                WHERE question_text LIKE ? OR ? LIKE ('%' || question_text || '%')
                ORDER BY length(question_text) DESC, use_count DESC LIMIT 1
                """,
                (f"%{query}%", query)
            )
            row = await cursor.fetchone()
            
            if row:
                answer, qa_id, count, matched_q = row
                await db.execute("UPDATE faq SET use_count = ? WHERE id = ?", (count + 1, qa_id))
                await db.commit()
                return answer, matched_q
            return None, None

    async def get_stats(self):
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute("SELECT COUNT(*) FROM faq") as cursor:
                db_total = (await cursor.fetchone())[0]
            
            async with db.execute("SELECT question_text, use_count FROM faq ORDER BY use_count DESC LIMIT 3") as cursor:
                top_3 = await cursor.fetchall()
                
            return db_total, top_3

    async def get_leaderboard(self):
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute("""
                SELECT approver_id, COUNT(*) as score 
                FROM faq 
                WHERE approver_id != 0 
                GROUP BY approver_id 
                ORDER BY score DESC LIMIT 5
            """) as cursor:
                return await cursor.fetchall()

db_manager = DatabaseManager(DB_NAME)

# ------------------------------------------------------------------
# 3. UI COMPONENTS
# ------------------------------------------------------------------

class AdminReviewView(ui.View):
    def __init__(self):
        super().__init__(timeout=None) 

    @ui.button(label="Draft Answer", style=discord.ButtonStyle.primary, emoji="✍️", custom_id="qa_btn_answer")
    async def answer_button(self, interaction: discord.Interaction, button: ui.Button):
        embed = interaction.message.embeds[0]
        description = embed.description or ""
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
        for field in original_embed.fields:
            new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        new_embed.set_footer(text=f"Drafted by {interaction.user.display_name} • Approval Required")

        await interaction.message.edit(embed=new_embed, view=ApprovalView(self.answer_input.value))
        await interaction.response.defer() 


class ApprovalView(ui.View):
    def __init__(self, answer_text):
        super().__init__(timeout=None)
        self.answer_text = answer_text

    @ui.button(label="Publish Publicly", style=discord.ButtonStyle.success, emoji="📢", custom_id="qa_btn_approve")
    async def approve(self, interaction: discord.Interaction, button: ui.Button):
        embed = interaction.message.embeds[0]
        user_id_field = discord.utils.get(embed.fields, name="User ID")
        channel_id_field = discord.utils.get(embed.fields, name="Channel ID")
        
        if not user_id_field or not channel_id_field:
            await interaction.response.send_message("❌ Error: Metadata corruption.", ephemeral=True)
            return

        user_id = int(user_id_field.value)
        channel_id = int(channel_id_field.value)
        desc_parts = embed.description.split("\n\n**Proposed Answer:**")
        question_text = desc_parts[0].replace("**Inquiry:** ", "").strip()
        
        await db_manager.add_qa(question_text, self.answer_text, user_id, interaction.user.id)

        target_channel = interaction.guild.get_channel(channel_id)
        if target_channel:
            success_embed = discord.Embed(
                title="✨ Astra Home | New Knowledge Added",
                description=f"**Q:** {question_text}\n\n**A:** {self.answer_text}",
                color=SUCCESS_COLOR,
                timestamp=discord.utils.utcnow()
            )
            success_embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/616/616490.png")
            success_embed.set_footer(text=f"Approved by {interaction.user.display_name}")
            
            try:
                await target_channel.send(f"📢 <@{user_id}>, your question has been answered and added to the database!", embed=success_embed)
            except discord.Forbidden:
                await interaction.followup.send("⚠️ Saved to DB, but failed to message user.", ephemeral=True)
        
        await interaction.message.delete()
        await interaction.response.send_message(f"✅ Response published.", ephemeral=True)

    @ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌", custom_id="qa_btn_reject")
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        embed = interaction.message.embeds[0]
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
# 4. BOT COMMANDS
# ------------------------------------------------------------------

class AstraHomeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True 
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            activity=discord.Activity(type=discord.ActivityType.listening, name="/ask")
        )

    async def setup_hook(self):
        load_knowledge_base() # 1. Load File Data
        await db_manager.initialize() # 2. Connect DB
        await self.add_cog(QACog(self))
        logger.info("🔄 Syncing commands...")
        await self.tree.sync()
        logger.info("✅ Commands synced.")

    async def on_ready(self):
        logger.info(f'🚀 Astra Home Bot logged in as {self.user}')

class QACog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- USER COMMANDS ---

    @app_commands.command(name="ask", description="Ask a question (Public). Answers instantly if known.")
    @app_commands.describe(question="What would you like to know?")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer(ephemeral=False)

        # 1. SEARCH IN-MEMORY STATIC DATA (File Based)
        # ----------------------------------------------------
        q_lower = question.lower()
        static_answer = None
        static_topic = None

        for entry in STATIC_KNOWLEDGE_BASE:
            # Check if user query is in stored question OR stored question is in user query
            kb_q = entry.get("q", "").lower()
            if kb_q and (kb_q in q_lower or q_lower in kb_q):
                static_answer = entry.get("a")
                static_topic = entry.get("q")
                break
        
        if static_answer:
            embed = discord.Embed(
                title="🕉️ Astra Home Knowledge Base",
                description=static_answer,
                color=SUCCESS_COLOR
            )
            embed.add_field(name="Topic", value=static_topic, inline=False)
            embed.set_footer(text=f"Asked by {interaction.user.display_name} • Knowledge File")
            await interaction.followup.send(embed=embed)
            return

        # 2. SEARCH DATABASE (Dynamic Data)
        # ----------------------------------------------------
        answer, matched_q = await db_manager.find_answer(question)

        if answer:
            embed = discord.Embed(
                title="🕉️ Astra Home Knowledge Base",
                description=answer,
                color=SUCCESS_COLOR
            )
            embed.add_field(name="Topic", value=matched_q, inline=False)
            embed.set_footer(text=f"Asked by {interaction.user.display_name} • Community Verified")
            await interaction.followup.send(embed=embed)
        else:
            # 3. FALLBACK: ADMIN REVIEW
            # ----------------------------------------------------
            review_channel = self.bot.get_channel(REVIEW_CHANNEL_ID)
            if not review_channel:
                await interaction.followup.send("⚠️ System Error: Review channel unavailable.", ephemeral=True)
                return

            embed = discord.Embed(
                title="📨 New Question Received",
                description=f"**Inquiry:**\n{question}",
                color=BRAND_COLOR,
                timestamp=discord.utils.utcnow()
            )
            embed.set_author(name=f"{interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
            embed.add_field(name="User ID", value=str(interaction.user.id), inline=True)
            embed.add_field(name="Channel ID", value=str(interaction.channel_id), inline=True)
            embed.add_field(name="Source", value=interaction.channel.mention if interaction.channel else "Unknown", inline=True)
            embed.set_footer(text="Awaiting Expert Answer")

            await review_channel.send(embed=embed, view=AdminReviewView())
            
            confirm_embed = discord.Embed(
                description=f"✅ **Good Question!** I don't have the answer yet, so I've forwarded it to the **Astra Home Experts**. You will be notified here when they answer.",
                color=BRAND_COLOR
            )
            await interaction.followup.send(embed=confirm_embed)

    @app_commands.command(name="ping", description="Check bot latency.")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! Latency: **{latency}ms**", ephemeral=True)

    @app_commands.command(name="stats", description="View Knowledge Base Statistics.")
    async def stats(self, interaction: discord.Interaction):
        # Stats now combine Static File count + DB count
        db_total, top_3 = await db_manager.get_stats()
        static_total = len(STATIC_KNOWLEDGE_BASE)
        total_combined = db_total + static_total
        
        embed = discord.Embed(title="📊 Astra Home Stats", color=INFO_COLOR)
        embed.add_field(name="Total Knowledge", value=f"{total_combined} ({static_total} Static / {db_total} Community)", inline=False)
        
        top_text = ""
        for i, (q, count) in enumerate(top_3, 1):
            top_text += f"**{i}.** {q} ({count} views)\n"
        
        if top_text:
            embed.add_field(name="🔥 Trending Community Topics", value=top_text, inline=False)
            
        await interaction.response.send_message(embed=embed)

    # --- ADMIN COMMANDS ---

    @app_commands.command(name="leaderboard", description="[Admin] Top Contributors.")
    @app_commands.default_permissions(administrator=True)
    async def leaderboard(self, interaction: discord.Interaction):
        rows = await db_manager.get_leaderboard()
        if not rows:
            await interaction.response.send_message("No contributions yet!", ephemeral=True)
            return

        embed = discord.Embed(title="🏆 Admin Leaderboard", color=WARNING_COLOR)
        desc = ""
        for i, (uid, score) in enumerate(rows, 1):
            desc += f"**{i}.** <@{uid}> - **{score}** answers\n"
        
        embed.description = desc
        await interaction.response.send_message(embed=embed)

# ------------------------------------------------------------------
# 5. ENTRY POINT
# ------------------------------------------------------------------

async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.critical("⛔ DISCORD_TOKEN not found.")
        return
    bot = AstraHomeBot()
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
