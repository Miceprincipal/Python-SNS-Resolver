# multi_fallback_sns_resolver.py
# Hardened async multi-provider SNS resolver with retries, caching, and fallbacks
# GitHub-ready version

import asyncio
import aiohttp
import time
import hashlib
import logging
from typing import Optional, List, Dict

try:
    import aiosqlite
    SQLITE_AVAILABLE = True
except ImportError:
    SQLITE_AVAILABLE = False

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class RateLimiter:
    """Async token-bucket rate limiter."""
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


class MultiFallbackSnsResolver:
    """
    Multi-provider Solana Name Service (SNS) resolver with caching,
    rate-limiting, and parallel fallback support.
    """

    def __init__(
        self,
        helius_api_key: Optional[str] = None,
        shyft_api_key: Optional[str] = None,
        solanafm_enabled: bool = True,
        sqlite_cache_path: Optional[str] = "sns_cache.db",
        parallel_fallbacks: bool = True,
        cache_ttl: int = 3600,
        request_timeout: int = 15,
        max_retries: int = 3,
    ):
        self.helius_api_key = helius_api_key
        self.shyft_api_key = shyft_api_key
        self.solanafm_enabled = solanafm_enabled
        self.parallel_fallbacks = parallel_fallbacks
        self.cache_ttl = cache_ttl
        self.request_timeout = request_timeout
        self.max_retries = max_retries

        self.session: Optional[aiohttp.ClientSession] = None
        self.sqlite_cache_path = sqlite_cache_path
        self.memory_cache: Dict[str, tuple] = {}
        self.db = None

        # Rate limiters per provider
        self.rate_limiters = {
            "helius": RateLimiter(5, 1.0),
            "shyft": RateLimiter(5, 1.0),
            "solanafm": RateLimiter(5, 1.0),
        }

    async def init(self):
        """Initialize aiohttp session and SQLite cache."""
        timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        self.session = aiohttp.ClientSession(timeout=timeout)

        if SQLITE_AVAILABLE and self.sqlite_cache_path:
            self.db = await aiosqlite.connect(self.sqlite_cache_path)
            await self.db.execute(
                "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, expiry INTEGER)"
            )
            await self.db.commit()
            logger.info(f"Initialized SQLite cache at {self.sqlite_cache_path}")

    async def close(self):
        """Clean up async resources."""
        if self.session:
            await self.session.close()
        if self.db:
            await self.db.close()
        logger.info("Closed SNS resolver resources")

    # -----------------------------
    # Caching
    # -----------------------------
    async def _cache_get(self, key: str) -> Optional[str]:
        now = int(time.time())
        # Memory cache
        if key in self.memory_cache:
            value, expiry = self.memory_cache[key]
            if expiry > now:
                return value
            del self.memory_cache[key]

        # SQLite cache
        if self.db:
            async with self.db.execute(
                "SELECT value, expiry FROM cache WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    value, expiry = row
                    if expiry > now:
                        self.memory_cache[key] = (value, expiry)
                        return value
                    else:
                        await self.db.execute("DELETE FROM cache WHERE key=?", (key,))
                        await self.db.commit()
        return None

    async def _cache_set(self, key: str, value: str):
        expiry = int(time.time()) + self.cache_ttl
        self.memory_cache[key] = (value, expiry)
        if self.db:
            await self.db.execute(
                "INSERT OR REPLACE INTO cache (key, value, expiry) VALUES (?, ?, ?)",
                (key, value, expiry),
            )
            await self.db.commit()

    def _normalize_domain(self, domain: str) -> str:
        if domain and not domain.endswith(".sol"):
            return domain + ".sol"
        return domain

    # -----------------------------
    # HTTP Requests
    # -----------------------------
    async def _retry_request(self, provider: str, method: str, url: str, **kwargs):
        """HTTP request with retries and provider rate limiting."""
        limiter = self.rate_limiters.get(provider)
        if limiter:
            await limiter.acquire()

        delay = 0.5
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                async with self.session.request(method, url, **kwargs) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 404:
                        return None
                    else:
                        text = await resp.text()
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                            message=f"HTTP {resp.status}: {text[:200]}",
                        )
            except Exception as e:
                last_exception = e
                if attempt == self.max_retries - 1:
                    logger.error(f"{provider} request failed {url}: {e}")
                    raise
                await asyncio.sleep(delay)
                delay *= 2
        raise last_exception

    # -----------------------------
    # Reverse Lookup (wallet -> domain)
    # -----------------------------
    async def reverse_lookup(self, wallet: str) -> Optional[str]:
        cache_key = f"addr:{wallet}"
        cached = await self._cache_get(cache_key)
        if cached:
            return cached

        tasks = []

        if self.helius_api_key:
            tasks.append(self._reverse_helius(wallet))
        if self.shyft_api_key:
            tasks.append(self._reverse_shyft(wallet))
        if self.solanafm_enabled:
            tasks.append(self._reverse_solanafm(wallet))

        results = []
        if self.parallel_fallbacks:
            completed, pending = await asyncio.wait(
                [asyncio.create_task(t) for t in tasks],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in completed:
                try:
                    res = await task
                    if res:
                        await self._cache_set(cache_key, res)
                        for p in pending:
                            p.cancel()
                        return res
                except Exception:
                    continue
        else:
            for task in tasks:
                try:
                    res = await task
                    if res:
                        await self._cache_set(cache_key, res)
                        return res
                except Exception:
                    continue

        await self._cache_set(cache_key, "")
        return None

    # -----------------------------
    # Provider Implementations
    # -----------------------------
    async def _reverse_helius(self, wallet: str) -> Optional[str]:
        url = f"https://rpc.helius.xyz/?api-key={self.helius_api_key}"
        payload = {"jsonrpc": "2.0", "id": "sns-reverse", "method": "getNameOwner", "params": [wallet]}
        data = await self._retry_request("helius", "POST", url, json=payload)
        if data and "result" in data:
            domain = data["result"].get("domain")
            return self._normalize_domain(domain) if domain else None
        return None

    async def _reverse_shyft(self, wallet: str) -> Optional[str]:
        url = f"https://api.shyft.to/sol/v1/names/reverse/{wallet}?network=mainnet-beta"
        headers = {"x-api-key": self.shyft_api_key}
        data = await self._retry_request("shyft", "GET", url, headers=headers)
        if data and "result" in data:
            domain = data["result"].get("domain")
            return self._normalize_domain(domain) if domain else None
        return None

    async def _reverse_solanafm(self, wallet: str) -> Optional[str]:
        url = f"https://api.solana.fm/v1/sns?wallet={wallet}"
        data = await self._retry_request("solanafm", "GET", url)
        if data and "domain" in data:
            return self._normalize_domain(data["domain"])
        return None
