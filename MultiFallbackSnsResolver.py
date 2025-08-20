import asyncio
import aiohttp
import time
import hashlib
import logging
from typing import Dict, Any, Optional, List

try:
    import aiosqlite
    SQLITE_AVAILABLE = True
except ImportError:
    SQLITE_AVAILABLE = False

from solders.pubkey import Pubkey
from solders.system_program import SYS_PROGRAM_ID

# SNS program ID (correct one)
SNS_PROGRAM_ID = Pubkey.from_string("namesLPneVptA9Z5rqUDD9tMTWEJwofgaYwp8cawRkX")
ROOT_DOMAIN_ACCOUNT = Pubkey.from_string("58PwtjSDuFHuUkYjkwrj2Abf8AX9oU5P9Wq5iTn33LPH")

logger = logging.getLogger(__name__)

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
                sleep_time = (1.0 - self.allowance) * (self.per / self.rate)
                await asyncio.sleep(sleep_time)
                self.allowance = 0
            else:
                self.allowance -= 1.0

class SNSResolver:
    def __init__(
        self,
        rpc_endpoint: str = "https://api.mainnet-beta.solana.com",
        solanafm_api: str = "https://api.solana.fm/v0",
        cache_db: str = "sns_cache.db",
        global_rate: int = 10,
        global_per: float = 1.0,
        cache_ttl: int = 3600,
        timeout: int = 15,
        max_retries: int = 3
    ):
        self.rpc_endpoint = rpc_endpoint
        self.solanafm_api = solanafm_api
        self.cache_db = cache_db
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.max_retries = max_retries
        self.session: Optional[aiohttp.ClientSession] = None

        self.global_limiter = RateLimiter(global_rate, global_per)
        
        # Track API health
        self.api_stats = {
            'rpc': {'calls': 0, 'successes': 0, 'total_time': 0.0},
            'solanafm': {'calls': 0, 'successes': 0, 'total_time': 0.0}
        }

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        self.session = aiohttp.ClientSession(timeout=timeout)
        if SQLITE_AVAILABLE:
            await self._init_cache()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.session:
            await self.session.close()

    async def _init_cache(self):
        """Initialize SQLite cache with TTL support."""
        async with aiosqlite.connect(self.cache_db) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    expiry INTEGER
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_expiry ON cache(expiry)")
            await db.commit()
            
            # Clean up expired entries
            now = int(time.time())
            await db.execute("DELETE FROM cache WHERE expiry < ?", (now,))
            await db.commit()

    def _make_cache_key(self, prefix: str, identifier: str) -> str:
        """Create cache key, hashing long identifiers."""
        if len(identifier) > 100:
            identifier = hashlib.sha256(identifier.encode()).hexdigest()[:32]
        return f"{prefix}:{identifier}"

    async def _cache_get(self, key: str) -> Optional[str]:
        if not SQLITE_AVAILABLE:
            return None
        
        try:
            async with aiosqlite.connect(self.cache_db) as db:
                now = int(time.time())
                async with db.execute("SELECT value FROM cache WHERE key = ? AND expiry > ?", (key, now)) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else None
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None

    async def _cache_set(self, key: str, value: str):
        if not SQLITE_AVAILABLE:
            return
        
        try:
            expiry = int(time.time()) + self.cache_ttl
            async with aiosqlite.connect(self.cache_db) as db:
                await db.execute("REPLACE INTO cache (key, value, expiry) VALUES (?, ?, ?)", 
                                (key, value, expiry))
                await db.commit()
        except Exception as e:
            logger.error(f"Cache set error: {e}")

    def _record_api_call(self, api_name: str, success: bool, duration: float):
        """Track API performance."""
        stats = self.api_stats[api_name]
        stats['calls'] += 1
        stats['total_time'] += duration
        if success:
            stats['successes'] += 1

    async def _throttled_request(self, method: str, url: str, api_name: str = 'unknown', **kwargs) -> Optional[Dict[str, Any]]:
        """Make throttled request with retry logic and stats tracking."""
        await self.global_limiter.acquire()
        
        start_time = time.time()
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                async with self.session.request(method, url, **kwargs) as resp:
                    duration = time.time() - start_time
                    
                    if resp.status == 200:
                        result = await resp.json()
                        self._record_api_call(api_name, True, duration)
                        return result
                    elif resp.status == 404:
                        # 404 is valid "not found" response
                        self._record_api_call(api_name, True, duration)
                        return None
                    else:
                        text = await resp.text()
                        error = f"HTTP {resp.status}: {text[:200]}"
                        logger.warning(f"{api_name} API returned {resp.status}: {text[:100]}")
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                            message=error
                        )
                        
            except Exception as e:
                last_exception = e
                if attempt == self.max_retries - 1:
                    duration = time.time() - start_time
                    self._record_api_call(api_name, False, duration)
                    logger.error(f"{api_name} request failed after {self.max_retries} attempts: {e}")
                    break
                    
                # Exponential backoff
                delay = (2 ** attempt) * 0.5
                logger.debug(f"{api_name} attempt {attempt + 1} failed: {e}, retrying in {delay}s")
                await asyncio.sleep(delay)
        
        return None

    def _derive_name_account(self, name: str) -> Pubkey:
        """Derive SNS name account PDA (proper implementation)."""
        # Remove .sol if present
        if name.endswith('.sol'):
            name = name[:-4]
            
        # Handle subdomains properly
        labels = name.split('.')
        parent = ROOT_DOMAIN_ACCOUNT
        
        # Process labels from right to left (parent to child)
        for i in range(len(labels) - 1, -1, -1):
            label = labels[i]
            hashed = hashlib.sha256(label.encode()).digest()
            name_account, _ = Pubkey.find_program_address([hashed, bytes(32), bytes(parent)], SNS_PROGRAM_ID)
            parent = name_account
            
        return parent

    # ------------------------------
    # .sol -> wallet (PDA computation + RPC)
    # ------------------------------
    async def resolve_name(self, name: str) -> Optional[str]:
        """Resolve a .sol domain to wallet address using proper SNS PDA computation."""
        if not name:
            return None
            
        # Normalize domain
        domain = name.strip().lower()
        if not domain.endswith('.sol'):
            domain = domain + '.sol'
        
        cache_key = self._make_cache_key("name", domain)
        cached = await self._cache_get(cache_key)
        if cached:
            logger.debug(f"Cache hit for domain resolution: {domain} -> {cached}")
            return cached

        try:
            # Compute proper SNS PDA
            pda = self._derive_name_account(domain)
            logger.debug(f"Derived PDA {pda} for domain {domain}")

            # Query account info using RPC
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [str(pda), {"encoding": "base64"}]
            }
            
            data = await self._throttled_request("POST", self.rpc_endpoint, api_name='rpc', json=payload)
            
            if data and data.get("result") and data["result"].get("value"):
                account_data = data["result"]["value"]["data"]
                if isinstance(account_data, list) and len(account_data) > 0:
                    # Parse SNS registry data to get owner
                    import base64
                    try:
                        decoded = base64.b64decode(account_data[0])
                        if len(decoded) >= 64:
                            # Owner is at bytes 32-64 in SNS registry
                            owner_bytes = decoded[32:64]
                            owner = str(Pubkey(owner_bytes))
                            
                            await self._cache_set(cache_key, owner)
                            logger.info(f"Resolved {domain} to {owner}")
                            return owner
                    except Exception as e:
                        logger.error(f"Failed to parse SNS account data for {domain}: {e}")
            
            logger.debug(f"No account data found for domain {domain}")
            return None
            
        except Exception as e:
            logger.error(f"Error resolving domain {domain}: {e}")
            return None

    # ------------------------------
    # wallet -> .sol (reverse lookup via solana.fm)
    # ------------------------------
    async def reverse_lookup(self, wallet: str) -> Optional[str]:
        """Reverse lookup wallet to .sol domain using Solana.fm."""
        if not wallet:
            return None
            
        cache_key = self._make_cache_key("addr", wallet)
        cached = await self._cache_get(cache_key)
        if cached:
            logger.debug(f"Cache hit for reverse lookup: {wallet} -> {cached}")
            return cached

        try:
            url = f"{self.solanafm_api}/domains/{wallet}"
            data = await self._throttled_request("GET", url, api_name='solanafm')
            
            domain = None
            if data and isinstance(data, dict) and wallet in data:
                domains_info = data[wallet].get("domains", [])
                if domains_info and isinstance(domains_info, list):
                    # Take first domain if multiple exist
                    first_domain = domains_info[0]
                    if isinstance(first_domain, dict) and "name" in first_domain:
                        domain = first_domain["name"]
                        if domain and not domain.endswith('.sol'):
                            domain = domain + '.sol'

            if domain:
                await self._cache_set(cache_key, domain)
                logger.info(f"Reverse lookup resolved {wallet} to {domain}")
                return domain
            else:
                logger.debug(f"No domain found for wallet {wallet}")
                return None
                
        except Exception as e:
            logger.error(f"Error in reverse lookup for {wallet}: {e}")
            return None

    async def batch_resolve_names(self, names: List[str], concurrency: int = 5) -> Dict[str, Optional[str]]:
        """Batch resolve multiple domain names."""
        semaphore = asyncio.Semaphore(concurrency)
        results = {}

        async def worker(name):
            async with semaphore:
                results[name] = await self.resolve_name(name)

        logger.info(f"Starting batch name resolution for {len(names)} domains")
        start_time = time.time()
        
        await asyncio.gather(*[worker(name) for name in names], return_exceptions=True)
        
        duration = time.time() - start_time
        success_count = sum(1 for v in results.values() if v is not None)
        logger.info(f"Batch resolution completed: {success_count}/{len(names)} resolved in {duration:.2f}s")
        
        return results

    async def batch_reverse_lookup(self, wallets: List[str], concurrency: int = 5) -> Dict[str, Optional[str]]:
        """Batch reverse lookup multiple wallet addresses."""
        semaphore = asyncio.Semaphore(concurrency)
        results = {}

        async def worker(wallet):
            async with semaphore:
                results[wallet] = await self.reverse_lookup(wallet)

        logger.info(f"Starting batch reverse lookup for {len(wallets)} wallets")
        start_time = time.time()
        
        await asyncio.gather(*[worker(wallet) for wallet in wallets], return_exceptions=True)
        
        duration = time.time() - start_time
        success_count = sum(1 for v in results.values() if v is not None)
        logger.info(f"Batch reverse lookup completed: {success_count}/{len(wallets)} resolved in {duration:.2f}s")
        
        return results

    def get_api_stats(self) -> Dict[str, Dict]:
        """Get current API performance statistics."""
        stats = {}
        for api, data in self.api_stats.items():
            if data['calls'] > 0:
                success_rate = data['successes'] / data['calls']
                avg_time = data['total_time'] / data['calls']
                stats[api] = {
                    'calls': data['calls'],
                    'successes': data['successes'],
                    'success_rate': f"{success_rate:.2%}",
                    'avg_response_time': f"{avg_time:.3f}s"
                }
            else:
                stats[api] = {
                    'calls': 0,
                    'successes': 0,
                    'success_rate': 'No data',
                    'avg_response_time': 'No data'
                }
        return stats

    async def health_check(self) -> Dict[str, bool]:
        """Test connectivity to RPC and Solana.fm."""
        health = {}
        
        # Test RPC
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
            await asyncio.wait_for(
                self._throttled_request("POST", self.rpc_endpoint, api_name='rpc', json=payload), 
                timeout=5
            )
            health['rpc'] = True
            logger.info("RPC health check: OK")
        except Exception as e:
            health['rpc'] = False
            logger.warning(f"RPC health check failed: {e}")
        
        # Test Solana.fm
        try:
            test_url = f"{self.solanafm_api}/domains/11111111111111111111111111111111"  # Invalid wallet for testing
            await asyncio.wait_for(
                self._throttled_request("GET", test_url, api_name='solanafm'),
                timeout=5
            )
            health['solanafm'] = True
            logger.info("Solana.fm health check: OK")
        except Exception as e:
            health['solanafm'] = False
            logger.warning(f"Solana.fm health check failed: {e}")
            
        return health

# Usage example:
# async with SNSResolver() as resolver:
#     wallet = await resolver.resolve_name("example.sol")
#     domain = await resolver.reverse_lookup("wallet_address_here")
#     print(f"Domain: example.sol -> Wallet: {wallet}")
#     print(f"Wallet: wallet_address_here -> Domain: {domain}")
