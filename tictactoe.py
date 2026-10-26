"""Крестики-нолики 5×5 PvP со ставкой. Таймаут — через фоновую чистку."""
import re
import time
import uuid
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, CallbackQueryHandler

import db
from helpers import RX, resolve_target, ensure_user, MENTION_RE, rate_limit

SIZE = 5
WIN_LEN = 4
TIMEOUT = 600  # 10 минут на игру — после этого фоновый cleanup вернёт ставки


def _empty():
    return [None] * (SIZE * SIZE)


def _check_win(board):
    for r in range(SIZE):
        for c in range(SIZE):
            p = board[r * SIZE + c]
            if not p:
                continue
            if c + WIN_LEN <= SIZE and all(board[r * SIZE + c + i] == p for i in range(WIN_LEN)):
                return p
            if r + WIN_LEN <= SIZE and all(board[(r + i) * SIZE + c] == p for i in range(WIN_LEN)):
                return p
            if (r + WIN_LEN <= SIZE and c + WIN_LEN <= SIZE
                    and all(board[(r + i) * SIZE + c + i] == p for i in range(WIN_LEN))):
                return p
            if (r + WIN_LEN <= SIZE and c - WIN_LEN + 1 >= 0
                    and all(board[(r + i) * SIZE + (c - i)] == p for i in range(WIN_LEN))):
                return p
    return None


def _kb(game_id, board, disabled=False):
    rows = []
    for r in range(SIZE):
        row = []
        for c in range(SIZE):
            cell = board[r * SIZE + c]
            label = cell if cell else "·"
            cb = "ttt:x" if disabled else f"ttt:mv:{game_id}:{r * SIZE + c}"
            row.append(InlineKeyboardButton(label, callback_data=cb))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


async def _name(context, uid):
    try:
        c = await context.bot.get_chat(uid)
        return "@" + c.username if c.username else (c.first_name or str(uid))
    except Exception:
        return str(uid)


def _game_text(g, name_a, name_b, current_turn_name):
    return (
        f"🎮 <b>Игра 5×5</b>\n"
        f"❌ {name_a}  vs  ⭕ {name_b}\n"
        f"💰 Ставка: <b>{g['bet']}</b>\n"
        f"Ход: <b>{current_turn_name}</b>"
    )


async def expire_stale(application):
    """Фоновая чистка зависших игр: возвращает ставки. Вызывается из Main."""
    games = application.bot_data.get("ttt", {})
    if not games:
        return
    now = time.time()
    for gid in list(games.keys()):
        g = games.get(gid)
        if not g:
            continue
        if g.get("finished"):
            games.pop(gid, None)
            continue
        if now - g["last_move_at"] <= TIMEOUT:
            continue
        # Таймаут — возвращаем ставки обоим
        try:
            await db.execute_multi(
                [
                    ("UPDATE users SET coins = coins + ? WHERE user_id=?", (g["bet"], g["p1"])),
                    ("UPDATE users SET coins = coins + ? WHERE user_id=?", (g["bet"], g["p2"])),
                ],
                expected_rowcounts=[1, 1],
            )
        except Exception:
            pass
        g["finished"] = True
        games.pop(gid, None)
        try:
            await application.bot.edit_message_text(
                chat_id=g["chat_id"],
                message_id=g["message_id"],
                text="⌛ <b>Время игры истекло.</b> Ставки возвращены.",
                parse_mode="HTML",
                reply_markup=_kb(gid, g["board"], disabled=True),
            )
        except Exception:
            pass


@rate_limit("ttt", 15, "⏳ Вызов в игру — раз в {left}с.")
async def _start_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    m = re.match(r"^хо\b\s*(.*)$", msg.text or "", re.IGNORECASE)
    rest = (m.group(1) if m else "").strip()

    target_id, uname, _ = await resolve_target(update, context, msg.text)
    if not target_id:
        await msg.reply_text("Пример: <code>хо @user 100</code> (или реплай + ставка)", parse_mode="HTML")
        return
    if target_id == msg.from_user.id:
        await msg.reply_text("С собой играть нельзя.")
        return
    clean = MENTION_RE.sub(" ", rest or msg.text or "")
    nums = re.findall(r"\d+", clean)
    if not nums:
        await msg.reply_text("Укажи ставку, например: <code>хо @user 100</code>", parse_mode="HTML")
        return
    bet = int(nums[-1])
    if bet <= 0:
        await msg.reply_text("Ставка должна быть положительной.")
        return

    await ensure_user(msg.from_user)
    await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (target_id,))
    row = await db.fetchone("SELECT coins FROM users WHERE user_id=?", (msg.from_user.id,))
    if not row or row[0] < bet:
        await msg.reply_text(f"⚠️ Недостаточно монет для ставки (у тебя {row[0] if row else 0}).")
        return

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Принять",    callback_data=f"ttt:ac:{msg.from_user.id}:{target_id}:{bet}"),
        InlineKeyboardButton("❌ Отклонить",  callback_data=f"ttt:dc:{msg.from_user.id}:{target_id}:{bet}"),
    ]])
    await msg.reply_text(
        f"🎮 <b>Вызов в крестики-нолики 5×5!</b>\n"
        f"{await _name(context, msg.from_user.id)} → {await _name(context, target_id)}\n"
        f"💰 Ставка: <b>{bet}</b>",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def challenge_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        _, action, frm_s, to_s, bet_s = q.data.split(":")
        frm, to, bet = int(frm_s), int(to_s), int(bet_s)
    except Exception:
        await q.answer("Ошибка данных.", show_alert=True)
        return
    if q.from_user.id != to:
        await q.answer("Этот вызов не тебе.", show_alert=True)
        return
    await q.answer()

    if action == "dc":
        await q.edit_message_text("❌ Вызов отклонён.")
        return

    try:
        await db.execute_multi(
            [
                ("UPDATE users SET coins = coins - ? WHERE user_id=? AND coins >= ?", (bet, frm, bet)),
                ("UPDATE users SET coins = coins - ? WHERE user_id=? AND coins >= ?", (bet, to, bet)),
            ],
            expected_rowcounts=[1, 1],
        )
    except Exception:
        r1 = await db.fetchone("SELECT coins FROM users WHERE user_id=?", (frm,))
        r2 = await db.fetchone("SELECT coins FROM users WHERE user_id=?", (to,))
        if not r1 or r1[0] < bet:
            await q.edit_message_text("⚠️ У вызывающего недостаточно монет.")
        elif not r2 or r2[0] < bet:
            await q.edit_message_text("⚠️ У тебя недостаточно монет для ставки.")
        else:
            await q.edit_message_text("⚠️ Не удалось списать ставки, попробуйте ещё раз.")
        return

    game_id = uuid.uuid4().hex[:8]
    board = _empty()
    turn = random.choice([frm, to])
    context.application.bot_data.setdefault("ttt", {})[game_id] = {
        "board": board, "p1": frm, "p2": to, "turn": turn,
        "bet": bet, "chat_id": q.message.chat_id, "message_id": q.message.message_id,
        "finished": False, "last_move_at": time.time(),
    }
    g = context.application.bot_data["ttt"][game_id]
    await q.edit_message_text(
        _game_text(g, await _name(context, frm), await _name(context, to), await _name(context, turn)),
        parse_mode="HTML",
        reply_markup=_kb(game_id, board),
    )


async def move_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        _, _, game_id, cell_s = q.data.split(":")
        cell = int(cell_s)
    except Exception:
        await q.answer("Ошибка.", show_alert=True)
        return
    games = context.application.bot_data.get("ttt", {})
    g = games.get(game_id)
    if not g or g["finished"]:
        await q.answer("Игра завершена.", show_alert=True)
        return
    if q.from_user.id != g["turn"]:
        await q.answer("Не твой ход.", show_alert=True)
        return
    if g["board"][cell]:
        await q.answer("Занято.", show_alert=True)
        return

    sym = "❌" if q.from_user.id == g["p1"] else "⭕"
    g["board"][cell] = sym
    g["last_move_at"] = time.time()
    winner = _check_win(g["board"])

    if winner:
        g["finished"] = True
        win_id = g["p1"] if winner == "❌" else g["p2"]
        loser = g["p2"] if win_id == g["p1"] else g["p1"]
        try:
            await db.execute_multi(
                [
                    ("UPDATE users SET coins = coins + ? WHERE user_id=?", (g["bet"] * 2, win_id)),
                    ("UPDATE users SET ttt_wins = ttt_wins + 1, ttt_played = ttt_played + 1 WHERE user_id=?", (win_id,)),
                    ("UPDATE users SET ttt_losses = ttt_losses + 1, ttt_played = ttt_played + 1 WHERE user_id=?", (loser,)),
                ],
                expected_rowcounts=[1, 1, 1],
            )
        except Exception:
            pass
        games.pop(game_id, None)
        await q.edit_message_text(
            f"🏆 <b>Победа!</b> {await _name(context, win_id)} выиграл <b>{g['bet'] * 2}</b> монет.",
            parse_mode="HTML",
            reply_markup=_kb(game_id, g["board"], disabled=True),
        )
        return

    if all(g["board"]):
        g["finished"] = True
        try:
            await db.execute_multi(
                [
                    ("UPDATE users SET coins = coins + ? WHERE user_id=?", (g["bet"], g["p1"])),
                    ("UPDATE users SET coins = coins + ? WHERE user_id=?", (g["bet"], g["p2"])),
                ],
                expected_rowcounts=[1, 1],
            )
        except Exception:
            pass
        games.pop(game_id, None)
        await q.edit_message_text(
            "🤝 <b>Ничья.</b> Ставки возвращены.",
            parse_mode="HTML",
            reply_markup=_kb(game_id, g["board"], disabled=True),
        )
        return

    g["turn"] = g["p2"] if g["turn"] == g["p1"] else g["p1"]
    try:
        await q.edit_message_text(
            _game_text(
                g,
                await _name(context, g["p1"]),
                await _name(context, g["p2"]),
                await _name(context, g["turn"]),
            ),
            parse_mode="HTML",
            reply_markup=_kb(game_id, g["board"]),
        )
    except Exception:
        await q.edit_message_reply_markup(reply_markup=_kb(game_id, g["board"]))


async def _ignore_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


def register(app):
    app.add_handler(MessageHandler(RX(r"^хо\b"), _start_challenge))
    app.add_handler(CallbackQueryHandler(challenge_cb, pattern=r"^ttt:(ac|dc):"))
    app.add_handler(CallbackQueryHandler(move_cb,       pattern=r"^ttt:mv:"))
    app.add_handler(CallbackQueryHandler(_ignore_cb,    pattern=r"^ttt:x$"))
