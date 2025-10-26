#!/bin/bash

# Cleanup Script - Remove Autonomous Crawler & Old Dashboard
# This reduces codebase by ~70%

echo "🧹 Cleaning up NewsTrace codebase..."
echo ""

# Create backup directory
echo "📦 Creating backup..."
mkdir -p old_version
mv dashboard.py old_version/ 2>/dev/null
mv autonomous_crawler.py old_version/ 2>/dev/null
mv autonomous_app.py old_version/ 2>/dev/null
mv AUTONOMOUS_TEST_RESULTS.md old_version/ 2>/dev/null
mv app.py old_version/ 2>/dev/null
echo "✓ Backup created in ./old_version/"
echo ""

# Rename minimal version to main
echo "🔄 Activating minimal dashboard..."
cp dashboard_minimal.py dashboard.py
echo "✓ dashboard_minimal.py → dashboard.py"
echo ""

# Show file sizes
echo "📊 Code Reduction:"
echo "-------------------"
OLD_SIZE=$(wc -l old_version/dashboard.py 2>/dev/null | awk '{print $1}')
NEW_SIZE=$(wc -l dashboard.py | awk '{print $1}')
if [ -n "$OLD_SIZE" ]; then
    REDUCTION=$(echo "scale=1; (($OLD_SIZE - $NEW_SIZE) / $OLD_SIZE) * 100" | bc)
    echo "Old dashboard: $OLD_SIZE lines"
    echo "New dashboard: $NEW_SIZE lines"
    echo "Reduction: $REDUCTION%"
else
    echo "New dashboard: $NEW_SIZE lines"
fi
echo ""

# List remaining files
echo "✅ Clean codebase:"
echo "-------------------"
echo "Core Files:"
ls -lh dashboard.py utils/*.py scrapers/*.py deep_scraper.py 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}'
echo ""

echo "🎉 Cleanup complete!"
echo ""
echo "Next steps:"
echo "  1. Test: streamlit run dashboard.py"
echo "  2. Delete backup: rm -rf old_version"
echo "  3. Keep only README.md (docs): rm -f *.md; git checkout -- README.md"
echo ""
