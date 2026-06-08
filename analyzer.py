"""
AI analysis engine.
Strictly uses only real scraped data — no hallucination of missing stats.
"""

import json
import re
import logging
from dataclasses import dataclass
from typing import Optional

import anthropic
from scraper import ProfileData

logger = logging.getLogger(__name__)


@dataclass
class ContentIdea:
    title: str
    why: str
    action: str
    keywords: list
    format: str
    confidence: str
    estimated_boost: str


@dataclass
class AnalysisResult:
    username: str
    niche: str
    top_themes: list
    top_hashtags: list
    content_ideas: list
    posting_insights: dict
    summary: str
    raw_claude_response: str
    error: Optional[str] = None


def _summarize_posts(profile: ProfileData) -> tuple[str, dict]:
    """
    Build a post summary string and a stats dict from real data only.
    Returns (posts_text, stats) where stats contains only fields we actually have.
    """
    posts = profile.posts
    if not posts:
        return "(no posts retrieved)", {}

    lines = []
    total_likes = 0
    total_comments = 0
    total_views = 0
    view_count = 0
    format_counts = {}

    for i, p in enumerate(posts[:20]):
        cap = (p.caption or "")[:150].replace("\n", " ")
        views_str = ""
        if p.is_video and p.video_view_count:
            views_str = f", views={p.video_view_count:,}"
            total_views += p.video_view_count
            view_count += 1

        insights_str = ""
        if getattr(profile, "has_insights", False):
            parts = []
            if p.reach:       parts.append(f"reach={p.reach:,}")
            if p.impressions: parts.append(f"impr={p.impressions:,}")
            if p.saves:       parts.append(f"saves={p.saves:,}")
            if p.shares:      parts.append(f"shares={p.shares:,}")
            if parts:         insights_str = " | " + ", ".join(parts)

        lines.append(
            f"  {i+1}. [{p.typename}] likes={p.likes:,} comments={p.comments:,}{views_str}{insights_str} | {cap}"
        )

        total_likes += p.likes
        total_comments += p.comments
        fmt = p.typename
        format_counts[fmt] = format_counts.get(fmt, 0) + 1

    n = len(posts)
    stats = {
        "post_count": n,
        "avg_likes": round(total_likes / n) if n else 0,
        "avg_comments": round(total_comments / n) if n else 0,
        "format_breakdown": format_counts,
    }
    if view_count:
        stats["avg_views_on_videos"] = round(total_views / view_count)

    return "\n".join(lines), stats


def _build_prompt(profile: ProfileData) -> str:
    has_real_data = profile.followers > 0 or len(profile.posts) > 0

    if not has_real_data:
        # No data at all — tell Claude to admit it can't analyze
        return f"""You are an Instagram content strategist.

You were asked to analyze @{profile.username} but NO real Instagram data was retrieved for this account.

Return this exact JSON and nothing else:
{{
  "niche": "",
  "full_name": "",
  "biography": "",
  "followers": 0,
  "is_verified": false,
  "summary": "We could not retrieve data for this account. Make sure the username is correct and the account is public.",
  "top_themes": [],
  "top_hashtags": [],
  "posting_insights": {{}},
  "content_ideas": []
}}"""

    posts_text, stats = _summarize_posts(profile)
    data_label = "FULL CREATOR INSIGHTS" if getattr(profile, "has_insights", False) else "PUBLIC DATA"

    # Build hashtag list from actual captions
    all_hashtags: dict[str, int] = {}
    for p in profile.posts:
        for tag in p.hashtags:
            all_hashtags[tag] = all_hashtags.get(tag, 0) + 1
    top_tags = sorted(all_hashtags.items(), key=lambda x: -x[1])[:20]
    tags_str = ", ".join(f"#{t[0]}({t[1]}x)" for t in top_tags) if top_tags else "none found"

    return f"""You are an expert Instagram content strategist.

REAL INSTAGRAM DATA for @{profile.username} [{data_label}]:
- Name: {profile.full_name or "unknown"}
- Bio: {profile.biography or "none"}
- Followers: {profile.followers:,}
- Total posts: {profile.post_count:,}
- Verified: {profile.is_verified}
- Avg likes per post: {stats.get("avg_likes", 0):,}
- Avg comments per post: {stats.get("avg_comments", 0):,}
{f"- Avg views on video posts: {stats.get('avg_views_on_videos', 0):,}" if stats.get("avg_views_on_videos") else ""}
- Post format breakdown: {stats.get("format_breakdown", {})}
- Hashtags actually used: {tags_str}

Recent {stats.get("post_count", 0)} posts:
{posts_text}

YOUR JOB:
Look at the data above. Find which post types got the MOST likes/views/saves. Find patterns in what topics performed best. Recommend exactly what to post next to maximize views.

STRICT RULES — you will be penalized for breaking these:
1. ONLY reference numbers that appear in the data above. Do NOT invent engagement numbers.
2. Base "estimated_boost" on the actual gap between the best and worst performing posts above.
3. If you don't have enough data to calculate something, say "not enough data" — do NOT guess.
4. "why" = one sentence, max 12 words, plain English, no jargon.
5. "action" = one sentence telling them exactly what to film/create.

Return ONLY this JSON:
{{
  "niche": "2-4 word niche label based on their actual posts",
  "full_name": "{profile.full_name or ""}",
  "biography": "{(profile.biography or "").replace('"', "'")[:120]}",
  "followers": {profile.followers},
  "is_verified": {str(profile.is_verified).lower()},
  "summary": "2 sentences. What content type is performing best based on the data. What their biggest opportunity is.",
  "top_themes": [
    {{"theme": "topic name from actual posts", "avg_engagement": real_number_from_data, "post_count": real_count}}
  ],
  "top_hashtags": [
    {{"tag": "tag_without_hash", "frequency": real_count_from_data, "avg_engagement": real_number_or_0}}
  ],
  "posting_insights": {{
    "best_format": "the format type with highest avg likes from the data",
    "best_format_reason": "one sentence using actual numbers from the data",
    "posting_frequency_tip": "one practical tip",
    "audience_insight": "one insight about what their audience actually engages with based on the data"
  }},
  "content_ideas": [
    {{
      "title": "punchy post title under 10 words",
      "why": "one sentence, max 12 words, plain English",
      "action": "exactly what to film or create, one sentence",
      "keywords": ["hashtag1", "hashtag2", "hashtag3", "hashtag4", "hashtag5"],
      "format": "Reel|Carousel|Image",
      "confidence": "High|Medium|Low",
      "estimated_boost": "+X% vs your average" or "not enough data"
    }}
  ]
}}

Provide exactly 5 content_ideas. Return ONLY the JSON."""


def analyze_profile(profile: ProfileData, api_key: str) -> AnalysisResult:
    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": _build_prompt(profile)}],
        )
        raw = message.content[0].text.strip()
    except Exception as e:
        return AnalysisResult(
            username=profile.username,
            niche="", top_themes=[], top_hashtags=[],
            content_ideas=[], posting_insights={},
            summary="", raw_claude_response="",
            error=f"Claude API error: {e}",
        )

    try:
        clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE)
        data = json.loads(clean.strip())
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nRaw: {raw[:500]}")
        return AnalysisResult(
            username=profile.username,
            niche="", top_themes=[], top_hashtags=[],
            content_ideas=[], posting_insights={},
            summary="", raw_claude_response=raw,
            error=f"Failed to parse AI response: {e}",
        )

    # Only fill profile fields Claude could legitimately know (name/bio from scrape)
    # Never overwrite followers with a hallucinated number
    if not profile.full_name:
        profile.full_name = data.get("full_name", "")
    if not profile.biography:
        profile.biography = data.get("biography", "")

    ideas = [
        ContentIdea(
            title=i.get("title", ""),
            why=i.get("why", ""),
            action=i.get("action", ""),
            keywords=i.get("keywords", []),
            format=i.get("format", ""),
            confidence=i.get("confidence", ""),
            estimated_boost=i.get("estimated_boost", ""),
        )
        for i in data.get("content_ideas", [])
    ]

    return AnalysisResult(
        username=profile.username,
        niche=data.get("niche", ""),
        top_themes=data.get("top_themes", []),
        top_hashtags=data.get("top_hashtags", []),
        content_ideas=ideas,
        posting_insights=data.get("posting_insights", {}),
        summary=data.get("summary", ""),
        raw_claude_response=raw,
    )
