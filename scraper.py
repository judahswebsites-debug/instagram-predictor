"""
Instagram researcher — uses web search + oEmbed to gather public profile data.
Works from any server with no extra API keys.
"""

import re
import logging
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
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
    # Extra field for web research data
    web_research: str = ""
    error: Optional[str] = None


def _oembed_profile(username: str) -> dict:
    """Get basic profile info from Instagram's official oEmbed endpoint."""
    try:
        url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            user = r.json().get("data", {}).get("user", {})
            if user:
                return user
    except Exception:
        pass

    # Fallback: oEmbed
    try:
        url = f"https://api.instagram.com/oembed/?url=https://www.instagram.com/{username}/&format=json"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return {
                "username": username,
                "full_name": data.get("author_name", ""),
                "profile_pic_url": data.get("thumbnail_url", ""),
            }
    except Exception:
        pass

    return {}


def _ddg_search(query: str, max_results: int = 8) -> list[str]:
    """Search DuckDuckGo and return a list of result snippets."""
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        snippets = []
        for result in soup.select(".result__snippet"):
            text = result.get_text(strip=True)
            if text:
                snippets.append(text)
            if len(snippets) >= max_results:
                break
        return snippets
    except Exception as e:
        logger.warning(f"DDG search failed: {e}")
        return []


def _research_creator(username: str) -> str:
    """
    Build a research dossier on an Instagram creator using web search.
    Returns a text block that gets sent to Claude alongside whatever
    profile data we could collect.
    """
    sections = []

    # 1. General profile search
    general = _ddg_search(f"{username} instagram creator content")
    if general:
        sections.append("## Web results about @" + username)
        sections.extend(f"- {s}" for s in general)

    # 2. Recent content / viral posts
    recent = _ddg_search(f"{username} instagram recent posts viral 2024 2025")
    if recent:
        sections.append("\n## Recent content mentions")
        sections.extend(f"- {s}" for s in recent)

    # 3. Niche / trending topics
    niche = _ddg_search(f"instagram {username} niche audience followers content type")
    if niche:
        sections.append("\n## Niche & audience research")
        sections.extend(f"- {s}" for s in niche)

    return "\n".join(sections)


def scrape_profile(username: str, max_posts: int = 20) -> ProfileData:
    username = username.strip().lstrip("@")

    # Try to get basic profile data
    user = _oembed_profile(username)

    # Always do web research regardless
    research = _research_creator(username)

    if not user and not research:
        return ProfileData(
            username=username, full_name="", biography="",
            followers=0, following=0, post_count=0,
            is_verified=False, profile_pic_url="",
            error=f"Could not find any public information for '@{username}'. Check the username is correct.",
        )

    return ProfileData(
        username=user.get("username", username),
        full_name=user.get("full_name", ""),
        biography=user.get("biography", ""),
        followers=int(user.get("edge_followed_by", {}).get("count") or
                      user.get("follower_count") or 0),
        following=int(user.get("edge_follow", {}).get("count") or
                      user.get("following_count") or 0),
        post_count=int(user.get("edge_owner_to_timeline_media", {}).get("count") or
                       user.get("media_count") or 0),
        is_verified=bool(user.get("is_verified")),
        profile_pic_url=user.get("profile_pic_url_hd") or user.get("profile_pic_url") or "",
        posts=[],  # No post-level data in this mode
        web_research=research,
    )
