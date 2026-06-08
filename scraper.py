"""
Instagram scraper using Apify — works from cloud servers.
Requires APIFY_TOKEN environment variable.
"""

import os
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Post:
    shortcode: str
    caption: str
    hashtags: list
    likes: int
    comments: int
    is_video: bool
    video_view_count: int
    timestamp: str
    typename: str


@dataclass
class ProfileData:
    username: str
    full_name: str = ""
    biography: str = ""
    followers: int = 0
    following: int = 0
    post_count: int = 0
    is_verified: bool = False
    profile_pic_url: str = ""
    posts: list = field(default_factory=list)
    web_research: str = ""
    error: Optional[str] = None


def _extract_hashtags(text: str) -> list:
    if not text:
        return []
    return re.findall(r"#(\w+)", text)


def scrape_profile(username: str, password: str = "", max_posts: int = 20) -> ProfileData:
    username = username.strip().lstrip("@")

    apify_token = os.getenv("APIFY_TOKEN", "").strip()
    if not apify_token:
        logger.warning("APIFY_TOKEN not set — returning empty profile")
        return ProfileData(username=username, error="APIFY_TOKEN not configured")

    try:
        from apify_client import ApifyClient
    except ImportError:
        return ProfileData(username=username, error="apify-client not installed")

    try:
        client = ApifyClient(apify_token)

        run_input = {"usernames": [username], "resultsLimit": max_posts}
        if username and password:
            run_input["loginInfo"] = {"username": username, "password": password}

        logger.info(f"Fetching @{username} via Apify (auth={'yes' if password else 'no'})...")
        run = client.actor("apify/instagram-profile-scraper").call(
            run_input=run_input,
        )

        # apify-client may return a dict or a Run object depending on version
        if isinstance(run, dict):
            dataset_id = run["defaultDatasetId"]
        else:
            dataset_id = (
                getattr(run, "default_dataset_id", None)
                or getattr(run, "defaultDatasetId", None)
            )

        items = list(client.dataset(dataset_id).iterate_items())

        if not items:
            return ProfileData(
                username=username,
                error=f"Could not find public profile for @{username}. Check that it's a public account.",
            )

        raw = items[0]

        # Parse profile fields
        profile = ProfileData(
            username=username,
            full_name=raw.get("fullName") or raw.get("full_name", ""),
            biography=raw.get("biography") or raw.get("bio", ""),
            followers=raw.get("followersCount") or raw.get("followers", 0) or 0,
            following=raw.get("followsCount") or raw.get("following", 0) or 0,
            post_count=raw.get("postsCount") or raw.get("mediaCount", 0) or 0,
            is_verified=raw.get("verified") or raw.get("is_verified", False) or False,
            profile_pic_url=raw.get("profilePicUrl") or raw.get("profile_pic_url", ""),
        )

        # Parse posts — Apify may nest them under "latestPosts" or similar
        raw_posts = (
            raw.get("latestPosts")
            or raw.get("posts")
            or raw.get("topPosts")
            or []
        )

        for p in raw_posts[:max_posts]:
            caption = p.get("caption") or p.get("alt") or ""
            profile.posts.append(
                Post(
                    shortcode=p.get("shortCode") or p.get("id", ""),
                    caption=caption,
                    hashtags=_extract_hashtags(caption),
                    likes=p.get("likesCount") or p.get("likes", 0) or 0,
                    comments=p.get("commentsCount") or p.get("comments", 0) or 0,
                    is_video=p.get("type") in ("Video", "video") or p.get("isVideo", False),
                    video_view_count=p.get("videoViewCount") or p.get("views", 0) or 0,
                    timestamp=p.get("timestamp") or p.get("taken_at_timestamp", ""),
                    typename=p.get("type") or ("Video" if p.get("isVideo") else "Image"),
                )
            )

        logger.info(
            f"@{username}: {profile.followers:,} followers, {len(profile.posts)} posts fetched"
        )
        return profile

    except Exception as e:
        logger.exception(f"Apify scrape failed for @{username}")
        return ProfileData(username=username, error=f"Scrape failed: {e}")
