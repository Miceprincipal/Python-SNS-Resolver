I take almost zero credit for this as it is the result of strangling something I needed out of multiple AIs. I am art monkey not a code monkey. But I figured it might be useful to someone who doesn't want to have to wrap the node bonfida libraries even if it's a bit of a bodge solution. Unfortunately I can't offer troubleshooting but I can draw a picture of a duck look pensive if that helps.

# Multi-Fallback SNS Resolver

A hardened, async Python resolver for Solana Name Service (SNS) domains. Supports multiple providers (Shyft, Helius, Bonfida), caching (memory + SQLite), rate-limiting, retries, and parallel fallbacks.

## Features

* Resolve **SNS domain → wallet address**
* Resolve **wallet address → SNS domain** (reverse lookup)
* Automatic **fallback between multiple providers** based on success rate
* **Parallel requests** for fastest resolution
* **Memory + SQLite caching** with configurable TTL
* **Retries with exponential backoff** for robust network handling
* Optional **rate-limiting** per provider
* Health checks and provider statistics

> **Important:** SNS domains (e.g., `example.sol`) **cannot** be passed directly to Solana RPC methods. They must first be resolved to a valid Solana public key (Base58) using this resolver.

## Installation

```bash
pip install aiohttp aiosqlite
```

## Usage Example

```python
import asyncio
from multi_fallback_sns_resolver import MultiFallbackSnsResolver

async def main():
    resolver = MultiFallbackSnsResolver(
        rpc_url="https://api.mainnet-beta.solana.com",
        shyft_api_key="YOUR_SHYFT_KEY",
        helius_api_key="YOUR_HELIUS_KEY",
        sqlite_cache_path="sns_cache.db"
    )
    
    await resolver.init()
    
    # Resolve domain -> wallet
    wallet = await resolver.reverse_lookup_with_fallbacks("example.sol")
    print("Wallet for example.sol:", wallet)
    
    # Resolve wallet -> domain
    domain = await resolver.get_wallet_domains_with_fallbacks(wallet)
    print("Domains for wallet:", domain)
    
    await resolver.close()

asyncio.run(main())
```

## Correct API Endpoints

**Shyft**

* Reverse lookup (wallet → domain):
  `GET https://api.shyft.to/sol/v1/names/reverse/{address}?network=mainnet-beta`
* Forward lookup (domain → wallet):
  `GET https://api.shyft.to/sol/v1/names/{domain}?network=mainnet-beta`
* Header: `x-api-key: YOUR_SHYFT_KEY`

**Helius**

* Reverse lookup (wallet → domain) using `getNameOwner`:
  `POST https://mainnet.helius-rpc.com/?api-key=YOUR_HELIUS_KEY`

  ```json
  {
    "jsonrpc": "2.0",
    "id": "sns-reverse",
    "method": "getNameOwner",
    "params": ["<wallet_address>"]
  }
  ```
* Forward lookup (domain → wallet) using `getDomainKey`:
  `POST https://mainnet.helius-rpc.com/?api-key=YOUR_HELIUS_KEY`

  ```json
  {
    "jsonrpc": "2.0",
    "id": "sns-lookup",
    "method": "getDomainKey",
    "params": ["<sns_domain>"]
  }
  ```

**Bonfida (public)**

* Reverse lookup (wallet → domain):
  `GET https://sns-api.bonfida.com/reverse-lookup/{wallet_address}`

## Batch Lookup Example

```python
wallets = [
    "Fv1nXf9E...abc",
    "7Lh3vV8...xyz"
]

results = await resolver.batch_reverse_lookup(wallets)
for w, d in results.items():
    print(w, "->", d)
```

## Notes

* Helius and Shyft POST requests require JSON-RPC payloads.
* SNS domains **cannot** be used directly in Solana RPC calls; always resolve to wallet first.
* Caching and rate-limiting help avoid hitting provider limits.
