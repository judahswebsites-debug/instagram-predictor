"""
AI analysis engine.
Returns: what's working, what's not, and 3 next video recommendations with posting times.
Strictly uses only real scraped data — no hallucination.
"""

import json
import re
import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone

import anthropic
from scraper import ProfileData

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    username: str
    niche: str
    summary: str
    whats_working: list
    whats_not_working: list
    best_posting_time: dict
    next_videos: list
    top_hashtags: list
    raw_claude_response: str
    error: Optional[str] = None


def _parse_timestamp(ts: str):
    """Try to parse an ISO timestamp string into a datetime."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.utcfromtimestamp(int(ts)).replace(tzinfo=timezone.utc)
        except Exception:
            return None


def _summarize_posts(profile: ProfileData) -> tuple[str, dict]:
    posts = profile.posts
    if not posts:
        return "(no posts retrieved)", {}

    lines = []
    total_likes = 0
    total_comments = 0
    total_views = 0
    view_count = 0
    format_counts = {}
    format_likes: dict[str, list] = {}

    for i, p in enumerate(posts[:20]):
        cap = (p.caption or "")[:120].replace("\n", " ")
        views_str = ""
        if p.is_video and p.video_view_count:
            views_str = f", views={p.video_view_count:,}"
            total_views += p.video_view_count
            view_count += 1

        # Day + hour from timestamp for timing analysis
        dt = _parse_timestamp(p.timestamp)
        time_str = f", posted={dt.strftime('%a %I%p UTC')}" if dt else ""

        # Link to the post
        link_str = f", link=instagram.com/p/{p.shortcode}/" if p.shortcode else ""

        lines.append(
            f"  Post {i+1}. [{p.typename}] likes={p.likes:,} comments={p.comments:,}{views_str}{time_str}{link_str} | {cap}"
        )

        total_likes += p.likes
        total_comments += p.comments
        fmt = p.typename
        format_counts[fmt] = format_counts.get(fmt, 0) + 1
        format_likes.setdefault(fmt, []).append(p.likes)

    n = len(posts)
    avg_by_format = {
        fmt: round(sum(lks) / len(lks)) for fmt, lks in format_likes.items()
    }
    stats = {
        "post_count": n,
        "avg_likes": round(total_likes / n) if n else 0,
        "avg_comments": round(total_comments / n) if n else 0,
        "format_breakdown": format_counts,
        "avg_likes_by_format": avg_by_format,
    }
    if view_count:
        stats["avg_views_on_videos"] = round(total_views / view_count)

    return "\n".join(lines), stats


def _build_prompt(profile: ProfileData) -> str:
    has_real_data = profile.followers > 0 or len(profile.posts) > 0

    if not has_real_data:
        return f"""You are an Instagram analyst. No data was retrieved for @{profile.username}.
Return ONLY this JSON:
{{"niche":"","summary":"Could not retrieve data. Check the username is correct and the account is public.","whats_working":[],"whats_not_working":[],"best_posting_time":{{}},"next_videos":[],"top_hashtags":[]}}"""

    posts_text, stats = _summarize_posts(profile)

    all_hashtags: dict[str, int] = {}
    for p in profile.posts:
        for tag in p.hashtags:
            all_hashtags[tag] = all_hashtags.get(tag, 0) + 1
    top_tags = sorted(all_hashtags.items(), key=lambda x: -x[1])[:20]
    tags_str = ", ".join(f"#{t[0]}({t[1]}x)" for t in top_tags) if top_tags else "none found"

    return f"""You are an expert Instagram content strategist and data analyst.

REAL DATA for @{profile.username}:
- Followers: {profile.followers:,}
- Bio: {profile.biography or "none"}
- Avg likes per post: {stats.get("avg_likes", 0):,}
- Avg comments per post: {stats.get("avg_comments", 0):,}
{f"- Avg views on video posts: {stats.get('avg_views_on_videos', 0):,}" if stats.get("avg_views_on_videos") else ""}
- Format breakdown: {stats.get("format_breakdown", {})}
- Avg likes by format: {stats.get("avg_likes_by_format", {})}
- Hashtags used: {tags_str}

All posts with engagement + posting day/time:
{posts_text}

INSTRUCTIONS:
Analyze the data above. Use ONLY real numbers from the data.

1. WHATS_WORKING: Find 3-4 patterns where posts performed ABOVE average. Use exact numbers. Reference specific post links where relevant.
2. WHATS_NOT_WORKING: Find 2-3 patterns where posts underperformed. Use exact numbers.
3. BEST_POSTING_TIME: Look at the "posted=Day Hour" on high-performing posts. Find the best day + time.
4. NEXT_VIDEOS: Give 3 specific video ideas. Each must have a posting day + time based on the timing analysis. Each must explain exactly what to film.

RULES:
- Use ONLY numbers from the data above. Never invent stats.
- Post links format: https://www.instagram.com/p/SHORTCODE/
- If timing data is missing, recommend generally accepted best times for the niche.
- Keep language simple — 7th grade level.
- estimated_boost must be based on the gap between best and worst posts in the data.

Return ONLY this JSON (no markdown, no extra text):
{{
  "niche": "2-4 word niche",
  "summary": "2 sentences: what's working best and the biggest opportunity.",
  "whats_working": [
    {{
      "finding": "Short headline (under 8 words)",
      "detail": "1-2 sentences with exact numbers from the data",
      "post_link": "https://www.instagram.com/p/SHORTCODE/ or empty string"
    }}
  ],
  "whats_not_working": [
    {{
      "finding": "Short headline (under 8 words)",
      "detail": "1-2 sentences with exact numbers from the data"
    }}
  ],
  "best_posting_time": {{
    "day": "Day of week",
    "time": "H:MM AM/PM EST",
    "reasoning": "One sentence explaining why based on the data"
  }},
  "next_videos": [
    {{
      "number": 1,
      "title": "Exact post title to use (under 10 words)",
      "post_day": "Day of week",
      "post_time": "H:MM AM/PM EST",
      "format": "Reel|Carousel|Image",
      "hook": "The first 3 seconds / opening line to use",
      "what_to_film": "Exactly what to film or create. 1-2 sentences.",
      "must_include": ["specific element 1", "specific element 2", "specific element 3"],
      "hashtags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
      "why": "One sentence: why this will outperform based on the data",
      "estimated_boost": "+X% vs your average based on similar posts"
    }}
  ],
  "top_hashtags": [
    {{"tag": "tagname", "frequency": number, "avg_engagement": number}}
  ]
}}

Provide exactly 3 next_videos and exactly 3-4 whats_working items. Return ONLY the JSON."""


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
            username=profile.username, niche="", summary="",
            whats_working=[], whats_not_working=[],
            best_posting_time={}, next_videos=[], top_hashtags=[],
            raw_claude_response="", error=f"Claude API error: {e}",
        )

    try:
        clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE)
        data = json.loads(clean.strip())
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nRaw: {raw[:500]}")
        return AnalysisResult(
            username=profile.username, niche="", summary="",
            whats_working=[], whats_not_working=[],
            best_posting_time={}, next_videos=[], top_hashtags=[],
            raw_claude_response=raw, error=f"Failed to parse AI response: {e}",
        )

    if not profile.full_name:
        profile.full_name = data.get("full_name", "")
    if not profile.biography:
        profile.biography = data.get("biography", "")

    return AnalysisResult(
        username=profile.username,
        niche=data.get("niche", ""),
        summary=data.get("summary", ""),
        whats_working=data.get("whats_working", []),
        whats_not_working=data.get("whats_not_working", []),
        best_posting_time=data.get("best_posting_time", {}),
        next_videos=data.get("next_videos", []),
        top_hashtags=data.get("top_hashtags", []),
        raw_claude_response=raw,
    )
