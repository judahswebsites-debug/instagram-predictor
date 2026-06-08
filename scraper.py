"""
Instagram public profile scraper.
Uses Instagram's internal web API — no login required, public profiles only.
"""

import re
import time
import random
import logging
import json
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Instagram's own web app ID — used by their website
IG_APP_ID = "936619743392459"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "X-IG-App-ID": IG_APP_ID,
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.instagram.com/",
    "Origin": "https://www.instagram.com",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


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


def _get_session_cookies(session: requests.Session) -> bool:
    """Hit the Instagram homepage to pick up csrftoken + session cookies."""
    try:
        resp = session.get(
            "https://www.instagram.com/",
            headers={
                "User-Agent": HEADERS["User-Agent"],
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
            allow_redirects=True,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Cookie fetch failed: {e}")
        return False


def _fetch_profile_api(session: requests.Session, username: str) -> Optional[dict]:
    """
    Call Instagram's web_profile_info endpoint.
    Returns the raw 'data.user' dict or None.
    """
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            logger.warning(f"web_profile_info returned {resp.status_code}")
            return None
        data = resp.json()
        return data.get("data", {}).get("user")
    except Exception as e:
        logger.warning(f"web_profile_info error: {e}")
        return None


def _fetch_profile_graphql(session: requests.Session, username: str) -> Optional[dict]:
    """
    Fallback: use the older /?__a=1 endpoint.
    """
    url = f"https://www.instagram.com/{username}/?__a=1&__d=dis"
    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("graphql", {}).get("user") or data.get("data", {}).get("user")
    except Exception as e:
        logger.warning(f"graphql fallback error: {e}")
        return None


def _parse_posts(edges: list, max_posts: int) -> list:
    posts = []
    for edge in edges[:max_posts]:
        node = edge.get("node", {})
        caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
        caption = caption_edges[0]["node"]["text"] if caption_edges else ""
        hashtags = re.findall(r"#(\w+)", caption)
        typename = node.get("__typename", "GraphImage")
        is_video = typename == "GraphVideo" or node.get("is_video", False)

        posts.append(Post(
            shortcode=node.get("shortcode", ""),
            caption=caption[:600],
            hashtags=hashtags,
            likes=_safe_int(node.get("edge_liked_by", {}).get("count")
                            or node.get("edge_media_preview_like", {}).get("count")),
            comments=_safe_int(node.get("edge_media_to_comment", {}).get("count")),
            is_video=is_video,
            video_view_count=_safe_int(node.get("video_view_count")),
            timestamp=str(node.get("taken_at_timestamp", "")),
            typename=typename,
        ))
    return posts


def scrape_profile(username: str, max_posts: int = 20) -> ProfileData:
    username = username.strip().lstrip("@")

    session = requests.Session()
    session.headers.update({"User-Agent": HEADERS["User-Agent"]})

    # Grab cookies first (needed for CSRF)
    _get_session_cookies(session)
    time.sleep(random.uniform(0.5, 1.2))

    # Try primary API endpoint
    user = _fetch_profile_api(session, username)

    # Try fallback if needed
    if not user:
        time.sleep(random.uniform(0.5, 1.0))
        user = _fetch_profile_graphql(session, username)

    if not user:
        return ProfileData(
            username=username, full_name="", biography="",
            followers=0, following=0, post_count=0,
            is_verified=False, profile_pic_url="",
            error=(
                f"Could not find '@{username}'. "
                "Make sure the account is public and the username is spelled correctly. "
                "Instagram may also be temporarily rate-limiting — wait 30 seconds and try again."
            ),
        )

    # Parse posts from timeline media
    timeline = (
        user.get("edge_owner_to_timeline_media")
        or user.get("edge_felix_video_timeline")
        or {}
    )
    edges = timeline.get("edges", [])
    posts = _parse_posts(edges, max_posts)

    return ProfileData(
        username=user.get("username", username),
        full_name=user.get("full_name", ""),
        biography=user.get("biography", ""),
        followers=_safe_int(
            user.get("edge_followed_by", {}).get("count")
            or user.get("follower_count")
        ),
        following=_safe_int(
            user.get("edge_follow", {}).get("count")
            or user.get("following_count")
        ),
        post_count=_safe_int(
            user.get("edge_owner_to_timeline_media", {}).get("count")
            or user.get("media_count")
        ),
        is_verified=bool(user.get("is_verified")),
        profile_pic_url=user.get("profile_pic_url_hd") or user.get("profile_pic_url") or "",
        posts=posts,
    )
