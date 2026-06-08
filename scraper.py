"""
Instagram researcher — uses Claude's knowledge about the creator.
No external scraping needed. Works from any server.
"""

from dataclasses import dataclass, field
from typing import Optional


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


def scrape_profile(username: str, max_posts: int = 20) -> ProfileData:
    """
    Returns a minimal ProfileData shell.
    The actual research is done inside the analyzer using Claude's knowledge.
    """
    username = username.strip().lstrip("@")
    return ProfileData(username=username)
