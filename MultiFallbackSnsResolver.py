import asyncio
import aiohttp
import time
from typing import Dict, Any, Optional

try:
    import aiosqlite
    SQLITE_AVAILABLE = True
except ImportError:
    SQLITE_AVAILABLE = False


class RateLimiter:
    """Async token-bucket style limiter."""
    def __init__(self, rate: int, per: float):
        self.rate = rate
        self.per = per
        self.allowance = rate
        self.last_check = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_check
            self.last_check = now
            self.allowance += elapsed * (self.rate / self.per)

            if self.allowance > self.rate:
                self.allowance = self.rate

            if self.allowance < 1.0:
                wait_time = (1.0 - self.allowance) * (self.per / self.rate)
                await asyncio.sleep(wait_time)
                self.allowance = 0
            else:
                self.allowance -= 1.0


class SNSResolver:
    def __init__(
        self,
        helius_api_key: Optional[str] = None,
        shyft_api_key: Optional[str] = None,
        cache_db: str = "sns_cache.db",
        global_rate: int = 10,
        global_per: float = 1.0,
    ):
        self.helius_api_key = helius_api_key
        self.shyft_api_key = shyft_api_key
        self.cache_db = cache_db
        self.session: Optional[aiohttp.ClientSession] = None

        # Global limiter (across all providers)
        self.global_limiter = RateLimiter(global_rate, global_per)

        # Per-provider defaults (safe public settings)
        self.provider_limiters: Dict[str, RateLimiter] = {
            "helius": RateLimiter(5, 1.0),   # 5 rps default
            "shyft": RateLimiter(5, 1.0),    # 5 rps default
        }

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        if SQLITE_AVAILABLE:
            await self._init_cache()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.session:
            await self.session.close()

    async def _init_cache(self):
        async with aiosqlite.connect(self.cache_db) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    timestamp REAL
                )
            """)
            await db.commit()

    async def _cache_get(self, key: str) -> Optional[str]:
        if not SQLITE_AVAILABLE:
            return None
        async with aiosqlite.connect(self.cache_db) as db:
            async with db.execute("SELECT value FROM cache WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None

    async def _cache_set(self, key: str, value: str):
        if not SQLITE_AVAILABLE:
            return
        async with aiosqlite.connect(self.cache_db) as db:
            await db.execute("REPLACE INTO cache (key, value, timestamp) VALUES (?, ?, ?)", (key, value, time.time()))
            await db.commit()

    async def _throttled_request(self, provider: str, method: str, url: str, **kwargs) -> Optional[Dict[str, Any]]:
        await self.global_limiter.acquire()
        await self.provider_limiters[provider].acquire()

        async with self.session.request(method, url, **kwargs) as resp:
            if resp.status != 200:
                return None
            return await resp.json()

    async def resolve_name(self, name: str) -> Optional[str]:
        """Resolve SNS domain -> wallet address."""
        cache_key = f"name:{name}"
        cached = await self._cache_get(cache_key)
        if cached:
            return cached

        if self.helius_api_key:
            url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"
            payload = {
                "jsonrpc": "2.0",
                "id": "sns-lookup",
                "method": "getDomainKey",
                "params": [name],
            }
            data = await self._throttled_request("helius", "POST", url, json=payload)
            if data and "result" in data:
                owner = data["result"].get("owner")
                if owner:
                    await self._cache_set(cache_key, owner)
                    return owner

        if self.shyft_api_key:
            url = f"https://api.shyft.to/sol/v1/names/{name}?network=mainnet-beta"
            headers = {"x-api-key": self.shyft_api_key}
            data = await self._throttled_request("shyft", "GET", url, headers=headers)
            if data and "result" in data:
                owner = data["result"].get("owner")
                if owner:
                    await self._cache_set(cache_key, owner)
                    return owner

        return None

    async def reverse_lookup(self, address: str) -> Optional[str]:
        """Resolve wallet -> SNS domain."""
        cache_key = f"addr:{address}"
        cached = await self._cache_get(cache_key)
        if cached:
            return cached

        if self.helius_api_key:
            url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"
            payload = {
                "jsonrpc": "2.0",
                "id": "sns-reverse",
                "method": "getNameOwner",
                "params": [address],
            }
            data = await self._throttled_request("helius", "POST", url, json=payload)
            if data and "result" in data:
                name = data["result"].get("domain")
                if name:
                    await self._cache_set(cache_key, name)
                    return name

        if self.shyft_api_key:
            url = f"https://api.shyft.to/sol/v1/names/reverse/{address}?network=mainnet-beta"
            headers = {"x-api-key": self.shyft_api_key}
            data = await self._throttled_request("shyft", "GET", url, headers=headers)
            if data and "result" in data:
                name = data["result"].get("domain")
                if name:
                    await self._cache_set(cache_key, name)
                    return name

        return None
