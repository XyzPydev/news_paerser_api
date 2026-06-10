"""
Truth Social Scraper — uses Mastodon.py to poll the public timeline.

Truth Social exposes a Mastodon-compatible API, so mastodon.py works
out of the box by pointing at the Truth Social base URL.

If no access token is configured the worker sleeps and logs a warning,
allowing the system to operate without Truth Social integration.
"""

import asyncio
import logging
from datetime import UTC, datetime

from app.common.config import Settings
from app.services.news_pipeline import process_telegram_post

logger = logging.getLogger(__name__)

TRUTH_SOCIAL_API_BASE = "https://truthsocial.com"
# How often to poll the home / public timeline (seconds)
POLL_INTERVAL = 30
# How many posts to fetch per poll cycle
FETCH_LIMIT = 20


async def _poll_truth_social(settings: Settings, stop_event: asyncio.Event) -> None:
    """Poll Truth Social timeline and emit events through news_pipeline."""
    from mastodon import Mastodon, MastodonError  # noqa: PLC0415

    client = Mastodon(
        access_token=settings.truth_social_access_token,
        api_base_url=TRUTH_SOCIAL_API_BASE,
    )

    seen_ids: set[str] = set()
    logger.info("Truth Social scraper connected to %s", TRUTH_SOCIAL_API_BASE)

    while not stop_event.is_set():
        try:
            # Fetch home timeline (posts from accounts the user follows)
            toots = await asyncio.to_thread(client.timeline_home, limit=FETCH_LIMIT)

            for toot in toots:
                toot_id = str(toot.get("id", ""))
                if toot_id in seen_ids:
                    continue
                seen_ids.add(toot_id)

                # Extract plain text (strip HTML tags via Mastodon)
                content: str = toot.get("content", "")
                # Simple HTML stripping — mastodon.py returns HTML
                import re  # noqa: PLC0415

                plain_text = re.sub(r"<[^>]+>", " ", content).strip()
                if not plain_text:
                    continue

                account = toot.get("account") or {}
                acct = account.get("acct", "unknown")
                display_name = account.get("display_name") or acct
                created_at: datetime = toot.get("created_at", datetime.now(UTC))
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at)

                media_attachments = toot.get("media_attachments") or []
                url = toot.get("url") or ""

                post = {
                    "provider": "mastodon",
                    "channel": {
                        "id": account.get("id"),
                        "username": acct,
                        "title": display_name,
                    },
                    "message_id": toot_id,
                    "url": url,
                    "published_at": created_at.isoformat(),
                    "has_media": len(media_attachments) > 0,
                    "raw_text": plain_text,
                }

                try:
                    await process_telegram_post(settings, post)
                    logger.info(
                        "Truth Social post processed: @%s id=%s preview=%r",
                        acct,
                        toot_id,
                        plain_text[:120],
                    )
                except Exception as exc:
                    logger.exception("Failed to process Truth Social post %s: %s", toot_id, exc)

            # Keep seen_ids from growing unboundedly
            if len(seen_ids) > 10_000:
                seen_ids = set(list(seen_ids)[-5_000:])

        except MastodonError as exc:
            logger.warning("Truth Social Mastodon API error: %s — retrying in %ds", exc, POLL_INTERVAL)
        except Exception as exc:
            logger.exception("Unexpected Truth Social error: %s", exc)

        # Wait before next poll cycle
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            pass


async def run_truth_scraper(settings: Settings, stop_event: asyncio.Event) -> None:
    """Entry point called from lifespan. Handles missing token gracefully."""
    if not settings.truth_social_access_token or settings.truth_social_access_token == "replace-me":
        logger.info(
            "Truth Social scraper disabled: TRUTH_SOCIAL_ACCESS_TOKEN not configured. "
            "Set it in .env to enable polling."
        )
        await stop_event.wait()
        return

    while not stop_event.is_set():
        try:
            await _poll_truth_social(settings, stop_event)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.exception("Truth Social scraper crashed: %s — restarting in 60s", exc)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

    logger.info("Truth Social scraper stopped")
