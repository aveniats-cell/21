import logging
from typing import Optional

from telethon import TelegramClient
from telethon.sessions import StringSession

logger = logging.getLogger(__name__)


class Resolver:
    """Обёртка над Telethon-клиентом для поиска пользователей по @username.

    PTB (Bot API) не умеет искать юзеров, которых бот никогда не видел.
    Telethon с user-сессией умеет — используем его только как справочник,
    без регистрации хэндлеров.
    """

    def __init__(self, api_id: int, api_hash: str, session_string: str):
        self._enabled = bool(api_id and api_hash and session_string)
        self.client: Optional[TelegramClient] = None
        if self._enabled:
            self.client = TelegramClient(
                StringSession(session_string), api_id, api_hash
            )

    @property
    def enabled(self) -> bool:
        return self._enabled and self.client is not None

    async def start(self) -> None:
        if not self._enabled:
            logger.warning("Resolver: MTProto отключён (нет API_ID/API_HASH/STRING_SESSION).")
            return
        try:
            await self.client.start()
            me = await self.client.get_me()
            logger.info("Resolver: MTProto-клиент запущен как @%s (id=%s)", me.username, me.id)
        except Exception as e:
            logger.error("Resolver: не удалось запустить MTProto: %s", e)
            self._enabled = False

    async def stop(self) -> None:
        if self._enabled and self.client:
            try:
                await self.client.disconnect()
                logger.info("Resolver: MTProto-клиент остановлен.")
            except Exception:
                pass

    async def resolve(self, username: str):
        """Возвращает объект User/Channel по @username или None."""
        if not self.enabled or not username:
            return None
        clean = username.lstrip("@").strip()
        if not clean:
            return None
        try:
            return await self.client.get_entity(f"@{clean}")
        except Exception as e:
            logger.debug("Resolver: не найден @%s (%s)", clean, e)
            return None

    async def resolve_by_id(self, user_id: int):
        """Возвращает объект User/Channel по id или None."""
        if not self.enabled:
            return None
        try:
            return await self.client.get_entity(user_id)
        except Exception:
            return None

    async def get_permissions(self, chat_id: int, user_id: int):
        """Возвращает Telethon ChatPermissions или None."""
        if not self.enabled:
            return None
        try:
            return await self.client.get_permissions(chat_id, user_id)
        except Exception:
            return None


def is_bot(entity) -> bool:
    """Универсальная проверка: Telethon User → .bot, PTB Chat → .is_bot."""
    if entity is None:
        return False
    if hasattr(entity, "bot"):
        return bool(entity.bot)
    return bool(getattr(entity, "is_bot", False))
