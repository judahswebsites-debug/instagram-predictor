"""
AI analysis engine.
Uses real scraped Instagram data + Claude to generate content predictions.
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


def _build_prompt(profile: ProfileData) -> str:
    username = profile.username
    has_real_data = profile.followers > 0 or len(profile.posts) > 0

    if has_real_data:
        post_lines = []
        for i, p in enumerate(profile.posts[:20]):
            cap = (p.caption or "")[:200].replace("\n", " ")
            views = f", {p.video_view_count:,} views" if p.is_video and p.video_view_count else ""
            post_lines.append(
                f"  {i+1}. [{p.typename}] likes={p.likes:,} comments={p.comments:,}{views} | {cap}"
            )
        posts_text = "\n".join(post_lines) if post_lines else "  (no posts retrieved)"

        context = f"""REAL INSTAGRAM DATA for @{username}:
- Full name: {profile.full_name or "unknown"}
- Bio: {profile.biography or "none"}
- Followers: {profile.followers:,}
- Following: {profile.following:,}
- Total posts: {profile.post_count:,}
- Verified: {profile.is_verified}
- Recent posts analyzed ({len(profile.posts)} posts):
{posts_text}"""
    else:
        context = f"""No live Instagram data was retrieved for @{username}.
Use your training knowledge about this creator to fill in the analysis."""

    return f"""You are an expert Instagram content strategist — like an Amazon keyword researcher, but optimizing for VIEWS instead of purchases.

{context}

Your job: analyze this creator's content and predict exactly what they should post next to MAXIMIZE views.

Look at which posts got the most likes/views, what topics recur, what hashtags they use, and what their audience responds to. Then give 5 specific, data-backed content ideas.

Return your full analysis as valid JSON with this exact structure:
{{
  "niche": "2-4 word description of creator's niche",
  "full_name": "creator's real name if known, else empty string",
  "biography": "brief description of who this creator is and what they post",
  "followers": {profile.followers if profile.followers else 0},
  "is_verified": {str(profile.is_verified).lower()},
  "summary": "2-3 sentence summary of what's working for this creator and their biggest content opportunity",
  "top_themes": [
    {{"theme": "content theme name", "avg_engagement": number, "post_count": number}}
  ],
  "top_hashtags": [
    {{"tag": "hashtag without #", "frequency": number, "avg_engagement": number}}
  ],
  "posting_insights": {{
    "best_format": "Reels|Carousels|Images|Mixed",
    "best_format_reason": "why this format works for them",
    "posting_frequency_tip": "recommended posting cadence",
    "audience_insight": "key insight about their audience"
  }},
  "content_ideas": [
    {{
      "title": "Short, punchy post title (under 10 words)",
      "why": "One simple sentence explaining why this will get more views. No jargon. 7th grade level. Do NOT reference specific past posts.",
      "action": "One sentence on exactly what to film or create. Very simple and direct.",
      "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
      "format": "Reel|Carousel|Video|Image",
      "confidence": "High|Medium|Low",
      "estimated_boost": "+X-Y% views vs their average"
    }}
  ]
}}

Requirements:
- Provide exactly 5 content_ideas ranked by predicted performance (best first)
- Keep ALL text short and simple — 7th grade reading level
- "why" must be ONE sentence, no more than 15 words, no mention of past posts
- "action" tells them exactly what to do in plain English
- Keywords = hashtags that will help this content get discovered
- Return ONLY the JSON object, no other text"""


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

    # Fill profile fields from Claude if scraper didn't get them
    if not profile.full_name:
        profile.full_name = data.get("full_name", "")
    if not profile.biography:
        profile.biography = data.get("biography", "")
    if not profile.followers:
        profile.followers = data.get("followers", 0)
    if not profile.is_verified:
        profile.is_verified = data.get("is_verified", False)

    ideas = [
        ContentIdea(
            title=i.get("title", ""),
            why=i.get("why", ""),
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
