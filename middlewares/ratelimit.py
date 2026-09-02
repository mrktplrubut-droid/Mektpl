import time
from collections import defaultdict, deque
from aiogram import BaseMiddleware

class RateLimitMiddleware(BaseMiddleware):
    """Small per-user guard against accidental callback/message spam.
    It is deliberately conservative; it does not block normal typing/upload flows."""
    def __init__(self, interval=0.35, burst=8):
        self.interval = interval
        self.burst = burst
        self.last = {}
        self.events = defaultdict(deque)

    async def __call__(self, handler, event, data):
        user = getattr(getattr(event, 'from_user', None), 'id', None)
        if not user:
            return await handler(event, data)
        now = time.monotonic()
        q = self.events[user]
        while q and now - q[0] > 2.0:
            q.popleft()
        last = self.last.get(user, 0.0)
        if now - last < self.interval and len(q) >= self.burst:
            try:
                await event.answer('⏳ Terlalu cepat. Tunggu sebentar lalu coba lagi.', show_alert=False)
            except Exception:
                pass
            return None
        self.last[user] = now
        q.append(now)
        return await handler(event, data)
