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

# ------------------------------------------------------------------
# 2. HINDUISM KNOWLEDGE BASE (EXPANDED)
# ------------------------------------------------------------------

HINDUISM_DATA = [
    ("What is Hinduism?", "Hinduism, or Sanatana Dharma, is the world's oldest living religion. It is a synthesis of various Indian cultures and traditions, with diverse beliefs including Dharma, Karma, Samsara (cycle of rebirth), and Moksha (liberation)."),
    ("Who are the Trimurti?", "The Trimurti represents the three cosmic functions: Brahma (The Creator), Vishnu (The Preserver), and Shiva (The Destroyer/Transformer)."),
    ("What is Karma?", "Karma is the universal law of cause and effect. Every thought, word, and action creates energy that influences a person's future and next life."),
    ("What is Dharma?", "Dharma is the moral order of the universe and a code of living. It signifies duty, righteousness, and the path one must follow in life."),
    ("Who is Lord Ganesha?", "Ganesha is the elephant-headed deity, revered as the remover of obstacles (Vighnaharta), the patron of arts and sciences, and the god of intellect and wisdom."),
    ("Who is Lord Shiva?", "Shiva is the Supreme Being in Shaivism. He is the destroyer of evil and the transformer, often depicted as a yogi in deep meditation on Mount Kailash."),
    ("Who is Lord Vishnu?", "Vishnu is the preserver of the universe in Vaishnavism. He incarnates (Avatars) on Earth to restore balance when evil threatens Dharma. Famous avatars include Rama and Krishna."),
    ("What is the Bhagavad Gita?", "The Bhagavad Gita is a 700-verse scripture that is part of the Mahabharata. It is a conversation between Prince Arjuna and Lord Krishna concerning duty (Dharma) and spiritual liberation."),
    ("What are the Vedas?", "The Vedas are the oldest scriptures of Hinduism, considered 'shruti' (that which is heard). The four Vedas are: Rigveda, Samaveda, Yajurveda, and Atharvaveda."),
    ("What is Moksha?", "Moksha is the liberation from Samsara, the cycle of birth, death, and rebirth. It is the ultimate goal of human life in Hindu philosophy."),
    ("What is Yoga?", "Yoga is a group of physical, mental, and spiritual practices originating in ancient India, aimed at controlling the mind and recognizing the detached 'witness-consciousness'."),
    ("What is Atman?", "Atman refers to the self, soul, or spirit. In Hindu philosophy, realizing that the Atman is distinct from the body and mind is a key step towards Moksha."),
    ("What is Brahman?", "Brahman is the ultimate reality, the formless, infinite, and eternal source of all existence in Hindu philosophy."),
    ("Who is Hanuman?", "Hanuman is a divine vanara (monkey) companion of the god Rama. He is a symbol of strength, energy, and selfless devotion (Bhakti)."),
    ("What is Diwali?", "Diwali is the festival of lights, symbolizing the spiritual victory of light over darkness, good over evil, and knowledge over ignorance."),
    ("What is Holi?", "Holi is the festival of colors, celebrating the arrival of spring and the victory of good over evil (Holika Dahan)."),
    ("What is a Mantra?", "A mantra is a sacred utterance, a numinous sound, a syllable, word or phonemes, or group of words in Sanskrit believed to have psychological and/or spiritual powers."),
    ("What is Om?", "Om (Aum) is the sacred sound and spiritual symbol in Hinduism. It signifies the essence of the ultimate reality, consciousness, or Atman."),
    ("What is Reincarnation?", "Reincarnation is the philosophical concept that the non-physical essence of a living being starts a new life in a different physical form or body after biological death."),
    ("Who is Goddess Durga?", "Durga is a major deity in Hinduism, worshipped as a principal aspect of the mother goddess Devi. She is associated with protection, strength, motherhood, and destruction of wars."),
    ("Who is Goddess Lakshmi?", "Lakshmi is the goddess of wealth, fortune, power, beauty, and prosperity. She is the wife and active energy (Shakti) of Vishnu."),
    ("Who is Goddess Saraswati?", "Saraswati is the goddess of knowledge, music, art, speech, wisdom, and learning."),
    ("What is the Ramayana?", "The Ramayana is an ancient Indian epic which narrates the struggle of the divine prince Rama to rescue his wife Sita from the demon king Ravana."),
    ("What is the Mahabharata?", "The Mahabharata is one of the two major Sanskrit epics of ancient India. It narrates the struggle between two groups of cousins in the Kurukshetra War and the fates of the Kaurava and the Pandava princes."),
    ("What is Puja?", "Puja is a prayer ritual performed by Hindus of devotional worship to one or more deities, or to host and honor a guest, or one to spiritually celebrate an event."),
    ("What is a Guru?", "A Guru is a spiritual teacher or guide who helps the disciple on the path to self-realization."),
    ("What is Ahimsa?", "Ahimsa is the principle of non-violence toward all living beings. It is a key virtue in Hinduism, Jainism, and Buddhism."),
    ("What are the 4 aims of life?", "The Purusharthas are the four proper goals of a human life: Dharma (righteousness), Artha (prosperity), Kama (pleasure), and Moksha (liberation)."),
    ("What is a Temple (Mandir)?", "A Mandir is a Hindu temple, a symbolic house, seat and body of god. It is a structure designed to bring human beings and gods together."),
    ("What is Tilak?", "A Tilak is a mark worn usually on the forehead, sometimes other parts of the body such as neck, hand or chest. It may be worn daily or for rites of passage or special religious occasions."),
    ("What is Prasad?", "Prasad is a material substance of food that is a religious offering in both Hinduism and Sikhism. It is normally consumed by worshippers after worship."),
    ("Who is Krishna?", "Krishna is a major deity in Hinduism. He is worshipped as the eighth avatar of Vishnu and also as the supreme God in his own right."),
    ("What is Navaratri?", "Navaratri is a Hindu festival that spans nine nights (and ten days) and is celebrated every year in the autumn. It is observed for different reasons and celebrated differently in various parts of the Indian cultural sphere."),
    ("What is Karma Yoga?", "Karma Yoga is the spiritual discipline of selfless action as a way to perfection."),
    ("What is Bhakti Yoga?", "Bhakti Yoga is a spiritual path or spiritual practice within Hinduism focused on loving devotion towards any personal deity."),
    ("What is Jnana Yoga?", "Jnana Yoga is the spiritual discipline of knowledge and insight."),
    ("What is Raja Yoga?", "Raja Yoga is the path of meditation and self-discipline."),
    ("What is Advaita Vedanta?", "Advaita Vedanta is a school of Hindu philosophy that emphasizes the oneness of the individual soul (Atman) and the ultimate reality (Brahman)."),
    ("Who is Adi Shankaracharya?", "Adi Shankaracharya was an early 8th-century Indian philosopher and theologian who consolidated the doctrine of Advaita Vedanta."),
    ("What is Ayurveda?", "Ayurveda is a traditional system of medicine with historical roots in the Indian subcontinent."),
    ("What is the Caste System (Varna)?", "The Varna system classifies society into four classes: Brahmins (priests), Kshatriyas (warriors), Vaishyas (merchants), and Shudras (laborers). It was originally based on qualities and duties, not birth, though it rigidified over time."),
    ("What is a Sannyasin?", "A Sannyasin is one who has renounced the world in order to attain Moksha."),
    ("What is Maya?", "Maya is the illusion or magic power with which a god can make human beings believe in what turns out to be an illusion."),
    ("What is Samsara?", "Samsara is the beginningless cycle of repeated birth, mundane existence and dying again."),
    ("What is Sanatana Dharma?", "Sanatana Dharma is the eternal order or eternal duty, the indigenous name for Hinduism."),
    ("Who is Kartikeya?", "Kartikeya (also Murugan or Skanda) is the Hindu god of war and the son of Shiva and Parvati."),
    ("What is a Yajna?", "Yajna refers to any ritual done in front of a sacred fire, often with mantras."),
    ("What is Raksha Bandhan?", "Raksha Bandhan is a popular, traditionally Hindu, annual rite, or ceremony, which is central to a festival of the same name, celebrating the love and duty between brothers and sisters."),
    ("Who is Yamraj?", "Yama is the Hindu god of death and justice, responsible for dispensing the law and punishing sinners in their afterlives."),
    ("What is Swastika?", "The Swastika is a geometrical figure and an ancient religious icon in the cultures of Eurasia. In Hinduism, it is a symbol of divinity and spirituality.")
]

# ------------------------------------------------------------------
# 3. DATABASE MANAGER
# ------------------------------------------------------------------

class DatabaseManager:
    def __init__(self, db_name: str):
        self.db_name = db_name

    async def initialize(self):
        """Creates tables and automatically seeds data."""
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
            
            # Auto-Seed Check
            async with db.execute("SELECT COUNT(*) FROM faq") as cursor:
                row = await cursor.fetchone()
                count = row[0]
                logger.info(f"Database currently holds {count} entries.")
                if count < 5: # If DB is nearly empty, force seed
                    await self.seed_data(db)

    async def seed_data(self, db_conn=None):
        """Injects the Hinduism dataset."""
        logger.info("⚡ Seeding Knowledge Base with Hinduism Data...")
        
        # Helper to execute insert
        async def insert_many(conn):
            for q, a in HINDUISM_DATA:
                # Check if exists first to prevent dupes during manual seed
                cursor = await conn.execute("SELECT id FROM faq WHERE question_text = ?", (q,))
                if not await cursor.fetchone():
                    await conn.execute(
                        """INSERT INTO faq (question_text, answer_text, author_id, approver_id, created_at)
                        VALUES (?, ?, 0, 0, ?)""",
                        (q, a, datetime.now())
                    )
            await conn.commit()

        if db_conn:
            await insert_many(db_conn)
        else:
            async with aiosqlite.connect(self.db_name) as db:
                await insert_many(db)
        
        logger.info(f"✅ Seeding Complete. Added {len(HINDUISM_DATA)} entries.")

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
        Smart Search: Checks substrings and keywords.
        """
        async with aiosqlite.connect(self.db_name) as db:
            # Logic:
            # 1. Check if stored question is inside user query ("What is Karma please" contains "What is Karma")
            # 2. Check if user query is inside stored question (User types "Karma", matches "What is Karma?")
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
                total = (await cursor.fetchone())[0]
            
            async with db.execute("SELECT question_text, use_count FROM faq ORDER BY use_count DESC LIMIT 3") as cursor:
                top_3 = await cursor.fetchall()
                
            return total, top_3

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
# 4. UI COMPONENTS
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
            success_embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/616/616490.png") # Generic Om symbol or star
            success_embed.set_footer(text=f"Approved by {interaction.user.display_name}")
            
            try:
                # Ping the user but send embed publicly
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
# 5. BOT COMMANDS
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
        await db_manager.initialize()
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
        # CHANGED: ephemeral=False ensures everyone sees the response
        await interaction.response.defer(ephemeral=False)

        # 1. Search DB
        answer, matched_q = await db_manager.find_answer(question)

        if answer:
            # Answer Found
            embed = discord.Embed(
                title="🕉️ Astra Home Knowledge Base",
                description=answer,
                color=SUCCESS_COLOR
            )
            embed.add_field(name="Topic", value=matched_q, inline=False)
            embed.set_footer(text=f"Asked by {interaction.user.display_name} • Instant Answer")
            
            # Send public response
            await interaction.followup.send(embed=embed)
        else:
            # Send to Admin Review
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
        total, top_3 = await db_manager.get_stats()
        
        embed = discord.Embed(title="📊 Astra Home Stats", color=INFO_COLOR)
        embed.add_field(name="Total Questions", value=str(total), inline=False)
        
        top_text = ""
        for i, (q, count) in enumerate(top_3, 1):
            top_text += f"**{i}.** {q} ({count} views)\n"
        
        if top_text:
            embed.add_field(name="🔥 Trending Topics", value=top_text, inline=False)
            
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

    @app_commands.command(name="seed", description="[Admin] Force-reload the Hinduism dataset.")
    @app_commands.default_permissions(administrator=True)
    async def seed(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await db_manager.seed_data()
        await interaction.followup.send("✅ Database seeded with Hinduism pack.")

# ------------------------------------------------------------------
# 6. ENTRY POINT
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
