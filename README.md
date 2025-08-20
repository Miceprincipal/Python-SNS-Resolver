I take almost zero credit for this as it is the result of strangling something I needed out of multiple AIs. I am art monkey not a code monkey. But I figured it might be useful to someone who doesn't want to have to wrap the node bonfida libraries even if it's a bit of a bodge solution. Unfortunately I can't offer troubleshooting but I can draw a picture of a duck look pensive if that helps. 

# Multi-Fallback Solana Name Service (SNS) Resolver

A robust async Python resolver for Solana Name Service (SNS) domains and wallets.
Supports **multiple providers** with caching, rate-limiting, retries, and optional parallel fallbacks.

---

## Features

* Reverse lookup: wallet → domain
* Forward lookup: domain → wallet
* Multiple providers: **Helius**, **Shyft**, **Solana.fm**
* Async and parallel-safe
* Configurable caching (memory + SQLite)
* Provider-specific rate limiting
* Retry with exponential backoff

---

## Requirements

* Python 3.10+
* [aiohttp](https://pypi.org/project/aiohttp/)
* Optional: [aiosqlite](https://pypi.org/project/aiosqlite/) for persistent caching

```bash
pip install aiohttp aiosqlite
```

---

## Installation

Clone this repository or copy `multi_fallback_sns_resolver.py` into your project.

```bash
git clone https://github.com/yourusername/multi-fallback-sns-resolver.git
```

---

## Usage

```python
import asyncio
from multi_fallback_sns_resolver import MultiFallbackSnsResolver

async def main():
    resolver = MultiFallbackSnsResolver(
        helius_api_key="YOUR_HELIUS_API_KEY",
        shyft_api_key="YOUR_SHYFT_API_KEY",
        sqlite_cache_path="sns_cache.db",
        parallel_fallbacks=True
    )

    await resolver.init()

    # Reverse lookup: wallet -> domain
    domain = await resolver.reverse_lookup("F4k3W4l1etAddr35545")
    print("Resolved domain:", domain)

    # Batch lookup example
    wallets = ["Addr1...", "Addr2...", "Addr3..."]
    results = await asyncio.gather(*[resolver.reverse_lookup(w) for w in wallets])
    print(results)

    await resolver.close()

asyncio.run(main())
```

---

## Providers & Endpoints

| Provider  | Endpoint / Notes                                     | Requires API Key |
| --------- | ---------------------------------------------------- | ---------------- |
| Helius    | `https://rpc.helius.xyz/?api-key={key}`              | Yes              |
| Shyft     | `https://api.shyft.to/sol/v1/names/reverse/{wallet}` | Yes              |
| Solana.fm | `https://api.solana.fm/v1/sns?wallet={wallet}`       | No               |

> Forward lookup (domain → wallet) is supported via Helius and Shyft as well.

---

## Features Details

### Caching

* **Memory cache** (fast, default)
* **SQLite cache** (persistent) if `aiosqlite` is installed
* Cache TTL configurable via `cache_ttl` (default: 3600s)

### Rate Limiting

* Token-bucket style limiter per provider
* Default: 5 requests/sec per provider
* Global limiter supported

### Parallel Fallbacks

* If multiple providers are configured, resolver can **race them** and return the first successful result
* Sequential fallback is also supported

---

## Error Handling

* Retries with exponential backoff (configurable via `max_retries`)
* Returns `None` if wallet or domain is not found
* Logs detailed errors and warnings

---

## Example Logs

```text
INFO:root:Initialized SQLite cache at sns_cache.db
INFO:root:Parallel lookup resolved F4k3W4l1etAddr35545 to "example.sol"
```

---

## License

MIT License. Free to use, modify, and distribute.

---

## Notes

1. **SNS domains cannot be used directly in Solana RPC calls** because they contain dots (`.`) which are not valid Base58 characters. Always resolve to wallet addresses first.
2. API keys are required for Helius and Shyft. Solana.fm does not require a key.
3. Designed for async applications; use `await` and `asyncio.run()` in your scripts.
