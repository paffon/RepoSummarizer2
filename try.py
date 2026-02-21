import asyncio
import time
import aiohttp

BASE_URL = "http://localhost:8000"

URLS = [
    "https://github.com/paffon/AIDiscussion",
    "https://github.com/paffon/RockPaperScissors",
    "https://github.com/torvalds/linux",
]


async def summarize(session: aiohttp.ClientSession, github_url: str) -> None:
    start = time.monotonic()
    print(f"Sent request: {github_url}")
    try:
        async with session.post(
            f"{BASE_URL}/summarize",
            json={"github_url": github_url},
        ) as response:
            elapsed = time.monotonic() - start
            body = await response.json()
            print(f"\n---\n")
            print(f"Response received for {github_url}")
            print(f"Status: {response.status}")
            print(f"Body: {body}")
            print(f"Time: {elapsed:.1f}s")
            print(f"\n---")
    except aiohttp.ClientError as e:
        elapsed = time.monotonic() - start
        print(f"\n---\n")
        print(f"Error for {github_url}: {type(e).__name__}: {e}")
        print(f"Time: {elapsed:.1f}s")
        print(f"\n---")


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*(summarize(session, url) for url in URLS))


if __name__ == "__main__":
    asyncio.run(main())
