"""
Instagram public profile scraper.
Simulates a mobile Instagram session to work from cloud servers.
"""

import re
import os
import time
import uuid
import random
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests

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


def _random_device_id():
    return f"android-{random.randint(0xFFFFFF, 0xFFFFFFFF):x}"


def _make_session():
    """Build a session that looks like the Instagram Android app."""
    session = requests.Session()
    device_id = str(uuid.uuid4())
    android_id = _random_device_id()

    # Mimic Instagram Android app
    session.headers.update({
        "User-Agent": (
            "Instagram 275.0.0.27.98 Android "
            "(33/13; 420dpi; 1080x2400; samsung; SM-G991B; o1s; exynos2100; en_US; 458229258)"
        ),
        "Accept": "*/*",
        "Accept-Language": "en-US",
        "Accept-Encoding": "gzip, deflate",
        "X-IG-App-ID": "567067343352427",
        "X-IG-Device-ID": device_id,
        "X-IG-Android-ID": android_id,
        "X-IG-Connection-Type": "WIFI",
        "X-IG-Capabilities": "3brTvx0=",
        "X-IG-Bandwidth-Speed-KBPS": str(random.randint(5000, 20000)),
        "X-IG-Bandwidth-TotalBytes-B": str(random.randint(1000000, 5000000)),
        "X-IG-Bandwidth-TotalTime-MS": str(random.randint(200, 800)),
    })
    return session


def _try_mobile_api(session, username):
    """Instagram's mobile API endpoint."""
    url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
    try:
        r = session.get(url, timeout=20)
        if r.status_code == 200:
            return r.json().get("data", {}).get("user")
    except Exception as e:
        logger.warning(f"Mobile API failed: {e}")
    return None


def _try_web_api(session, username):
    """Instagram's web API endpoint with browser headers."""
    # Switch to browser headers for this attempt
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "X-IG-App-ID": "936619743392459",
        "Referer": "https://www.instagram.com/",
        "Origin": "https://www.instagram.com",
    })

    # First, grab cookies from the homepage
    try:
        session.get("https://www.instagram.com/", timeout=10)
        time.sleep(random.uniform(0.5, 1.0))
    except Exception:
        pass

    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
    try:
        r = session.get(url, timeout=20)
        if r.status_code == 200:
            return r.json().get("data", {}).get("user")
    except Exception as e:
        logger.warning(f"Web API failed: {e}")
    return None


def _try_graphql(session, username):
    """Older GraphQL endpoint."""
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    })
    url = f"https://www.instagram.com/{username}/?__a=1&__d=dis"
    try:
        r = session.get(url, timeout=20)
        if r.status_code == 200:
            data = r.json()
            return data.get("graphql", {}).get("user") or data.get("data", {}).get("user")
    except Exception as e:
        logger.warning(f"GraphQL failed: {e}")
    return None


def _parse_posts(edges, max_posts):
    posts = []
    for edge in edges[:max_posts]:
        node = edge.get("node", {})
        caps = node.get("edge_media_to_caption", {}).get("edges", [])
        caption = caps[0]["node"]["text"] if caps else ""
        hashtags = re.findall(r"#(\w+)", caption)
        typename = node.get("__typename", "GraphImage")
        is_video = typename == "GraphVideo" or node.get("is_video", False)
        posts.append(Post(
            shortcode=node.get("shortcode", ""),
            caption=caption[:600],
            hashtags=hashtags,
            likes=_safe_int(
                node.get("edge_liked_by", {}).get("count") or
                node.get("edge_media_preview_like", {}).get("count")
            ),
            comments=_safe_int(node.get("edge_media_to_comment", {}).get("count")),
            is_video=is_video,
            video_view_count=_safe_int(node.get("video_view_count")),
            timestamp=str(node.get("taken_at_timestamp", "")),
            typename=typename,
        ))
    return posts


def scrape_profile(username: str, max_posts: int = 20) -> ProfileData:
    username = username.strip().lstrip("@")
    session = _make_session()

    # Try three approaches in sequence
    user = _try_mobile_api(session, username)

    if not user:
        time.sleep(random.uniform(1.0, 2.0))
        session = _make_session()
        user = _try_web_api(session, username)

    if not user:
        time.sleep(random.uniform(1.0, 2.0))
        session = _make_session()
        user = _try_graphql(session, username)

    if not user:
        return ProfileData(
            username=username, full_name="", biography="",
            followers=0, following=0, post_count=0,
            is_verified=False, profile_pic_url="",
            error=(
                f"Could not retrieve '@{username}'. "
                "Instagram is currently blocking automated requests from this server. "
                "Please try again in 30 seconds, or try a different username."
            ),
        )

    timeline = (
        user.get("edge_owner_to_timeline_media") or
        user.get("edge_felix_video_timeline") or {}
    )
    posts = _parse_posts(timeline.get("edges", []), max_posts)

    return ProfileData(
        username=user.get("username", username),
        full_name=user.get("full_name", ""),
        biography=user.get("biography", ""),
        followers=_safe_int(
            user.get("edge_followed_by", {}).get("count") or user.get("follower_count")
        ),
        following=_safe_int(
            user.get("edge_follow", {}).get("count") or user.get("following_count")
        ),
        post_count=_safe_int(
            user.get("edge_owner_to_timeline_media", {}).get("count") or user.get("media_count")
        ),
        is_verified=bool(user.get("is_verified")),
        profile_pic_url=user.get("profile_pic_url_hd") or user.get("profile_pic_url") or "",
        posts=posts,
    )
