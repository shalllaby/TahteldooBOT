#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo "Starting Taht El Doo Web Server on http://0.0.0.0:8000..."
python3 web_server.py
