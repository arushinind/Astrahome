import discord
from discord import app_commands, ui
from discord.ext import commands
import logging
import os
import asyncio
import aiosqlite
import json
import difflib
import random
from datetime import datetime, timedelta
from dotenv import load_dotenv

# ------------------------------------------------------------------
# 1. CONFIGURATION & SETUP
# ------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('astra_home')

BRAND_COLOR = 0x5865F2  
SUCCESS_COLOR = 0x57F287  
WARNING_COLOR = 0xFEE75C  
ERROR_COLOR = 0xED4245    
INFO_COLOR = 0x3498db     
MYSTIC_COLOR = 0x9b59b6   # Purple for Magic/Oracle

DB_NAME = os.getenv("DB_NAME", "astra_home.db")
REVIEW_CHANNEL_ID = int(os.getenv("REVIEW_CHANNEL_ID", 0))

STATIC_KNOWLEDGE_BASE = []

def load_knowledge_base():
    global STATIC_KNOWLEDGE_BASE
    file_path = os.path.join("data", "hinduism.jsonl")
    try:
        if not os.path.exists(file_path):
            logger.warning(f"⚠️ Static Knowledge Base file not found at: {file_path}")
            return
        count = 0
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        if "q" in entry and "a" in entry:
                            STATIC_KNOWLEDGE_BASE.append(entry)
                            count += 1
                    except json.JSONDecodeError:
                        continue
        logger.info(f"✅ Loaded {count} static entries.")
    except Exception as e:
        logger.error(f"❌ Failed to load Knowledge Base: {e}")

# ------------------------------------------------------------------
# 2. DATABASE MANAGER
# ------------------------------------------------------------------

class DatabaseManager:
    def __init__(self, db_name: str):
        self.db_name = db_name

    async def initialize(self):
        directory = os.path.dirname(self.db_name)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        async with aiosqlite.connect(self.db_name) as db:
            # FAQ Table
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
            # Users/Karma Table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    karma INTEGER DEFAULT 0,
                    meditations INTEGER DEFAULT 0,
                    last_meditation TIMESTAMP
                )
            """)
            await db.commit()
        logger.info(f"Connected to Database: {self.db_name}")

    # --- FAQ Logic ---
    async def add_qa(self, question: str, answer: str, author_id: int, approver_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
                """INSERT INTO faq (question_text, answer_text, author_id, approver_id, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (question, answer, author_id, approver_id, datetime.now())
            )
            await db.commit()

    async def search_candidates(self, query: str):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """SELECT question_text, answer_text, id 
                FROM faq 
                WHERE question_text LIKE ? OR ? LIKE ('%' || question_text || '%')
                LIMIT 10""",
                (f"%{query}%", query)
            )
            rows = await cursor.fetchall()
            return [{'q': r[0], 'a': r[1], 'source': 'db', 'id': r[2]} for r in rows]

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

    # --- Karma/User Logic ---
    async def update_karma(self, user_id: int, points: int):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute("""
                INSERT INTO users (user_id, karma) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET karma = karma + ?
            """, (user_id, points, points))
            await db.commit()

    async def record_meditation(self, user_id: int):
        now = datetime.now()
        async with aiosqlite.connect(self.db_name) as db:
            # Check cooldown (1 hour)
            async with db.execute("SELECT last_meditation FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    last = datetime.fromisoformat(row[0])
                    if now - last < timedelta(hours=1):
                        return False, (timedelta(hours=1) - (now - last))

            # Update stats
            await db.execute("""
                INSERT INTO users (user_id, karma, meditations, last_meditation) 
                VALUES (?, 10, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET 
                    karma = karma + 10, 
                    meditations = meditations + 1,
                    last_meditation = ?
            """, (user_id, now, now))
            await db.commit()
            return True, None

    async def get_user_profile(self, user_id: int):
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute("SELECT karma, meditations FROM users WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchone()

db_manager = DatabaseManager(DB_NAME)

# ------------------------------------------------------------------
# 3. QUIZ & GAME COMPONENTS
# ------------------------------------------------------------------

class QuizButton(ui.Button):
    def __init__(self, label, is_correct, quiz_view):
        super().__init__(style=discord.ButtonStyle.secondary, label=label[:80]) # Limit length
        self.is_correct = is_correct
        self.quiz_view = quiz_view

    async def callback(self, interaction: discord.Interaction):
        # Disable all buttons
        for child in self.view.children:
            child.disabled = True
            if isinstance(child, QuizButton):
                if child.is_correct:
                    child.style = discord.ButtonStyle.success
                elif child == self:
                    child.style = discord.ButtonStyle.danger

        if self.is_correct:
            await db_manager.update_karma(interaction.user.id, 5)
            await interaction.response.edit_message(content="🎉 **Correct!** +5 Karma", view=self.view)
        else:
            await interaction.response.edit_message(content=f"❌ **Wrong!** The correct answer was highlighted.", view=self.view)
        
        self.view.stop()

class QuizView(ui.View):
    def __init__(self, correct_answer, wrong_answers):
        super().__init__(timeout=30)
        
        # Combine and shuffle
        options = [(correct_answer, True)]
        for ans in wrong_answers:
            options.append((ans, False))
        random.shuffle(options)

        for label, is_correct in options:
            self.add_item(QuizButton(label, is_correct, self))

# ------------------------------------------------------------------
# 4. ADMIN & Q&A COMPONENTS
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
    answer_input = ui.TextInput(label="Official Response", style=discord.TextStyle.paragraph, max_length=2000)

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
        user_id = int(discord.utils.get(embed.fields, name="User ID").value)
        channel_id = int(discord.utils.get(embed.fields, name="Channel ID").value)
        question_text = embed.description.split("\n\n**Proposed Answer:**")[0].replace("**Inquiry:** ", "").strip()
        
        await db_manager.add_qa(question_text, self.answer_text, user_id, interaction.user.id)
        # Give admin karma
        await db_manager.update_karma(interaction.user.id, 15)

        target_channel = interaction.guild.get_channel(channel_id)
        if target_channel:
            success_embed = discord.Embed(
                title="✨ Astra Home | New Knowledge Added",
                description=f"**Q:** {question_text}\n\n**A:** {self.answer_text}",
                color=SUCCESS_COLOR
            )
            try:
                await target_channel.send(f"📢 <@{user_id}>, your question has been answered!", embed=success_embed)
            except: pass
        
        await interaction.message.delete()
        await interaction.response.send_message(f"✅ Published! (+15 Karma for you)", ephemeral=True)

    @ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌", custom_id="qa_btn_reject")
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.message.delete()
        await interaction.response.send_message("↩️ Ticket rejected.", ephemeral=True)

# ------------------------------------------------------------------
# 5. DISAMBIGUATION
# ------------------------------------------------------------------

class DisambiguationSelect(ui.Select):
    def __init__(self, candidates):
        self.candidates = candidates
        options = []
        for i, c in enumerate(candidates[:25]):
            label = c['q'][:95] + "..." if len(c['q']) > 95 else c['q']
            options.append(discord.SelectOption(label=label, value=str(i), emoji="🕉️"))
        super().__init__(placeholder="Select the correct question:", options=options)

    async def callback(self, interaction: discord.Interaction):
        selection = self.candidates[int(self.values[0])]
        embed = discord.Embed(title="🕉️ Knowledge Base", description=selection['a'], color=SUCCESS_COLOR)
        embed.add_field(name="Topic", value=selection['q'])
        await interaction.response.edit_message(embed=embed, view=None)

class DisambiguationView(ui.View):
    def __init__(self, candidates):
        super().__init__(timeout=60)
        self.add_item(DisambiguationSelect(candidates))

# ------------------------------------------------------------------
# 6. BOT COMMANDS
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
        load_knowledge_base()
        await db_manager.initialize()
        await self.add_cog(QACog(self))
        await self.tree.sync()

class QACog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def calculate_match_score(self, query: str, target: str) -> float:
        query_l, target_l = query.lower(), target.lower()
        if query_l in target_l: return 1.0
        return difflib.SequenceMatcher(None, query_l, target_l).ratio()

    @app_commands.command(name="ask", description="Ask a question. Fuzzy matching included.")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer(ephemeral=False)
        candidates = []
        
        # Search Static
        for entry in STATIC_KNOWLEDGE_BASE:
            score = self.calculate_match_score(question, entry['q'])
            if score > 0.4:
                candidates.append({'q': entry['q'], 'a': entry['a'], 'score': score, 'source': 'static'})

        # Search DB
        db_rows = await db_manager.search_candidates(question)
        for row in db_rows:
            score = self.calculate_match_score(question, row['q'])
            candidates.append({'q': row['q'], 'a': row['a'], 'score': score, 'source': 'db'})

        candidates.sort(key=lambda x: x['score'], reverse=True)
        # Dedupe
        unique = []
        seen = set()
        for c in candidates:
            if c['q'] not in seen:
                unique.append(c)
                seen.add(c['q'])
        
        candidates = unique

        if not candidates:
            # Fallback to Admin
            review_channel = self.bot.get_channel(REVIEW_CHANNEL_ID)
            if not review_channel:
                await interaction.followup.send("⚠️ No match found & Review channel missing.", ephemeral=True)
                return

            embed = discord.Embed(title="📨 New Question", description=f"**Inquiry:**\n{question}", color=BRAND_COLOR)
            embed.add_field(name="User ID", value=str(interaction.user.id))
            embed.add_field(name="Channel ID", value=str(interaction.channel_id))
            await review_channel.send(embed=embed, view=AdminReviewView())
            await interaction.followup.send("✅ Sent to experts for review.")

        elif len(candidates) == 1 or (candidates[0]['score'] > 0.95):
            best = candidates[0]
            embed = discord.Embed(title="🕉️ Knowledge Base", description=best['a'], color=SUCCESS_COLOR)
            embed.add_field(name="Topic", value=best['q'])
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(
                embed=discord.Embed(title="🔍 Multiple Matches", description="Select the best fit:", color=INFO_COLOR),
                view=DisambiguationView(candidates)
            )

    # --- CRAZY NEW FEATURES (STRICTLY THEMED) ---

    @app_commands.command(name="quiz", description="Test your Vedic knowledge and earn Karma!")
    async def quiz(self, interaction: discord.Interaction):
        if len(STATIC_KNOWLEDGE_BASE) < 4:
            await interaction.response.send_message("Not enough data for a quiz yet!", ephemeral=True)
            return

        question_data = random.choice(STATIC_KNOWLEDGE_BASE)
        correct_answer = question_data['a']
        
        # Get 3 random wrong answers
        distractors = random.sample([x['a'] for x in STATIC_KNOWLEDGE_BASE if x['q'] != question_data['q']], 3)
        
        embed = discord.Embed(
            title="🧠 Astra Wisdom Quiz",
            description=f"**Question:** {question_data['q']}",
            color=MYSTIC_COLOR
        )
        embed.set_footer(text="Select the correct answer below. (+5 Karma)")
        
        await interaction.response.send_message(embed=embed, view=QuizView(correct_answer, distractors))

    @app_commands.command(name="meditate", description="Perform a Dhyana (Meditation) session.")
    async def meditate(self, interaction: discord.Interaction):
        success, wait_time = await db_manager.record_meditation(interaction.user.id)
        
        if not success:
            mins = int(wait_time.total_seconds() // 60)
            await interaction.response.send_message(f"🧘 You must rest. You can meditate again in {mins} minutes.", ephemeral=True)
            return

        msg = await interaction.response.send_message("🧘 **Entering Asana...** (Posture)", ephemeral=False)
        msg = await interaction.original_response()
        
        # Sanskrit/Vedic Stages
        stages = [
            "🌬️ **Pranayama...** (Controlling breath) [==........]",
            "👁️ **Pratyahara...** (Withdrawing senses) [====......]",
            "🧠 **Dharana...** (Concentration) [======....]",
            "🕉️ **Dhyana...** (Deep Meditation) [========..]",
            "✨ **Samadhi...** (Oneness) [==========]"
        ]
        
        for stage in stages:
            await asyncio.sleep(1.5)
            await msg.edit(content=stage)
        
        # Strictly Scriptural Quotes
        quotes = [
            "“You have a right to perform your prescribed duties, but you are not entitled to the fruits of your actions.” – *Bhagavad Gita 2.47*",
            "“Yoga is the journey of the self, through the self, to the self.” – *Bhagavad Gita 6.20*",
            "“As a lamp in a windless place does not flicker, so is the disciplined mind of a yogi practicing meditation.” – *Bhagavad Gita 6.19*",
            "“Lead me from the unreal to the real, lead me from darkness to light, lead me from death to immortality.” – *Brihadaranyaka Upanishad*",
            "“The little space within the heart is as great as the vast universe.” – *Chandogya Upanishad*"
        ]
        
        final_embed = discord.Embed(title="🙏 Shanti (Peace)", description=random.choice(quotes), color=SUCCESS_COLOR)
        final_embed.set_footer(text="+10 Karma gained")
        await msg.edit(content="", embed=final_embed)

    @app_commands.command(name="profile", description="Check your spiritual standing.")
    async def profile(self, interaction: discord.Interaction):
        row = await db_manager.get_user_profile(interaction.user.id)
        if not row:
            karma, meditations = 0, 0
        else:
            karma, meditations = row

        # Thematic Ranks
        if karma < 50: rank = "Sadhaka (Aspirant)"
        elif karma < 150: rank = "Brahmachari (Student)"
        elif karma < 300: rank = "Yogi (Practitioner)"
        elif karma < 500: rank = "Rishi (Sage)"
        else: rank = "Maharishi (Great Sage)"

        embed = discord.Embed(title=f"📜 {interaction.user.display_name}'s Profile", color=INFO_COLOR)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="Dharma Rank", value=f"**{rank}**", inline=False)
        embed.add_field(name="🌀 Karma", value=str(karma), inline=True)
        embed.add_field(name="🧘 Dhyana Sessions", value=str(meditations), inline=True)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="oracle", description="Seek guidance from the Shastras.")
    async def oracle(self, interaction: discord.Interaction, query: str):
        # Strictly Dharmic responses
        responses = [
            "This path aligns with your Dharma.",
            "Obstacles (Vighna) are present; perform selfless service (Seva) first.",
            "The outcome depends on your past Karma.",
            "Meditate on this; the answer lies within the Atman.",
            "Detach from the result, focus only on the action (Karma Yoga).",
            "Time (Kala) is the ultimate decider.",
            "Sattva Guna (purity) is required for success here."
        ]
        
        embed = discord.Embed(title="📜 Vedic Guidance", color=MYSTIC_COLOR)
        embed.add_field(name="Inquiry", value=query, inline=False)
        embed.add_field(name="Insight", value=f"||{random.choice(responses)}||", inline=False)
        
        await interaction.response.send_message(embed=embed)

async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token: return
    bot = AstraHomeBot()
    async with bot: await bot.start(token)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
