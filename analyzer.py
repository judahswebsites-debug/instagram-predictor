"""
AI analysis engine.
Takes scraped ProfileData → sends structured prompt to Claude → returns predictions.
"""

import json
import re
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Optional

import anthropic

from scraper import ProfileData, Post

logger = logging.getLogger(__name__)


@dataclass
class ContentIdea:
    title: str
    why: str
    keywords: list[str]
    format: str          # Reel, Carousel, Video, Story
    confidence: str      # High / Medium / Low
    estimated_boost: str # e.g. "+30-50% views"


@dataclass
class AnalysisResult:
    username: str
    niche: str
    top_themes: list[dict]           # [{"theme": ..., "avg_engagement": ..., "post_count": ...}]
    top_hashtags: list[dict]         # [{"tag": ..., "frequency": ..., "avg_engagement": ...}]
    content_ideas: list[ContentIdea]
    posting_insights: dict
    summary: str
    raw_claude_response: str
    error: Optional[str] = None


def _compute_engagement(post: Post) -> int:
    """Proxy engagement metric. Prefer view count for videos, else likes + comments."""
    if post.is_video and post.video_view_count:
        return post.video_view_count
    return post.likes + post.comments * 2  # weight comments more


def _extract_themes(posts: list[Post]) -> list[dict]:
    """
    Heuristic theme extraction from captions.
    Returns top themes with avg engagement.
    """
    word_scores: dict[str, list[int]] = {}
    for post in posts:
        eng = _compute_engagement(post)
        words = re.findall(r"\b[a-zA-Z]{4,}\b", post.caption.lower())
        STOP = {
            "this", "that", "with", "have", "from", "they", "will", "been",
            "when", "your", "more", "like", "just", "make", "what", "some",
            "than", "then", "into", "also", "only", "about", "would", "could",
            "their", "there", "which", "were", "being", "these", "those",
        }
        for w in set(words) - STOP:
            word_scores.setdefault(w, []).append(eng)

    themes = []
    for word, scores in word_scores.items():
        if len(scores) >= 2:
            themes.append({
                "theme": word,
                "avg_engagement": round(sum(scores) / len(scores)),
                "post_count": len(scores),
            })

    themes.sort(key=lambda x: x["avg_engagement"] * x["post_count"], reverse=True)
    return themes[:15]


def _extract_hashtag_stats(posts: list[Post]) -> list[dict]:
    tag_eng: dict[str, list[int]] = {}
    for post in posts:
        eng = _compute_engagement(post)
        for tag in post.hashtags:
            tag_eng.setdefault(tag.lower(), []).append(eng)

    stats = []
    for tag, engs in tag_eng.items():
        stats.append({
            "tag": tag,
            "frequency": len(engs),
            "avg_engagement": round(sum(engs) / len(engs)),
        })

    stats.sort(key=lambda x: x["avg_engagement"] * x["frequency"], reverse=True)
    return stats[:20]


def _build_prompt(profile: ProfileData, themes: list[dict], hashtag_stats: list[dict]) -> str:
    posts_summary = []
    sorted_posts = sorted(profile.posts, key=_compute_engagement, reverse=True)
    for p in sorted_posts[:15]:
        eng = _compute_engagement(p)
        posts_summary.append({
            "caption_preview": p.caption[:200],
            "hashtags": p.hashtags[:10],
            "engagement_score": eng,
            "format": "Video/Reel" if p.is_video else ("Carousel" if p.typename == "GraphSidecar" else "Image"),
            "views": p.video_view_count if p.is_video else None,
            "likes": p.likes,
            "comments": p.comments,
        })

    video_count = sum(1 for p in profile.posts if p.is_video)
    image_count = len(profile.posts) - video_count
    avg_engagement = (
        round(sum(_compute_engagement(p) for p in profile.posts) / len(profile.posts))
        if profile.posts else 0
    )

    prompt = f"""You are an Instagram content strategy expert — think of yourself as an Amazon keyword research tool, but instead of optimizing for purchases, you're optimizing for VIEWS and ENGAGEMENT.

## Profile Data
- Username: @{profile.username}
- Full Name: {profile.full_name}
- Bio: {profile.biography}
- Followers: {profile.followers:,}
- Following: {profile.following:,}
- Total Posts: {profile.post_count}
- Verified: {profile.is_verified}

## Content Mix (last {len(profile.posts)} posts)
- Videos/Reels: {video_count} ({round(video_count/max(len(profile.posts),1)*100)}%)
- Images/Carousels: {image_count} ({round(image_count/max(len(profile.posts),1)*100)}%)
- Average Engagement Score: {avg_engagement:,}

## Top Performing Posts (by engagement)
{json.dumps(posts_summary, indent=2)}

## Top Content Themes (by performance)
{json.dumps(themes[:10], indent=2)}

## Top Hashtags (by performance)
{json.dumps(hashtag_stats[:15], indent=2)}

---

Based on this data, perform a deep content strategy analysis. Your job is to predict exactly what this creator should post next to MAXIMIZE views — like finding high-value keywords for an Amazon listing.

Return your analysis as valid JSON with this exact structure:
{{
  "niche": "2-4 word description of creator's niche",
  "summary": "2-3 sentence executive summary of what's working and what the big opportunity is",
  "top_themes": [
    {{"theme": "string", "avg_engagement": number, "post_count": number}}
  ],
  "top_hashtags": [
    {{"tag": "string", "frequency": number, "avg_engagement": number}}
  ],
  "posting_insights": {{
    "best_format": "Reels|Carousels|Images|Mixed",
    "best_format_reason": "string",
    "posting_frequency_tip": "string",
    "audience_insight": "string"
  }},
  "content_ideas": [
    {{
      "title": "Specific, actionable video/post title",
      "why": "Data-backed reason this will perform well",
      "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
      "format": "Reel|Carousel|Video|Image",
      "confidence": "High|Medium|Low",
      "estimated_boost": "+X-Y% views vs avg"
    }}
  ]
}}

Requirements:
- Provide exactly 5 content_ideas, ranked by predicted performance (highest first)
- Each content idea must reference specific data from the posts (e.g. "posts about X average 3x more views")
- Keywords should be caption/hashtag keywords that will help this content get discovered — like SEO keywords
- Be specific and actionable, not generic
- confidence should reflect how strongly the data supports the prediction

Return ONLY the JSON object, no other text."""

    return prompt


def analyze_profile(profile: ProfileData, api_key: str) -> AnalysisResult:
    if profile.error and not profile.posts:
        return AnalysisResult(
            username=profile.username,
            niche="", top_themes=[], top_hashtags=[],
            content_ideas=[], posting_insights={},
            summary="", raw_claude_response="",
            error=profile.error,
        )

    themes = _extract_themes(profile.posts)
    hashtag_stats = _extract_hashtag_stats(profile.posts)
    prompt = _build_prompt(profile, themes, hashtag_stats)

    client = anthropic.Anthropic(api_key=api_key)
    try:
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
    except Exception as e:
        return AnalysisResult(
            username=profile.username,
            niche="", top_themes=themes, top_hashtags=hashtag_stats,
            content_ideas=[], posting_insights={},
            summary="", raw_claude_response="",
            error=f"Claude API error: {e}",
        )

    # Parse JSON response
    try:
        # Strip markdown code fences if present
        clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE)
        data = json.loads(clean.strip())
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}\nRaw: {raw[:500]}")
        return AnalysisResult(
            username=profile.username,
            niche="", top_themes=themes, top_hashtags=hashtag_stats,
            content_ideas=[], posting_insights={},
            summary="", raw_claude_response=raw,
            error=f"Failed to parse AI response: {e}",
        )

    ideas = []
    for item in data.get("content_ideas", []):
        ideas.append(ContentIdea(
            title=item.get("title", ""),
            why=item.get("why", ""),
            keywords=item.get("keywords", []),
            format=item.get("format", ""),
            confidence=item.get("confidence", ""),
            estimated_boost=item.get("estimated_boost", ""),
        ))

    return AnalysisResult(
        username=profile.username,
        niche=data.get("niche", ""),
        top_themes=data.get("top_themes", themes),
        top_hashtags=data.get("top_hashtags", hashtag_stats),
        content_ideas=ideas,
        posting_insights=data.get("posting_insights", {}),
        summary=data.get("summary", ""),
        raw_claude_response=raw,
    )
