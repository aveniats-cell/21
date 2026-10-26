"""Монеты, кредит, погашение. Денежные операции — атомарные UPDATE."""
import re
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

import db
import config
from helpers import is_admin_user, resolve_target, ensure_user, RX


async def add_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not is_admin_user(msg.from_user):
        await msg.reply_text("⛔ Только админ может начислять монеты.")
        return
    m = re.match(r"^[+]монеты\s+(\d+)", msg.text or "", re.IGNORECASE)
    if not m:
        await msg.reply_text("Пример: <code>+Монеты 500 @user</code>", parse_mode="HTML")
        return
    amount = int(m.group(1))
    if amount <= 0 or amount > 10_000_000:
        await msg.reply_text("Сумма должна быть от 1 до 10 000 000.")
        return
    tid, uname, _ = await resolve_target(update, context, msg.text)
    if not tid:
        await msg.reply_text("Укажи получателя: реплай или @username.")
        return
    await ensure_user(msg.from_user)
    await db.execute(
        "INSERT OR IGNORE INTO users (user_id, coins) VALUES (?, 0)", (tid,)
    )
    await db.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (amount, tid))
    await msg.reply_text(
        f"💰 Начислено <b>{amount}</b> монет @{uname or tid}.", parse_mode="HTML"
    )


async def take_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    m = re.match(r"^[+]кредит\s+(\d+)$", msg.text or "", re.IGNORECASE)
    if not m:
        await msg.reply_text("Пример: <code>+Кредит 50</code>", parse_mode="HTML")
        return
    amount = int(m.group(1))
    if not 1 <= amount <= config.CREDIT_MAX:
        await msg.reply_text(f"Сумма кредита: <b>1–{config.CREDIT_MAX}</b>.", parse_mode="HTML")
        return
    await ensure_user(msg.from_user)

    try:
        await db.execute_multi(
            [(
                "UPDATE users SET coins = coins + ?, credit = credit + ? "
                "WHERE user_id=? AND coins >= 0 AND credit + ? <= ?",
                (amount, amount, msg.from_user.id, amount, config.CREDIT_MAX),
            )],
            expected_rowcounts=[1],
        )
    except Exception:
        row = await db.fetchone(
            "SELECT coins, credit FROM users WHERE user_id=?", (msg.from_user.id,)
        )
        coins, credit = (row[0], row[1]) if row else (0, 0)
        if coins < 0:
            await msg.reply_text(
                "⚠️ Ты в минусе — кредит не выдаётся. Обратись к админу: <code>+Монеты</code>.",
                parse_mode="HTML",
            )
        else:
            await msg.reply_text(
                f"⚠️ Кредитный лимит <b>{config.CREDIT_MAX}</b>. У тебя уже <b>{credit}</b>.",
                parse_mode="HTML",
            )
        return

    row = await db.fetchone(
        "SELECT credit FROM users WHERE user_id=?", (msg.from_user.id,)
    )
    credit_now = row[0] if row else amount
    await msg.reply_text(
        f"💳 Выдан кредит <b>{amount}</b>. Итого: <b>{credit_now}/{config.CREDIT_MAX}</b>.\n"
        f"Для погашения: <code>-Кредит {amount}</code>",
        parse_mode="HTML",
    )


async def repay_credit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    m = re.match(r"^[-]кредит\s+(\d+)$", msg.text or "", re.IGNORECASE)
    if not m:
        return
    amount = int(m.group(1))
    if amount <= 0:
        return
    await ensure_user(msg.from_user)

    try:
        await db.execute_multi(
            [(
                "UPDATE users SET coins = coins - ?, credit = credit - ? "
                "WHERE user_id=? AND coins >= ? AND credit >= ?",
                (amount, amount, msg.from_user.id, amount, amount),
            )],
            expected_rowcounts=[1],
        )
    except Exception:
        row = await db.fetchone(
            "SELECT coins, credit FROM users WHERE user_id=?", (msg.from_user.id,)
        )
        coins, credit = (row[0], row[1]) if row else (0, 0)
        if credit <= 0:
            await msg.reply_text("У тебя нет кредита.")
        elif amount > credit:
            await msg.reply_text(f"Твой кредит всего <b>{credit}</b>.", parse_mode="HTML")
        else:
            await msg.reply_text(
                f"⚠️ Недостаточно монет: у тебя <b>{coins}</b>, нужно <b>{amount}</b>.",
                parse_mode="HTML",
            )
        return

    row = await db.fetchone(
        "SELECT credit FROM users WHERE user_id=?", (msg.from_user.id,)
    )
    credit_now = row[0] if row else 0
    await msg.reply_text(
        f"✅ Погашено <b>{amount}</b>. Остаток кредита: <b>{credit_now}</b>.",
        parse_mode="HTML",
    )


def register(app):
    app.add_handler(MessageHandler(RX(r"^[+]монеты\b"), add_coins))
    app.add_handler(MessageHandler(RX(r"^[+]кредит\b"), take_credit))
    app.add_handler(MessageHandler(RX(r"^[-]кредит\b"), repay_credit))
