I take almost zero credit for this as it is the result of strangling something I needed out of multiple AIs. I am art monkey not a code monkey. But I figured it might be useful to someone who doesn't want to have to wrap the node bonfida libraries even if it's a bit of a bodge solution. Unfortunately I can't offer troubleshooting but I can draw a picture of a duck look pensive if that helps. 

# SNSResolver

`SNSResolver` is an asynchronous Python module for resolving **Solana `.sol` domains** to wallet addresses and performing **reverse lookups** from wallet addresses to `.sol` domains. It uses **proper PDA computation** for `.sol` domains and queries **Solana.fm** for reverse lookups. The module includes caching, rate limiting, retry logic, and batch processing.

---

## Features

- **Resolve `.sol` domain → wallet address** using SNS PDA derivation.
- **Reverse lookup wallet → `.sol` domain** using Solana.fm API.
- **Async & throttled requests** with token-bucket rate limiting.
- **SQLite caching** with TTL support.
- **Batch resolution** for domains and wallets.
- **API performance tracking** and health checks.
- **Retry logic** with exponential backoff.

---

## Installation

```bash
pip install aiohttp aiosqlite solders

