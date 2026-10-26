"""Halloween 2026 «Bloody Moon» — всё обновление в одном файле.

Чтобы выковырить:
  1. Удали `import halloween` и `halloween.register(app, state)` из main.py
  2. Удали блок "HALLOWEEN 2026" в конце db.py (опционально)
  3. Удали строки с тыквами в profile.py (опционально)
  Всё. Старый бот работает как раньше.
"""

import asyncio
import logging
import random
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

import db

logger = logging.getLogger(__name__)

# ==================== КОНСТАНТЫ ====================

COMPONENTS = {
    "paper": {"name": "📜 Бумага Проклятья", "rarity": "rare"},
    "ink":   {"name": "🖋 Чернила Джека Потрошителя", "rarity": "rare"},
    "seal":  {"name": "🔴 Печать Кровавого Совета", "rarity": "rare"},
    "stone": {"name": "💎 Камень Завета", "rarity": "legendary"},
}

JUNK = {
    "bone":        {"name": "🦴 Кость", "price": 0.2},
    "web":         {"name": "🕸 Паутина", "price": 0.2},
    "needle":      {"name": "🪡 Иголка", "price": 0.3},
    "thread":      {"name": "🧵 Нить", "price": 0.3},
    "splinter":    {"name": "🪵 Щепка", "price": 0.2},
    "paper_scrap": {"name": "📄 Обрывок бумаги", "price": 0.3},
    "candle":      {"name": "🕯 Огарок свечи", "price": 0.5},
    "mirror":      {"name": "🪞 Осколок зеркала", "price": 0.7},
    "key":         {"name": "🗝 Ржавый ключ", "price": 1.0},
    "skull":       {"name": "💀 Черепок", "price": 1.5},
    "blood":       {"name": "🩸 Пятно крови", "price": 1.5},
    "spider":      {"name": "🕷 Паук (живой)", "price": 2.0},
    "eye":         {"name": "👁 Стеклянный глаз", "price": 3.0},
    "bat_wing":    {"name": "🦇 Крыло летучей мыши", "price": 3.0},
    "stone_shard": {"name": "💎 Осколок Камня", "price": 5.0},
}

JUNK_WEIGHTS = {
    "bone": 20, "web": 20, "needle": 15, "thread": 15, "splinter": 15,
    "paper_scrap": 10, "candle": 8, "mirror": 6, "key": 5,
    "skull": 3, "blood": 3, "spider": 2, "eye": 1, "bat_wing": 1,
    "stone_shard": 1,
}

CHESTS = {
    "wooden": {
        "name": "🪵 Wooden Chest",
        "price": 3.0,
        "drop": {"junk": 0.92, "1_component": 0.05, "2_components": 0.02, "empty": 0.01},
    },
    "copper": {
        "name": "🥉 Copper Chest",
        "price": 8.0,
        "drop": {"junk": 0.75, "1_component": 0.15, "2_components": 0.08, "3_components": 0.02},
    },
    "bloody": {
        "name": "🩸 Bloody Metal Chest",
        "price": 15.0,
        "drop": {"junk": 0.55, "1_component": 0.25, "2_components": 0.12,
                 "3_components": 0.06, "stone": 0.02},
    },
}

ENERGY_BAR_PRICE = 2.0
CLOVER_PRICE = 5.0

MINING_DROP = {"stone": 0.08, "seal": 0.12, "ink": 0.15, "paper": 0.15, "junk": 0.50}
PITY = {"component_bonus": 0.02, "stone_bonus": 0.01,
        "guarantee_component": 11, "guarantee_stone": 21}

JUNK_EXCHANGE = {
    "energy_bar": {"cost": 20, "gives": "energy_bar"},
    "copper":     {"cost": 50, "gives": "copper_chest"},
    "bloody":     {"cost": 100, "gives": "bloody_chest"},
    "stone":      {"cost": 5, "gives": "stone"},
}

AWARD_ID = "bloody_moon_2026"
AWARD_NAME = 'Award Halloween 2026 "Bloody Moon"'
AWARD_BONUS_PUMPKINS = 100.0

PUMPKIN_PER_MSG = 0.5
PUMPKIN_DAILY_BONUS = 1.0

# Регулярка для команды: и кириллица, и латиница
HALLOWEEN_CMD_RE = re.compile(r"^/?(хэллоуин|halloween)$", re.IGNORECASE)


# ==================== ВНУТРЕННИЕ ХЕЛПЕРЫ ====================

def _weighted_junk() -> str:
    ids = list(JUNK_WEIGHTS.keys())
    weights = list(JUNK_WEIGHTS.values())
    return random.choices(ids, weights=weights, k=1)[0]


def _random_component() -> str:
    return random.choice(["paper", "ink", "seal"])


def _open_chest(chest_id: str) -> list:
    chest = CHESTS[chest_id]
    roll = random.random()
    cumulative = 0.0
    result = []

    if "stone" in chest["drop"]:
        cumulative += chest["drop"]["stone"]
        if roll < cumulative:
            return [("stone", 1)]

    cumulative += chest["drop"].get("junk", 0)
    if roll < cumulative:
        return [(_weighted_junk(), 1)]

    for key, count in [("1_component", 1), ("2_components", 2), ("3_components", 3)]:
        if key in chest["drop"]:
            cumulative += chest["drop"][key]
            if roll < cumulative:
                for _ in range(count):
                    result.append((_random_component(), 1))
                return result

    return []


# ==================== РЕГИСТРАЦИЯ ====================

def register(app, state: dict) -> None:

    # ---------------- Трекер сообщений ----------------

    async def track_pumpkins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        user = update.effective_user
        if not msg or not msg.text or msg.text.startswith("/"):
            return
        if not user or user.is_bot:
            return
        try:
            db.ensure_profile(user.id, user.username, user.first_name)
            db.hw_add_pumpkins(user.id, PUMPKIN_PER_MSG)
            if db.hw_claim_daily_bonus(user.id):
                db.hw_add_pumpkins(user.id, PUMPKIN_DAILY_BONUS)
        except Exception as e:
            logger.error("Halloween track error: %s", e)

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, track_pumpkins),
        group=2,
    )

    # ---------------- Главное меню ----------------

    def main_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Магазин", callback_data="hw|shop"),
             InlineKeyboardButton("🎒 Инвентарь", callback_data="hw|inv")],
            [InlineKeyboardButton("⛏ Добыть", callback_data="hw|mine"),
             InlineKeyboardButton("🔮 Слияние", callback_data="hw|fusion")],
            [InlineKeyboardButton("🗑 Продать мусор", callback_data="hw|selljunk")],
            [InlineKeyboardButton("🔄 Обмен мусора", callback_data="hw|exchange_menu")],
        ])

    async def _build_main_text(user_id: int) -> str:
        bal = db.hw_get_pumpkins(user_id)
        inv = db.hw_get_inventory(user_id)
        comps = {k: inv.get(k, 0) for k in COMPONENTS}
        has_award = db.hw_has_award(user_id, AWARD_ID)

        text = (
            f"🎃 <b>Halloween 2026 «Bloody Moon»</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎃 Тыквы: <b>{bal:.2f}</b>\n\n"
            f"📦 <b>Компоненты:</b>\n"
            f"  📜 Бумага: {comps['paper']}\n"
            f"  🖋 Чернила: {comps['ink']}\n"
            f"  🔴 Печать: {comps['seal']}\n"
            f"  💎 Камень: {comps['stone']}\n\n"
        )
        if has_award:
            text += f"🏆 <b>{AWARD_NAME}</b> — получена!\n"
        else:
            text += "🎯 Собери все 4 компонента и нажми «Слияние»."
        return text

    async def halloween_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not user:
            return
        text = await _build_main_text(user.id)
        await update.effective_message.reply_text(
            text, reply_markup=main_keyboard(), parse_mode=ParseMode.HTML,
        )

    app.add_handler(
        MessageHandler(filters.Regex(HALLOWEEN_CMD_RE), halloween_cmd)
    )

    # ---------------- Callback-роутер ----------------

    async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        user = q.from_user
        data = q.data or ""

        if data == "hw|shop":
            await _show_shop(q)
        elif data == "hw|inv":
            await _show_inventory(q, user.id)
        elif data == "hw|mine":
            await _start_mining(q, context, user.id)
        elif data == "hw|fusion":
            await _try_fusion(q, user.id)
        elif data == "hw|selljunk":
            await _sell_all_junk(q, user.id)
        elif data == "hw|exchange_menu":
            await _show_exchange_menu(q)
        elif data == "hw|back":
            await _show_main(q, user.id)
        elif data.startswith("hw|buy|"):
            await _buy_item(q, user.id, data.split("|")[2])
        elif data.startswith("hw|exch|"):
            await _exchange_junk(q, user.id, data.split("|")[2])
        else:
            await q.answer()

    app.add_handler(CallbackQueryHandler(callback, pattern=r"^hw\|"))

    # ---------------- Экраны ----------------

    async def _show_main(q, user_id: int) -> None:
        text = await _build_main_text(user_id)
        await q.edit_message_text(
            text, reply_markup=main_keyboard(), parse_mode=ParseMode.HTML,
        )
        await q.answer()

    async def _show_shop(q) -> None:
        bal = db.hw_get_pumpkins(q.from_user.id)
        kb = [
            [InlineKeyboardButton(f"🪵 Wooden — {CHESTS['wooden']['price']:.0f} 🎃",
                                  callback_data="hw|buy|wooden")],
            [InlineKeyboardButton(f"🥉 Copper — {CHESTS['copper']['price']:.0f} 🎃",
                                  callback_data="hw|buy|copper")],
            [InlineKeyboardButton(f"🩸 Bloody Metal — {CHESTS['bloody']['price']:.0f} 🎃",
                                  callback_data="hw|buy|bloody")],
            [InlineKeyboardButton(f"⚡ Energy Bar — {ENERGY_BAR_PRICE:.0f} 🎃",
                                  callback_data="hw|buy|energy_bar")],
            [InlineKeyboardButton(f"🍀 Клевер удачи — {CLOVER_PRICE:.0f} 🎃",
                                  callback_data="hw|buy|clover")],
            [InlineKeyboardButton("🔙 Назад", callback_data="hw|back")],
        ]
        await q.edit_message_text(
            f"🛒 <b>Магазин</b>\nБаланс: <b>{bal:.2f} 🎃</b>\n\n"
            f"🪵 Wooden — 92% мусор, 5% компонент\n"
            f"🥉 Copper — 75% мусор, 25% компонент\n"
            f"🩸 Bloody Metal — 55% мусор, 43% компонент, 2% камень\n"
            f"⚡ Energy Bar — 1 попытка добычи\n"
            f"🍀 Клевер — +5% к следующей добыче",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML,
        )
        await q.answer()

    async def _show_inventory(q, user_id: int) -> None:
        inv = db.hw_get_inventory(user_id)
        lines = ["🎒 <b>Инвентарь</b>\n"]
        for k, meta in COMPONENTS.items():
            n = inv.get(k, 0)
            if n:
                lines.append(f"{meta['name']}: <b>{n}</b>")
        if inv.get("energy_bar"):
            lines.append(f"⚡ Energy Bar: <b>{inv['energy_bar']}</b>")
        junk_lines = []
        for k, meta in JUNK.items():
            n = inv.get(k, 0)
            if n:
                junk_lines.append(f"  {meta['name']} ×{n}")
        if junk_lines:
            lines.append("\n🗑 <b>Мусор:</b>")
            lines.extend(junk_lines)
        if len(lines) == 1:
            lines.append("Пусто.")
        lines.append("")
        await q.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="hw|back")
            ]]),
            parse_mode=ParseMode.HTML,
        )
        await q.answer()

    async def _show_exchange_menu(q) -> None:
        kb = [
            [InlineKeyboardButton("⚡ 20 мусора → Energy Bar",
                                  callback_data="hw|exch|energy_bar")],
            [InlineKeyboardButton("🥉 50 мусора → Copper",
                                  callback_data="hw|exch|copper")],
            [InlineKeyboardButton("🩸 100 мусора → Bloody Metal",
                                  callback_data="hw|exch|bloody")],
            [InlineKeyboardButton("💎 5 Осколков → Камень Завета",
                                  callback_data="hw|exch|stone")],
            [InlineKeyboardButton("🔙 Назад", callback_data="hw|back")],
        ]
        await q.edit_message_text(
            "🔄 <b>Обмен мусора</b>\n\nВыбери, на что обменять:",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML,
        )
        await q.answer()

    # ---------------- Покупка ----------------

    async def _buy_item(q, user_id: int, item: str) -> None:
        if item in CHESTS:
            price = CHESTS[item]["price"]
            if not db.hw_spend_pumpkins(user_id, price):
                await q.answer("❌ Недостаточно тыкв.", show_alert=True)
                return
            loot = _open_chest(item)
            lines = [f"📦 <b>{CHESTS[item]['name']} открыт!</b>\n"]
            if not loot:
                lines.append("💨 Пусто. В следующий раз повезёт.")
            else:
                for item_id, amount in loot:
                    if item_id in COMPONENTS:
                        db.hw_add_inventory(user_id, item_id, amount)
                        lines.append(f"✨ {COMPONENTS[item_id]['name']} ×{amount}")
                    else:
                        db.hw_add_inventory(user_id, item_id, amount)
                        lines.append(f"🗑 {JUNK[item_id]['name']} ×{amount}")
            await q.edit_message_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🛒 В магазин", callback_data="hw|shop"),
                    InlineKeyboardButton("🎒 Инвентарь", callback_data="hw|inv"),
                ]]),
                parse_mode=ParseMode.HTML,
            )
            await q.answer()
        elif item == "energy_bar":
            if not db.hw_spend_pumpkins(user_id, ENERGY_BAR_PRICE):
                await q.answer("❌ Недостаточно тыкв.", show_alert=True)
                return
            db.hw_add_inventory(user_id, "energy_bar", 1)
            await q.answer("⚡ Energy Bar куплен!", show_alert=True)
        elif item == "clover":
            if not db.hw_spend_pumpkins(user_id, CLOVER_PRICE):
                await q.answer("❌ Недостаточно тыкв.", show_alert=True)
                return
            db.hw_set_luck_buff(user_id, 0.05)
            await q.answer("🍀 +5% к следующей добыче!", show_alert=True)
        else:
            await q.answer("Неизвестный товар.", show_alert=True)

    # ---------------- Добыча ----------------

    async def _start_mining(q, context, user_id: int) -> None:
        inv = db.hw_get_inventory(user_id)
        if inv.get("energy_bar", 0) < 1:
            await q.answer("❌ Нет Energy Bar. Купи в магазине (2 🎃).", show_alert=True)
            return

        db.hw_remove_inventory(user_id, "energy_bar", 1)
        msg = await q.edit_message_text(
            "⛏️ <b>Добыча...</b>\n[░░░░░░░░░░] 0%", parse_mode=ParseMode.HTML,
        )
        await q.answer()

        for pct in (20, 40, 60, 80, 100):
            await asyncio.sleep(1.2)
            filled = pct // 10
            bar = "█" * filled + "░" * (10 - filled)
            try:
                await msg.edit_text(
                    f"⛏️ <b>Добыча...</b>\n[{bar}] {pct}%",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

        stats = db.hw_get_mining_stats(user_id)
        fails = stats["fails_streak"]
        luck = db.hw_get_luck_buff(user_id)

        stone_chance = MINING_DROP["stone"] + fails * PITY["stone_bonus"] + luck
        comp_chance = (
            MINING_DROP["seal"] + MINING_DROP["ink"] + MINING_DROP["paper"]
            + fails * PITY["component_bonus"]
        )

        if fails >= PITY["guarantee_stone"] - 1:
            result = "stone"
        elif fails >= PITY["guarantee_component"] - 1:
            result = random.choice(["seal", "ink", "paper"])
        else:
            roll = random.random()
            if roll < stone_chance:
                result = "stone"
            elif roll < stone_chance + comp_chance:
                result = random.choice(["seal", "ink", "paper"])
            else:
                result = None

        db.hw_consume_luck_buff(user_id)

        if result:
            db.hw_add_inventory(user_id, result, 1)
            db.hw_update_mining_stats(user_id, success=True)
            text = f"✨ <b>Находка!</b>\n{COMPONENTS[result]['name']} +1"
        else:
            junk_id = _weighted_junk()
            db.hw_add_inventory(user_id, junk_id, 1)
            db.hw_update_mining_stats(user_id, success=False)
            text = f"❌ Пусто.\nНо ты нашёл: {JUNK[junk_id]['name']}"

        try:
            await msg.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⛏ Ещё", callback_data="hw|mine"),
                    InlineKeyboardButton("🔙 Меню", callback_data="hw|back"),
                ]]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            await context.bot.send_message(
                q.message.chat_id, text, parse_mode=ParseMode.HTML,
            )

    # ---------------- Мусор ----------------

    async def _sell_all_junk(q, user_id: int) -> None:
        inv = db.hw_get_inventory(user_id)
        total = 0.0
        count = 0
        for junk_id, meta in JUNK.items():
            n = inv.get(junk_id, 0)
            if n:
                total += meta["price"] * n
                count += n
                db.hw_remove_inventory(user_id, junk_id, n)
        if count == 0:
            await q.answer("🗑 Мусора нет.", show_alert=True)
            return
        db.hw_add_pumpkins(user_id, total)
        await q.edit_message_text(
            f"💰 Продано мусора: <b>{count}</b>\nПолучено: <b>+{total:.2f} 🎃</b>",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Назад", callback_data="hw|back")
            ]]),
            parse_mode=ParseMode.HTML,
        )
        await q.answer()

    async def _exchange_junk(q, user_id: int, kind: str) -> None:
        spec = JUNK_EXCHANGE.get(kind)
        if not spec:
            await q.answer("Неизвестный обмен.", show_alert=True)
            return
        inv = db.hw_get_inventory(user_id)

        if kind == "stone":
            have = inv.get("stone_shard", 0)
            need = spec["cost"]
            if have < need:
                await q.answer(
                    f"❌ Нужно {need} Осколков Камня (у тебя {have}).",
                    show_alert=True,
                )
                return
            db.hw_remove_inventory(user_id, "stone_shard", need)
            db.hw_add_inventory(user_id, "stone", 1)
            await q.answer("💎 Камень Завета получен!", show_alert=True)
            return

        junk_total = sum(inv.get(k, 0) for k in JUNK if k != "stone_shard")
        if junk_total < spec["cost"]:
            await q.answer(
                f"❌ Нужно {spec['cost']} мусора (у тебя {junk_total}).",
                show_alert=True,
            )
            return

        remaining = spec["cost"]
        for k in JUNK:
            if k == "stone_shard":
                continue
            n = inv.get(k, 0)
            if n <= 0:
                continue
            take = min(n, remaining)
            db.hw_remove_inventory(user_id, k, take)
            remaining -= take
            if remaining <= 0:
                break

        gives = spec["gives"]
        result_msg = ""
        if gives == "energy_bar":
            db.hw_add_inventory(user_id, "energy_bar", 1)
            result_msg = "⚡ Energy Bar получен!"
        elif gives == "copper_chest":
            loot = _open_chest("copper")
            loot_lines = []
            for item_id, amt in loot:
                db.hw_add_inventory(user_id, item_id, amt)
                name = COMPONENTS.get(item_id, JUNK.get(item_id, {})).get("name", item_id)
                loot_lines.append(f"  {name} ×{amt}")
            result_msg = "🥉 Copper открыт:\n" + ("\n".join(loot_lines) if loot_lines else "  💨 пусто")
        elif gives == "bloody_chest":
            loot = _open_chest("bloody")
            loot_lines = []
            for item_id, amt in loot:
                db.hw_add_inventory(user_id, item_id, amt)
                name = COMPONENTS.get(item_id, JUNK.get(item_id, {})).get("name", item_id)
                loot_lines.append(f"  {name} ×{amt}")
            result_msg = "🩸 Bloody Metal открыт:\n" + ("\n".join(loot_lines) if loot_lines else "  💨 пусто")

        await q.answer(result_msg, show_alert=True)

    # ---------------- Слияние ----------------

    async def _try_fusion(q, user_id: int) -> None:
        if db.hw_has_award(user_id, AWARD_ID):
            await q.answer("🏆 У тебя уже есть эта награда!", show_alert=True)
            return
        inv = db.hw_get_inventory(user_id)
        missing = [k for k in COMPONENTS if inv.get(k, 0) < 1]
        if missing:
            names = ", ".join(COMPONENTS[k]["name"] for k in missing)
            await q.answer(f"❌ Не хватает: {names}", show_alert=True)
            return

        for k in COMPONENTS:
            db.hw_remove_inventory(user_id, k, 1)
        db.hw_give_award(user_id, AWARD_ID)
        db.hw_add_pumpkins(user_id, AWARD_BONUS_PUMPKINS)

        text = (
            "🩸 <b>СЛИЯНИЕ</b> 🩸\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📜 Бумага Проклятья ✦\n"
            "🖋 Чернила Джека Потрошителя ✦\n"
            "🔴 Печать Кровавого Совета ✦\n"
            "💎 Камень Завета ✦\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"✨ <b>Свиток Небес собран!</b>\n"
            f"🏆 <b>{AWARD_NAME}</b>\n"
            f"🎃 +{AWARD_BONUS_PUMPKINS:.0f} тыкв бонусом"
        )
        await q.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🎃 В меню", callback_data="hw|back")
            ]]),
            parse_mode=ParseMode.HTML,
        )
        await q.answer("🏆 Награда получена!", show_alert=True)

    logger.info("Halloween module: тыквы, магазин, добыча, слияние зарегистрированы.")
