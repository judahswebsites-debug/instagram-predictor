#!/bin/bash
# Double-click this file to launch the Instagram Content Predictor

cd "$(dirname "$0")"

echo "============================================"
echo "  Instagram Content Predictor"
echo "============================================"
echo ""

# Install dependencies if needed
echo "Checking dependencies..."
pip3 install flask flask-cors instaloader anthropic requests beautifulsoup4 python-dotenv --break-system-packages -q 2>/dev/null || \
pip install flask flask-cors instaloader anthropic requests beautifulsoup4 python-dotenv --break-system-packages -q 2>/dev/null

echo ""
echo "Starting server..."
echo "Opening http://localhost:5000 in your browser..."
echo ""
echo "(Close this window to stop the app)"
echo ""

# Open browser after 2-second delay
sleep 2 && open "http://localhost:5000" &

# Start Flask
python3 app.py 2>/dev/null || python app.py
