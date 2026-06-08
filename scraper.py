"""
Instagram public profile scraper using RapidAPI Instagram Scraper Stable API.
"""

import re
import os
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

RAPIDAPI_HOST = "instagram-scraper-stable-api.p.rapidapi.com"


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
    full_name: str
    biography: str
    followers: int
    following: int
    post_count: int
    is_verified: bool
    profile_pic_url: str
    posts: list = field(default_factory=list)
    error: Optional[str] = None


def _safe_int(val) -> int:
    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def _headers():
    return {
        "x-rapidapi-key": os.getenv("RAPIDAPI_KEY", ""),
        "x-rapidapi-host": RAPIDAPI_HOST,
    }


def _get_profile(username: str) -> Optional[dict]:
    """Fetch user profile info."""
    # Try v1 endpoint first
    for url in [
        f"https://{RAPIDAPI_HOST}/ig/info/",
        f"https://{RAPIDAPI_HOST}/v1/info",
    ]:
        try:
            r = requests.get(
                url,
                headers=_headers(),
                params={"username_or_id_or_url": username},
                timeout=20,
            )
            if r.status_code == 200:
                data = r.json()
                # Handle various response shapes
                return (
                    data.get("data")
                    or data.get("user")
                    or data.get("result")
                    or (data if data.get("username") else None)
                )
        except Exception as e:
            logger.warning(f"Profile fetch failed ({url}): {e}")
    return None


def _get_posts(username: str, max_posts: int) -> list:
    """Fetch recent posts."""
    for url in [
        f"https://{RAPIDAPI_HOST}/ig/posts/",
        f"https://{RAPIDAPI_HOST}/v1/posts",
    ]:
        try:
            r = requests.get(
                url,
                headers=_headers(),
                params={"username_or_id_or_url": username},
                timeout=20,
            )
            if r.status_code == 200:
                data = r.json()
                items = (
                    data.get("data", {}).get("items")
                    or data.get("items")
                    or data.get("posts")
                    or data.get("result", {}).get("items")
                    or []
                )
                return items[:max_posts]
        except Exception as e:
            logger.warning(f"Posts fetch failed ({url}): {e}")
    return []


def _parse_posts(items: list) -> list:
    posts = []
    for item in items:
        # Caption
        cap = item.get("caption") or {}
        caption = cap.get("text", "") if isinstance(cap, dict) else str(cap)
        hashtags = re.findall(r"#(\w+)", caption)

        # Type
        media_type = item.get("media_type") or item.get("type") or 1
        is_video = media_type in (2, "2", "VIDEO", "video") or item.get("is_video", False)

        posts.append(Post(
            shortcode=item.get("code") or item.get("shortcode") or "",
            caption=caption[:600],
            hashtags=hashtags,
            likes=_safe_int(item.get("like_count") or item.get("likes")),
            comments=_safe_int(item.get("comment_count") or item.get("comments")),
            is_video=is_video,
            video_view_count=_safe_int(
                item.get("view_count") or item.get("play_count") or item.get("video_view_count")
            ),
            timestamp=str(item.get("taken_at") or item.get("timestamp") or ""),
            typename="GraphVideo" if is_video else "GraphImage",
        ))
    return posts


def scrape_profile(username: str, max_posts: int = 20) -> ProfileData:
    username = username.strip().lstrip("@")

    if not os.getenv("RAPIDAPI_KEY"):
        return ProfileData(
            username=username, full_name="", biography="",
            followers=0, following=0, post_count=0,
            is_verified=False, profile_pic_url="",
            error="RAPIDAPI_KEY environment variable not set.",
        )

    user = _get_profile(username)
    if not user:
        return ProfileData(
            username=username, full_name="", biography="",
            followers=0, following=0, post_count=0,
            is_verified=False, profile_pic_url="",
            error=f"Could not find '@{username}'. Make sure the account is public and the username is correct.",
        )

    raw_posts = _get_posts(username, max_posts)
    posts = _parse_posts(raw_posts)

    return ProfileData(
        username=user.get("username", username),
        full_name=user.get("full_name", ""),
        biography=user.get("biography") or user.get("bio") or "",
        followers=_safe_int(
            user.get("follower_count") or user.get("followers") or
            user.get("edge_followed_by", {}).get("count")
        ),
        following=_safe_int(
            user.get("following_count") or user.get("following") or
            user.get("edge_follow", {}).get("count")
        ),
        post_count=_safe_int(user.get("media_count") or user.get("post_count")),
        is_verified=bool(user.get("is_verified")),
        profile_pic_url=user.get("profile_pic_url_hd") or user.get("profile_pic_url") or "",
        posts=posts,
    )
