#!/bin/bash
# macOS/Linux launcher: double-click in Finder, or run ./run.command [folder]
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Please install Python 3 from python.org"; read -r -p "Press Enter"; exit 1; }
python3 gilddesign.py extract "$@"
read -r -p "Press Enter to close"
