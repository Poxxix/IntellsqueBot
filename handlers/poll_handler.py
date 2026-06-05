import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, and_
from models.database import db_session
from models.spin import Reaction
from models.user import User

# Emoji list for poll options
NUM_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Creates a custom poll in the group."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    message_text = update.message.text
    
    # Parse quotes first
    args = re.findall(r'"([^"]*)"', message_text)
    if not args:
        # Fallback to splitting by space if no quotes
        args = context.args
        
    if len(args) < 3:
        await update.message.reply_text(
            "💡 **Cú pháp lệnh /vote:**\n"
            f'`/vote "Tiêu đề" "Phương án 1" "Phương án 2" ...`\n\n'
            f"*Ví dụ:* `/vote \"Trưa nay ăn gì?\" \"Cơm sườn\" \"Bún chả\" \"Bánh mì\"`",
            parse_mode="Markdown"
        )
        return
        
    title = args[0]
    options = args[1:11] # Max 10 options
    
    # Render poll
    poll_text = f"📊 **BÌNH CHỌN: {title}**\n\n"
    keyboard_row = []
    
    for idx, opt in enumerate(options):
        emoji = NUM_EMOJIS[idx]
        poll_text += f"{emoji} {opt}: `0` phiếu (0%)\n"
        keyboard_row.append(InlineKeyboardButton(emoji, callback_data=f"vote_click:{idx}"))
        
    poll_text += "\n👥 Tổng số: `0` vote"
    
    # Inline buttons in rows of 5
    keyboard = []
    for i in range(0, len(keyboard_row), 5):
        keyboard.append(keyboard_row[i:i+5])
        
    await update.message.reply_text(
        text=poll_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_react(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Attaches a quick reaction panel to a replied message or sends a new reaction message."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    target_msg = update.message.reply_to_message
    
    if not target_msg:
        await update.message.reply_text("💡 Hãy reply (trả lời) một tin nhắn và gõ `/react` để gắn bảng biểu cảm.")
        return
        
    # Send reaction keyboard referencing target message
    text = f"👍 `0` | 👎 `0` | 🤔 `0`"
    
    keyboard = [
        [
            InlineKeyboardButton("👍", callback_data=f"react_click:like:{target_msg.message_id}"),
            InlineKeyboardButton("👎", callback_data=f"react_click:dislike:{target_msg.message_id}"),
            InlineKeyboardButton("🤔", callback_data=f"react_click:think:{target_msg.message_id}")
        ]
    ]
    
    await target_msg.reply_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    # Delete the command message to keep chat clean
    try:
        await update.message.delete()
    except Exception:
        pass

async def handle_vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes callback clicks for polls."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split(":")
    option_idx = int(parts[1])
    
    chat_id = query.message.chat.id
    message_id = query.message.message_id
    user_id = query.from_user.id
    display_name = query.from_user.full_name
    
    async with db_session() as session:
        # Check if user already voted in this poll
        stmt = select(Reaction).where(
            and_(
                Reaction.chat_id == chat_id,
                Reaction.message_id == message_id,
                Reaction.user_id == user_id,
                Reaction.reaction_type == 'vote'
            )
        )
        res = await session.execute(stmt)
        existing = res.scalar_one_or_none()
        
        if existing:
            if existing.value == str(option_idx):
                # Toggle vote off if clicked the same option again
                await session.delete(existing)
            else:
                # Update to new option
                existing.value = str(option_idx)
        else:
            # Create new vote
            vote = Reaction(
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                user_name=display_name,
                reaction_type='vote',
                value=str(option_idx)
            )
            session.add(vote)
            
        await session.flush()
        
        # Get all votes for this poll
        stmt_all = select(Reaction).where(
            and_(
                Reaction.chat_id == chat_id,
                Reaction.message_id == message_id,
                Reaction.reaction_type == 'vote'
            )
        )
        res_all = await session.execute(stmt_all)
        all_votes = res_all.scalars().all()
        
    # Reconstruct original text & options from original message text
    original_text = query.message.text if query.message else ""
    lines = original_text.split("\n")
    if not lines or not lines[0].startswith("📊"):
        return
        
    title = lines[0].replace("📊 **BÌNH CHỌN: ", "").rstrip("**")
    
    # Parse options from lines
    options = []
    for line in lines[2:]:
        if not line.strip() or line.startswith("👥"):
            break
        # Find Option Name (starts with number emoji, then option name, then colon)
        match = re.match(r'^[1-9]️⃣|🔟\s*(.*?):', line)
        if match:
            options.append(match.group(1).strip())
        else:
            # Fallback parsing
            parts_line = line.split(":")
            if len(parts_line) > 0:
                opt_name = parts_line[0][3:].strip() # remove emoji
                options.append(opt_name)
                
    # Recalculate votes
    total_votes = len(all_votes)
    counts = {str(i): 0 for i in range(len(options))}
    for v in all_votes:
        if v.value in counts:
            counts[v.value] += 1
            
    # Re-render poll text
    new_text = f"📊 **BÌNH CHỌN: {title}**\n\n"
    for idx, opt in enumerate(options):
        emoji = NUM_EMOJIS[idx]
        cnt = counts.get(str(idx), 0)
        pct = (cnt / total_votes * 100) if total_votes > 0 else 0
        new_text += f"{emoji} {opt}: `{cnt}` phiếu ({pct:.0f}%)\n"
        
    new_text += f"\n👥 Tổng số: `{total_votes}` vote"
    
    await query.edit_message_text(new_text, parse_mode="Markdown", reply_markup=query.message.reply_markup)

async def handle_react_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes callback clicks for reactions."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split(":")
    react_val = parts[1] # like, dislike, think
    target_msg_id = int(parts[2])
    
    chat_id = query.message.chat.id
    message_id = query.message.message_id
    user_id = query.from_user.id
    display_name = query.from_user.full_name
    
    emoji_map = {
        "like": "👍",
        "dislike": "👎",
        "think": "🤔"
    }
    emoji = emoji_map.get(react_val, "👍")
    
    async with db_session() as session:
        # Check if user already reacted with this emoji on this message
        stmt = select(Reaction).where(
            and_(
                Reaction.chat_id == chat_id,
                Reaction.message_id == message_id,
                Reaction.user_id == user_id,
                Reaction.reaction_type == 'emoji',
                Reaction.value == emoji
            )
        )
        res = await session.execute(stmt)
        existing = res.scalar_one_or_none()
        
        if existing:
            # Toggle off
            await session.delete(existing)
        else:
            # Create new reaction
            react = Reaction(
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                user_name=display_name,
                reaction_type='emoji',
                value=emoji
            )
            session.add(react)
            
        await session.flush()
        
        # Get all emoji reactions for this panel
        stmt_all = select(Reaction).where(
            and_(
                Reaction.chat_id == chat_id,
                Reaction.message_id == message_id,
                Reaction.reaction_type == 'emoji'
            )
        )
        res_all = await session.execute(stmt_all)
        all_reacts = res_all.scalars().all()
        
    # Count totals
    counts = {"👍": 0, "👎": 0, "🤔": 0}
    for r in all_reacts:
        if r.value in counts:
            counts[r.value] += 1
            
    # Re-render reaction text
    new_text = f"👍 `{counts['👍']}` | 👎 `{counts['👎']}` | 🤔 `{counts['🤔']}`"
    
    await query.edit_message_text(new_text, parse_mode="Markdown", reply_markup=query.message.reply_markup)
