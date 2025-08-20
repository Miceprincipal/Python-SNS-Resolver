I take almost zero credit for this as it is the result of strangling something I needed out of multiple AIs. I am art monkey not a code monkey. But I figured it might be useful to someone who doesn't want to have to wrap the node bonfida libraries even if it's a bit of a bodge solution. Unfortunately I can't offer troubleshooting but I can draw a picture of a duck look pensive if that helps. 

# Web3.bio SNS Resolver

**Python wrapper for Solana Name Service (SNS) using Web3.bio API**  

This library provides forward and reverse resolution of Solana `.sol` domains, batch operations, caching, and built-in rate limiting with retries. It is designed for reliability and optimized for Solana forensic or tracking tools.

---

## Features

- **Forward lookup**: `.sol` domain → wallet address
- **Reverse lookup**: wallet address → `.sol` domain
- **Batch resolution**: efficient handling of multiple domains or addresses
- **Caching**: optional SQLite-based cache to avoid redundant API calls
- **Rate limiting**: token-bucket limiter with burst capacity and backoff for retries
- **Error handling**: exponential backoff on timeouts or rate limits
- **Health check**: verify Web3.bio API availability

---

## Requirements

- Python 3.10+
- [`aiohttp`](https://pypi.org/project/aiohttp/)
- [`aiosqlite`](https://pypi.org/project/aiosqlite/) (optional for caching)

Install dependencies:

```bash
pip install aiohttp aiosqlite
```

Installation

Clone the repository or copy the script directly. No additional setup is required beyond installing dependencies.

Usage
Basic Example

import asyncio
from web3bio_sns_resolver import Web3BioSNSResolver

```
async def main():
    async with Web3BioSNSResolver(rate_limit=2.0, cache_ttl=3600) as resolver:
        # Forward lookup
        wallet = await resolver.resolve_name("bonfida.sol")
        print(f"bonfida.sol -> {wallet}")

        # Reverse lookup
        if wallet:
            domain = await resolver.reverse_lookup(wallet)
            print(f"{wallet} -> {domain}")

        # Batch resolution
        domains = ["bonfida.sol", "dex.sol", "solana.sol"]
        batch_results = await resolver.batch_resolve_names(domains)
        print(batch_results)

        # Batch reverse lookup
        rev_results = await resolver.batch_reverse_lookup([wallet])
        print(rev_results)

        # Cache stats
        stats = await resolver.get_cache_stats()
        print(stats)

asyncio.run(main())
```

Class Reference
Web3BioSNSResolver
__init__(cache_db="web3bio_sns_cache.db", cache_ttl=3600, rate_limit=2.0, timeout=10)

cache_db: Path to SQLite database for caching

cache_ttl: Time in seconds before cache entries expire

rate_limit: Requests per second

timeout: HTTP request timeout

resolve_name(name: str) -> Optional[str]

Forward lookup: resolve .sol domain to wallet address.

reverse_lookup(wallet: str) -> Optional[str]

Reverse lookup: resolve wallet address to .sol domain.

batch_resolve_names(names: List[str], batch_size=25, concurrency=3) -> Dict[str, Optional[str]]

Batch forward lookup. Processes names in batches with controlled concurrency.

batch_reverse_lookup(wallets: List[str], concurrency=5) -> Dict[str, Optional[str]]

Batch reverse lookup (single calls concurrently since no batch API is available).

health_check() -> bool

Check if Web3.bio API is responsive.

get_cache_stats() -> Dict[str, int]

Retrieve cache statistics including total entries, valid entries, expired entries, and TTL.

Rate Limiting & Retries

Token-bucket limiter prevents exceeding API limits (default: 2 requests/sec)

Burst capacity allows short spikes

Automatic retry on timeouts or HTTP 429

Exponential backoff with jitter

Note: Web3.bio does not publicly disclose exact rate limits. This implementation is conservative and safe for non-API key usage.

Caching

Uses SQLite (optional)

Entries expire after cache_ttl seconds

Prevents redundant API calls and speeds up repeated queries

Error Handling

Handles HTTP errors gracefully

Respects rate limits

Exponential backoff with retries for transient errors

Logging

Uses Python logging module

Default level: INFO

Debug-level logs include cache hits/misses and retry attempts

License

MIT License
Developed by Kevin Heavey (web3.bio integration)






