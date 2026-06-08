"""
AI analysis engine.
Uses Claude's knowledge of Instagram creators to generate content predictions.
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


def _build_prompt(username: str) -> str:
    return f"""You are an expert Instagram content strategist — like an Amazon keyword researcher, but optimizing for VIEWS instead of purchases.

Analyze the Instagram creator @{username}.

Use everything you know about this creator: their niche, content style, what topics they cover, their audience, their most viral posts, engagement patterns, and what content performs best for them.

If you're not familiar with this specific creator, use your knowledge of their apparent niche (based on the username) and Instagram content trends in that space to give strong, specific recommendations.

Your job: predict exactly what they should post next to MAXIMIZE views.

Return your full analysis as valid JSON with this exact structure:
{{
  "niche": "2-4 word description of creator's niche",
  "full_name": "creator's real name if known, else empty string",
  "biography": "brief description of who this creator is and what they post",
  "followers": estimated follower count as integer (0 if unknown),
  "is_verified": true or false,
  "summary": "2-3 sentence summary of what's working for this creator and their biggest content opportunity",
  "top_themes": [
    {{"theme": "content theme name", "avg_engagement": estimated_number, "post_count": estimated_posts}}
  ],
  "top_hashtags": [
    {{"tag": "hashtag without #", "frequency": estimated_uses, "avg_engagement": estimated_number}}
  ],
  "posting_insights": {{
    "best_format": "Reels|Carousels|Images|Mixed",
    "best_format_reason": "why this format works for them",
    "posting_frequency_tip": "recommended posting cadence",
    "audience_insight": "key insight about their audience"
  }},
  "content_ideas": [
    {{
      "title": "Specific, compelling video/post title they should make",
      "why": "Data-backed or trend-backed reason this will get more views",
      "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
      "format": "Reel|Carousel|Video|Image",
      "confidence": "High|Medium|Low",
      "estimated_boost": "+X-Y% views vs their average"
    }}
  ]
}}

Requirements:
- Provide exactly 5 content_ideas ranked by predicted performance (best first)
- Keywords = specific caption/hashtag words that maximize discoverability for this content
- Be specific — name real topics, hooks, formats that fit this creator
- If you don't know the creator well, still give 5 strong ideas based on their niche
- Return ONLY the JSON object, no other text"""


def analyze_profile(profile: ProfileData, api_key: str) -> AnalysisResult:
    client = anthropic.Anthropic(api_key=api_key)

    try:
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": _build_prompt(profile.username)}],
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

    # Enrich the profile with what Claude knows
    profile.full_name = data.get("full_name", "")
    profile.biography = data.get("biography", "")
    profile.followers = data.get("followers", 0)
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
