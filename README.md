# MultiFallbackSNSResolver README

## Overview

`MultiFallbackSNSResolver` is a hardened, asynchronous Solana Name Service (SNS) resolver that supports multiple providers (Shyft, Bonfida, Helius) with fallback, caching, and retries. It is designed for forensic and analytic workflows, enabling robust domain resolution, batch lookups, and integration with NFT and token analyses.

I take almost zero credit for this as it is the result of strangling something I needed out of multiple AIs. I am art monkey not a code monkey. But I figured it might be useful to someone who doesn't want to have to wrap the node bonfida libraries even if it's a bit of a bodge solution. Unfortunately I can't offer troubleshooting but I can draw a picture of a duck look pensive if that helps.

---

## Features

- Multi-provider `.sol` domain resolution with automatic fallback
- Parallel or sequential lookups with concurrency control
- Memory and SQLite caching with TTL support
- Exponential backoff retries for network requests
- Provider performance statistics (success rate, average response time)
- Batch wallet reverse lookups
- Domain enumeration for wallets (NFT-based)
- Health checks for all providers

---

## Installation

```bash
pip install aiohttp aiosqlite
```

Place `multi_fallback_sns_resolver.py` in your project directory.

---

## Usage

### Initialize Resolver

```python
import asyncio
from multi_fallback_sns_resolver import MultiFallbackSnsResolver

resolver = MultiFallbackSnsResolver(
    rpc_url="https://api.mainnet-beta.solana.com",
    shyft_api_key="YOUR_SHYFT_API_KEY",
    helius_api_key="YOUR_HELIUS_API_KEY",
    sqlite_cache_path="sns_cache.db",
    cache_ttl=3600,
    parallel_fallbacks=True
)

asyncio.run(resolver.init())
```

### Single Wallet Lookup

```python
wallet = "6XhQqJqYQwQY3B3kt6H27Xj1gYkKfjx5k1hR3nH9Rx9k"
domain = await resolver.reverse_lookup_with_fallbacks(wallet)
print(f"{wallet} → {domain}")
```

### Batch Wallet Lookup

```python
wallets = ["6XhQqJqYQwQY3B3kt6H27Xj1gYkKfjx5k1hR3nH9Rx9k", "8D7d9aK6QpQ8sYc3t6GJ1W2V3G9nD5k2fF9hB2kT9JqA"]
results = await resolver.batch_reverse_lookup(wallets, concurrency=5)
print(results)
```

### Retrieve All Domains Owned by a Wallet

```python
domains = await resolver.get_wallet_domains_with_fallbacks(wallet)
print(domains)
```

### Integrating with NFT Forensics

```python
owned_nfts = await nft_module.get_owned_nfts(wallet)
creator_domains = {}
for nft in owned_nfts:
    creator_wallet = nft["creator"]
    domain = await resolver.reverse_lookup_with_fallbacks(creator_wallet)
    creator_domains[creator_wallet] = domain
print(creator_domains)
```

### Quick SOL & Token Forensics Integration

```python
balances = {}
for wallet in wallets:
    sol_balance = await solana_module.get_sol_balance(wallet)
    token_balances = await solana_module.get_token_balances(wallet)
    balances[wallet] = {"sol": sol_balance, "tokens": token_balances, "domain": domains.get(wallet)}
print(balances)
```

### Health Checks & Provider Monitoring

```python
health = await resolver.health_check()
stats = resolver.get_provider_stats()
print(health, stats)
```

---

## Best Practices & Tips

1. **Rate Limiting:**
   - Use your own rate-limiter to prevent API throttling.
   - Avoid making too many parallel requests to free-tier endpoints.

2. **Parallel Lookups:**
   - `parallel_fallbacks=True` is faster but increases load.
   - Use `concurrency` parameter in `batch_reverse_lookup` to control batch speed.

3. **Caching:**
   - Memory cache is fastest.
   - SQLite cache persists across runs; set TTL to your preference.

4. **Error Handling:**
   - Resolver automatically retries failed requests with exponential backoff.
   - Negative results are cached with shorter TTL to reduce repeated lookups.

5. **Provider Selection:**
   - Shyft and Helius require API keys.
   - Bonfida is public but slower and sometimes rate-limited.
   - Health checks allow you to monitor provider availability.

6. **Integration:**
   - Can be integrated with other Solana analytics pipelines.

---

## Cleanup

```python
await resolver.close()
```

Always close resources to prevent open connections.

---

## License

MIT License

---

**End of README**

