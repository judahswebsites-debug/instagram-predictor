"""
Instagram Content Predictor — Flask backend
Run: python app.py
Then open http://localhost:5000
"""

import os
import logging
from dataclasses import asdict

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv

from scraper import scrape_profile
from analyzer import analyze_profile

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    return jsonify({
        "status": "ok",
        "api_key_configured": bool(api_key and api_key != "your_anthropic_api_key_here"),
    })


@app.route("/api/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json(force=True) or {}
        username = (data.get("username") or "").strip().lstrip("@")
        password = (data.get("password") or "").strip()
        api_key = (data.get("api_key") or os.getenv("ANTHROPIC_API_KEY") or "").strip()
        max_posts = min(int(data.get("max_posts", 20)), 30)

        if not username:
            return jsonify({"error": "Username is required"}), 400
        if not api_key or api_key == "your_anthropic_api_key_here":
            return jsonify({"error": "Anthropic API key is required. Get one at console.anthropic.com"}), 400

        logger.info(f"Analyzing @{username} (max_posts={max_posts})")

        # Step 1: Research
        profile = scrape_profile(username, password=password, max_posts=max_posts)
        if profile.error and not profile.web_research:
            return jsonify({"error": profile.error}), 422

        # Step 2: Analyze
        result = analyze_profile(profile, api_key)
        if result.error and not result.content_ideas:
            return jsonify({"error": result.error}), 422

        response = {
            "username": result.username,
            "niche": result.niche,
            "summary": result.summary,
            "profile": {
                "full_name": profile.full_name,
                "biography": profile.biography,
                "followers": profile.followers,
                "following": profile.following,
                "post_count": profile.post_count,
                "is_verified": profile.is_verified,
                "profile_pic_url": profile.profile_pic_url,
                "posts_analyzed": len(profile.posts),
                "warning": profile.error,
            },
            "top_themes": result.top_themes,
            "top_hashtags": result.top_hashtags,
            "posting_insights": result.posting_insights,
            "content_ideas": [asdict(idea) for idea in result.content_ideas],
        }
        return jsonify(response)

    except Exception as e:
        logger.exception("Unhandled error in /api/analyze")
        return jsonify({"error": f"Server error: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("RENDER") is None  # disable debug mode on Render
    print(f"\n🚀  Instagram Content Predictor running at http://localhost:{port}\n")
    app.run(debug=debug, host="0.0.0.0", port=port)
