#!/bin/bash
# Instagram Content Predictor — quick start
set -e

echo ""
echo "📦  Installing dependencies..."
pip install flask flask-cors instaloader anthropic requests beautifulsoup4 python-dotenv --break-system-packages -q

echo ""
echo "🚀  Starting server at http://localhost:5000"
echo ""

# Copy .env.example → .env if no .env exists yet
if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "⚠️  Created .env from .env.example — edit it to add your ANTHROPIC_API_KEY"
  echo ""
fi

python app.py
