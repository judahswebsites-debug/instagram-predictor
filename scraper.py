"""
Instagram scraper.
Primary: instagrapi (authenticated mobile API — gets real creator insights).
Fallback: Apify public scraper.
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
    reach: int = 0        # only available when logged in as the creator
    impressions: int = 0  # only available when logged in as the creator
    saves: int = 0        # only available when logged in as the creator
    shares: int = 0       # only available when logged in as the creator


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
    has_insights: bool = False   # True when we have real reach/impressions data
    error: Optional[str] = None


def _extract_hashtags(text: str) -> list:
    if not text:
        return []
    return re.findall(r"#(\w+)", text)


def _scrape_with_instagrapi(username: str, password: str, max_posts: int) -> Optional[ProfileData]:
    """Log in as the creator and pull real insights data."""
    try:
        from instagrapi import Client
        from instagrapi.exceptions import (
            BadPassword, ChallengeRequired, TwoFactorRequired,
            LoginRequired, PleaseWaitFewMinutes
        )
    except ImportError:
        logger.warning("instagrapi not installed")
        return None

    cl = Client()
    # Mimic a real Android device to reduce challenge triggers
    cl.set_settings({
        "user_agent": (
            "Instagram 275.0.0.27.98 Android (28/9.0; 420dpi; 1080x2220; "
            "samsung; SM-G973F; beyond1; exynos9820; en_US; 458328067)"
        )
    })

    try:
        cl.login(username, password)
        logger.info(f"instagrapi login succeeded for @{username}")
    except BadPassword:
        return ProfileData(
            username=username,
            error="Incorrect Instagram password. Please check and try again."
        )
    except TwoFactorRequired:
        return ProfileData(
            username=username,
            error="Your account has two-factor authentication enabled. Temporarily disable it in Instagram settings, then try again."
        )
    except ChallengeRequired:
        return ProfileData(
            username=username,
            error="Instagram flagged this as a suspicious login. Open Instagram on your phone, confirm it was you, then try again in a few minutes."
        )
    except PleaseWaitFewMinutes:
        return ProfileData(
            username=username,
            error="Instagram is asking us to wait. Try again in 5 minutes."
        )
    except Exception as e:
        logger.warning(f"instagrapi login failed: {e} — falling back to Apify")
        return None  # Fall through to Apify

    try:
        user_info = cl.user_info_by_username(username)
    except Exception as e:
        logger.warning(f"instagrapi user_info failed: {e}")
        return None

    profile = ProfileData(
        username=username,
        full_name=user_info.full_name or "",
        biography=user_info.biography or "",
        followers=user_info.follower_count or 0,
        following=user_info.following_count or 0,
        post_count=user_info.media_count or 0,
        is_verified=user_info.is_verified or False,
        profile_pic_url=str(user_info.profile_pic_url or ""),
        has_insights=True,
    )

    try:
        medias = cl.user_medias(user_info.pk, amount=max_posts)
    except Exception as e:
        logger.warning(f"instagrapi user_medias failed: {e}")
        return profile  # Return profile even without posts

    for media in medias:
        caption = media.caption_text or ""
        reach = impressions = saves = shares = 0

        # Try to get creator insights (reach, impressions, saves, shares)
        try:
            insights = cl.insights_media(media.pk)
            reach       = getattr(insights, "reach", 0) or 0
            impressions = getattr(insights, "impressions", 0) or 0
            saves       = getattr(insights, "saved", 0) or 0
            shares      = getattr(insights, "shares", 0) or 0
        except Exception:
            pass  # Insights not available — still keep the post

        media_type = media.media_type  # 1=Photo, 2=Video, 8=Carousel
        typename = "Video" if media_type == 2 else "Carousel" if media_type == 8 else "Image"

        profile.posts.append(Post(
            shortcode=media.code or "",
            caption=caption,
            hashtags=_extract_hashtags(caption),
            likes=media.like_count or 0,
            comments=media.comment_count or 0,
            is_video=media_type == 2,
            video_view_count=media.view_count or 0,
            timestamp=str(media.taken_at or ""),
            typename=typename,
            reach=reach,
            impressions=impressions,
            saves=saves,
            shares=shares,
        ))

    logger.info(
        f"@{username}: {profile.followers:,} followers, "
        f"{len(profile.posts)} posts, insights={'yes' if profile.has_insights else 'no'}"
    )
    return profile


def _scrape_with_apify(username: str, password: str, max_posts: int) -> ProfileData:
    """Fallback: Apify public scraper."""
    apify_token = os.getenv("APIFY_TOKEN", "").strip()
    if not apify_token:
        return ProfileData(username=username, error="Could not retrieve Instagram data. Please check your username and password.")

    try:
        from apify_client import ApifyClient
    except ImportError:
        return ProfileData(username=username, error="apify-client not installed")

    try:
        client = ApifyClient(apify_token)
        run_input = {"usernames": [username], "resultsLimit": max_posts}
        if password:
            run_input["loginInfo"] = {"username": username, "password": password}

        run = client.actor("apify/instagram-profile-scraper").call(run_input=run_input)

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
                error=f"Could not find a public profile for @{username}."
            )

        raw = items[0]
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

        raw_posts = raw.get("latestPosts") or raw.get("posts") or raw.get("topPosts") or []
        for p in raw_posts[:max_posts]:
            caption = p.get("caption") or p.get("alt") or ""
            profile.posts.append(Post(
                shortcode=p.get("shortCode") or p.get("id", ""),
                caption=caption,
                hashtags=_extract_hashtags(caption),
                likes=p.get("likesCount") or p.get("likes", 0) or 0,
                comments=p.get("commentsCount") or p.get("comments", 0) or 0,
                is_video=p.get("type") in ("Video", "video") or p.get("isVideo", False),
                video_view_count=p.get("videoViewCount") or p.get("views", 0) or 0,
                timestamp=p.get("timestamp") or p.get("taken_at_timestamp", ""),
                typename=p.get("type") or ("Video" if p.get("isVideo") else "Image"),
            ))

        return profile

    except Exception as e:
        logger.exception(f"Apify scrape failed for @{username}")
        return ProfileData(username=username, error=f"Scrape failed: {e}")


def scrape_profile(username: str, password: str = "", max_posts: int = 20) -> ProfileData:
    username = username.strip().lstrip("@")

    # Try authenticated instagrapi first (gets real insights)
    if password:
        result = _scrape_with_instagrapi(username, password, max_posts)
        if result is not None:
            return result
        # None means login failed for a retryable reason — fall through to Apify

    # Fallback to Apify
    logger.info(f"Using Apify fallback for @{username}")
    return _scrape_with_apify(username, password, max_posts)
