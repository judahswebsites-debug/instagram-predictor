"""
AI analysis engine.
Takes ProfileData (with optional web_research) → Claude → content predictions.
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
    prompt = f"""You are an Instagram content strategy expert — like an Amazon keyword researcher, but optimizing for VIEWS instead of purchases.

## Profile
- Username: @{profile.username}
- Name: {profile.full_name}
- Bio: {profile.biography}
- Followers: {profile.followers:,}
- Following: {profile.following:,}
- Total Posts: {profile.post_count}
- Verified: {profile.is_verified}
"""

    if profile.web_research:
        prompt += f"""
## Public Web Research
The following was gathered from public web search results about this creator:

{profile.web_research}
"""

    prompt += """
---

Based on everything above, perform a deep content strategy analysis. Predict exactly what this creator should post next to MAXIMIZE views — like finding high-value keywords for an Amazon listing.

Even if data is limited, use your knowledge of Instagram trends, the creator's apparent niche, and content strategy best practices to give strong, specific recommendations.

Return your analysis as valid JSON with this exact structure:
{
  "niche": "2-4 word description of creator's niche",
  "summary": "2-3 sentence summary of what's working and the biggest content opportunity",
  "top_themes": [
    {"theme": "string", "avg_engagement": 0, "post_count": 0}
  ],
  "top_hashtags": [
    {"tag": "string", "frequency": 1, "avg_engagement": 0}
  ],
  "posting_insights": {
    "best_format": "Reels|Carousels|Images|Mixed",
    "best_format_reason": "string",
    "posting_frequency_tip": "string",
    "audience_insight": "string"
  },
  "content_ideas": [
    {
      "title": "Specific, actionable video/post title",
      "why": "Why this will perform well based on the research",
      "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
      "format": "Reel|Carousel|Video|Image",
      "confidence": "High|Medium|Low",
      "estimated_boost": "+X-Y% views vs avg"
    }
  ]
}

Requirements:
- Provide exactly 5 content_ideas, ranked by predicted performance
- Keywords are caption/hashtag terms that maximize discoverability
- Be specific and actionable — name actual topics, formats, hooks
- Return ONLY the JSON object, no other text"""

    return prompt


def analyze_profile(profile: ProfileData, api_key: str) -> AnalysisResult:
    if profile.error and not profile.web_research:
        return AnalysisResult(
            username=profile.username,
            niche="", top_themes=[], top_hashtags=[],
            content_ideas=[], posting_insights={},
            summary="", raw_claude_response="",
            error=profile.error,
        )

    prompt = _build_prompt(profile)
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
