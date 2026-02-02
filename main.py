import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
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
MYSTIC_COLOR = 0x9b59b6   

DB_NAME = os.getenv("DB_NAME", "astra_home.db")
REVIEW_CHANNEL_ID = int(os.getenv("REVIEW_CHANNEL_ID", 0))

# --- EXPERT CONFIGURATION ---
# Add the Discord User IDs of your experts here.
EXPERT_IDS = [
    1467844647773802579, 
    861825627032125491
]

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
            # Users Table (Updated with last_daily)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    karma INTEGER DEFAULT 0,
                    meditations INTEGER DEFAULT 0,
                    last_meditation TIMESTAMP,
                    last_daily TIMESTAMP
                )
            """)
            
            # MIGRATION CHECK: Attempt to add columns if they don't exist (for older DB versions)
            try:
                await db.execute("ALTER TABLE users ADD COLUMN last_daily TIMESTAMP")
            except Exception:
                pass # Column likely exists
                
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

    async def search_candidates(self, query: str):
        async with aiosqlite.connect(self.db_name) as db:
            cursor = await db.execute(
                """SELECT question_text, answer_text, id 
                FROM faq 
                WHERE question_text LIKE ? OR ? LIKE ('%' || question_text || '%')
                LIMIT 15""",
                (f"%{query}%", query)
            )
            rows = await cursor.fetchall()
            return [{'q': r[0], 'a': r[1], 'source': 'db', 'id': r[2]} for r in rows]

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
            async with db.execute("SELECT last_meditation FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    last = datetime.fromisoformat(row[0])
                    if now - last < timedelta(hours=1):
                        return False, (timedelta(hours=1) - (now - last))

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

    async def claim_daily(self, user_id: int):
        now = datetime.now()
        async with aiosqlite.connect(self.db_name) as db:
            async with db.execute("SELECT last_daily FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    last = datetime.fromisoformat(row[0])
                    if now - last < timedelta(hours=24):
                        return False, (timedelta(hours=24) - (now - last))
            
            # Give 50 Karma for daily
            await db.execute("""
                INSERT INTO users (user_id, karma, last_daily) 
                VALUES (?, 50, ?)
                ON CONFLICT(user_id) DO UPDATE SET 
                    karma = karma + 50, 
                    last_daily = ?
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
        super().__init__(style=discord.ButtonStyle.secondary, label=label[:80])
        self.is_correct = is_correct
        self.quiz_view = quiz_view

    async def callback(self, interaction: discord.Interaction):
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
        # Allow anyone to draft an answer, remove expert check here.
        embed = interaction.message.embeds[0]
        description = embed.description or ""
        question_text = description.replace("**Inquiry:**\n", "").strip()
        await interaction.response.send_modal(AnswerModal(question_text))

    @ui.button(label="Discard", style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="qa_btn_delete")
    async def delete_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id not in EXPERT_IDS:
            await interaction.response.send_message("🚫 **Access Denied:** Only designated Experts can discard tickets.", ephemeral=True)
            return

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
        if interaction.user.id not in EXPERT_IDS:
            await interaction.response.send_message("🚫 **Access Denied:** Only designated Experts can publish answers.", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        user_id = int(discord.utils.get(embed.fields, name="User ID").value)
        channel_id = int(discord.utils.get(embed.fields, name="Channel ID").value)
        question_text = embed.description.split("\n\n**Proposed Answer:**")[0].replace("**Inquiry:** ", "").strip()
        
        await db_manager.add_qa(question_text, self.answer_text, user_id, interaction.user.id)
        await db_manager.update_karma(interaction.user.id, 15)

        target_channel = interaction.client.get_channel(channel_id)
        
        if target_channel:
            success_embed = discord.Embed(
                title="✨ Astra Home | New Knowledge Added",
                description=f"**Q:** {question_text}\n\n**A:** {self.answer_text}",
                color=SUCCESS_COLOR
            )
            success_embed.set_footer(text=f"Answered by Expert: {interaction.user.display_name}")
            try:
                await target_channel.send(f"📢 <@{user_id}>, your question has been answered!", embed=success_embed)
            except discord.Forbidden:
                await interaction.followup.send("⚠️ Saved to DB, but failed to message user (Permissions).", ephemeral=True)
            except Exception as e:
                logger.error(f"Failed to send message to channel {channel_id}: {e}")
        else:
            await interaction.followup.send("⚠️ Saved to DB, but could not find the original channel.", ephemeral=True)
        
        await interaction.message.delete()
        await interaction.response.send_message(f"✅ Published! (+15 Karma for you)", ephemeral=True)

    @ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌", custom_id="qa_btn_reject")
    async def reject(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id not in EXPERT_IDS:
            await interaction.response.send_message("🚫 **Access Denied.**", ephemeral=True)
            return
            
        await interaction.message.delete()
        await interaction.response.send_message("↩️ Ticket rejected.", ephemeral=True)

# ------------------------------------------------------------------
# 5. DISAMBIGUATION & SUBMISSION LOGIC
# ------------------------------------------------------------------

class DisambiguationSelect(ui.Select):
    def __init__(self, candidates, bot, user, original_question):
        self.candidates = candidates
        self.bot = bot
        self.user = user
        self.original_question = original_question
        
        options = []
        for i, c in enumerate(candidates[:24]):
            label = c['q'][:90] + "..." if len(c['q']) > 90 else c['q']
            options.append(discord.SelectOption(label=label, value=str(i), emoji="🕉️"))
            
        options.append(discord.SelectOption(
            label="None of these / Send to Experts", 
            value="EXP_REQ", 
            description="Forward this question to admin review", 
            emoji="📨"
        ))
        
        super().__init__(placeholder="Select the correct question OR ask Experts:", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This menu is not for you.", ephemeral=True)
            return

        if self.values[0] == "EXP_REQ":
            review_channel = self.bot.get_channel(REVIEW_CHANNEL_ID)
            if not review_channel:
                await interaction.response.send_message("⚠️ System Error: Review channel unavailable.", ephemeral=True)
                return

            embed = discord.Embed(
                title="📨 New Question Received",
                description=f"**Inquiry:**\n{self.original_question}",
                color=BRAND_COLOR,
                timestamp=discord.utils.utcnow()
            )
            embed.set_author(name=f"{self.user.display_name}", icon_url=self.user.display_avatar.url)
            embed.add_field(name="User ID", value=str(self.user.id), inline=True)
            embed.add_field(name="Channel ID", value=str(interaction.channel_id), inline=True)
            embed.set_footer(text="Awaiting Expert Answer")

            await review_channel.send(embed=embed, view=AdminReviewView())
            
            confirm_embed = discord.Embed(
                description=f"✅ **Sent!** Your question has been forwarded to the **Astra Home Experts**.",
                color=SUCCESS_COLOR
            )
            await interaction.response.edit_message(embed=confirm_embed, view=None)

        else:
            selection = self.candidates[int(self.values[0])]
            embed = discord.Embed(title="🕉️ Knowledge Base", description=selection['a'], color=SUCCESS_COLOR)
            embed.add_field(name="Topic", value=selection['q'])
            await interaction.response.edit_message(embed=embed, view=None)

class DisambiguationView(ui.View):
    def __init__(self, candidates, bot, user, original_question):
        super().__init__(timeout=60)
        self.add_item(DisambiguationSelect(candidates, bot, user, original_question))

class ConfirmSubmissionView(ui.View):
    def __init__(self, bot, question, user):
        super().__init__(timeout=60)
        self.bot = bot
        self.question = question
        self.user = user

    @ui.button(label="Send to Experts", style=discord.ButtonStyle.primary, emoji="📨")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This action is not for you.", ephemeral=True)
            return
        
        button.disabled = True
        await interaction.response.edit_message(view=self)

        review_channel = self.bot.get_channel(REVIEW_CHANNEL_ID)
        if not review_channel:
            await interaction.followup.send("⚠️ System Error: Review channel unavailable.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📨 New Question Received",
            description=f"**Inquiry:**\n{self.question}",
            color=BRAND_COLOR,
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=f"{self.user.display_name}", icon_url=self.user.display_avatar.url)
        embed.add_field(name="User ID", value=str(self.user.id), inline=True)
        embed.add_field(name="Channel ID", value=str(interaction.channel_id), inline=True)
        embed.set_footer(text="Awaiting Expert Answer")

        await review_channel.send(embed=embed, view=AdminReviewView())
        
        confirm_embed = discord.Embed(
            description=f"✅ **Sent!** Your question has been forwarded to the **Astra Home Experts**.",
            color=SUCCESS_COLOR
        )
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This action is not for you.", ephemeral=True)
            return
        await interaction.response.edit_message(content="❌ Request cancelled.", embed=None, view=None)
        self.stop()

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
        self.rotate_status.start() # Start Status Loop

    @tasks.loop(minutes=10)
    async def rotate_status(self):
        statuses = [
            "/ask | Vedic Wisdom",
            "Helping Seekers",
            "Reading scriptures...",
            "Meditating on Dharma",
            "/quiz | Test Knowledge"
        ]
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=random.choice(statuses)))

    @rotate_status.before_loop
    async def before_rotate(self):
        await self.wait_until_ready()

class QACog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def calculate_match_score(self, query: str, target: str) -> float:
        stopwords = {'who', 'what', 'where', 'when', 'why', 'how', 'is', 'are', 'the', 'a', 'an', 'in', 'of', 'for', 'to', 'do', 'does', 'did'}
        def clean_text(text):
            words = ''.join(c for c in text.lower() if c.isalnum() or c.isspace()).split()
            cleaned = [w for w in words if w not in stopwords]
            return " ".join(cleaned)

        query_clean = clean_text(query)
        target_clean = clean_text(target)

        if not query_clean:
            query_clean = query.lower()
            target_clean = target.lower()

        if query_clean and query_clean in target_clean:
            return 0.95
        
        return difflib.SequenceMatcher(None, query_clean, target_clean).ratio()

    @app_commands.command(name="ask", description="Ask a question. Fuzzy matching included.")
    async def ask(self, interaction: discord.Interaction, question: str):
        await interaction.response.defer(ephemeral=False)
        candidates = []
        
        for entry in STATIC_KNOWLEDGE_BASE:
            score = self.calculate_match_score(question, entry['q'])
            if score > 0.6: 
                candidates.append({'q': entry['q'], 'a': entry['a'], 'score': score, 'source': 'static'})

        db_rows = await db_manager.search_candidates(question)
        for row in db_rows:
            score = self.calculate_match_score(question, row['q'])
            if score > 0.6:
                candidates.append({'q': row['q'], 'a': row['a'], 'score': score, 'source': 'db'})

        candidates.sort(key=lambda x: x['score'], reverse=True)
        unique = []
        seen = set()
        for c in candidates:
            if c['q'] not in seen:
                unique.append(c)
                seen.add(c['q'])
        
        candidates = unique

        if not candidates:
            embed = discord.Embed(
                title="🤔 No Answer Found",
                description="I couldn't find a matching answer in the scriptures. Would you like to send this question to our **Experts**?",
                color=WARNING_COLOR
            )
            view = ConfirmSubmissionView(self.bot, question, interaction.user)
            await interaction.followup.send(embed=embed, view=view)

        elif len(candidates) == 1 and candidates[0]['score'] > 0.95:
            best = candidates[0]
            embed = discord.Embed(title="🕉️ Knowledge Base", description=best['a'], color=SUCCESS_COLOR)
            embed.add_field(name="Topic", value=best['q'])
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(
                embed=discord.Embed(title="🔍 I found potential matches", description="Select the correct question, or send yours to the experts:", color=INFO_COLOR),
                view=DisambiguationView(candidates, self.bot, interaction.user, question)
            )

    # --- ENHANCED FEATURES ---

    @app_commands.command(name="daily", description="Claim your daily Karma reward (Every 24h).")
    async def daily(self, interaction: discord.Interaction):
        success, wait_time = await db_manager.claim_daily(interaction.user.id)
        if not success:
            hours = int(wait_time.total_seconds() // 3600)
            mins = int((wait_time.total_seconds() % 3600) // 60)
            await interaction.response.send_message(f"⏳ **Patience, seeker.** Come back in {hours}h {mins}m.", ephemeral=True)
            return
        
        embed = discord.Embed(title="🌞 Daily Blessings", description="You have received **50 Karma** points today!", color=SUCCESS_COLOR)
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3233/3233497.png")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mantra", description="Receive a powerful Vedic Mantra for contemplation.")
    async def mantra(self, interaction: discord.Interaction):
        mantras = [
            {"s": "Om Namah Shivaya", "m": "I bow to Shiva (The Self)", "b": "Peace, removal of fear, and spiritual awakening."},
            {"s": "Om Gam Ganapataye Namaha", "m": "Salutations to Ganesha", "b": "Removal of obstacles and success in new ventures."},
            {"s": "Gayatri Mantra", "m": "Om Bhur Bhuva Swaha...", "b": "Illumination of intellect and spiritual light."},
            {"s": "Mahamrityunjaya Mantra", "m": "Om Tryambakam Yajamahe...", "b": "Healing, protection, and liberation from the fear of death."},
            {"s": "Om Mani Padme Hum", "m": "The Jewel in the Lotus", "b": "Purification of the mind and cultivation of compassion."}
        ]
        choice = random.choice(mantras)
        
        embed = discord.Embed(title="📿 Sacred Mantra", description=f"# {choice['s']}", color=MYSTIC_COLOR)
        embed.add_field(name="Meaning", value=choice['m'], inline=False)
        embed.add_field(name="Benefit", value=choice['b'], inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="quiz", description="Test your Vedic knowledge and earn Karma!")
    async def quiz(self, interaction: discord.Interaction):
        if len(STATIC_KNOWLEDGE_BASE) < 4:
            await interaction.response.send_message("Not enough data for a quiz yet!", ephemeral=True)
            return

        question_data = random.choice(STATIC_KNOWLEDGE_BASE)
        correct_answer = question_data['a']
        distractors = random.sample([x['a'] for x in STATIC_KNOWLEDGE_BASE if x['q'] != question_data['q']], 3)
        
        embed = discord.Embed(title="🧠 Astra Wisdom Quiz", description=f"**Question:** {question_data['q']}", color=MYSTIC_COLOR)
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
        
        quotes = [
            "“You have a right to perform your prescribed duties, but you are not entitled to the fruits of your actions.” – *Bhagavad Gita 2.47*",
            "“Yoga is the journey of the self, through the self, to the self.” – *Bhagavad Gita 6.20*",
            "“As a lamp in a windless place does not flicker, so is the disciplined mind of a yogi practicing meditation.” – *Bhagavad Gita 6.19*"
        ]
        
        final_embed = discord.Embed(title="🙏 Shanti (Peace)", description=random.choice(quotes), color=SUCCESS_COLOR)
        final_embed.set_footer(text="+10 Karma gained")
        await msg.edit(content="", embed=final_embed)

    @app_commands.command(name="profile", description="Check your spiritual standing.")
    async def profile(self, interaction: discord.Interaction):
        row = await db_manager.get_user_profile(interaction.user.id)
        karma, meditations = row if row else (0, 0)

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
        responses = [
            "This path aligns with your Dharma.",
            "Obstacles (Vighna) are present; perform selfless service (Seva) first.",
            "The outcome depends on your past Karma.",
            "Meditate on this; the answer lies within the Atman.",
            "Detach from the result, focus only on the action (Karma Yoga)."
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


