#!/bin/bash
# Start Cloudflare quick tunnel and print the URL
# Usage: bash scripts/tunnel.sh

# Kill existing cloudflared if running
pkill -f cloudflared 2>/dev/null
sleep 1

echo "Starting Cloudflare tunnel to http://localhost:8000 ..."
cloudflared tunnel --url http://localhost:8000 2>&1 | while read line; do
    echo "$line"
    # Extract the trycloudflare.com URL
    if echo "$line" | grep -q "trycloudflare.com"; then
        URL=$(echo "$line" | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com')
        echo ""
        echo "============================================"
        echo "  WeChat Callback URL:"
        echo "  ${URL}/api/wechat/callback"
        echo "============================================"
        echo ""
    fi
done
