#!/bin/bash
# One-time setup on your Mac: keeps a copy of the repo, stores your Substack cookie
# locally, and installs a launchd job that creates each morning's Substack draft.
#
#   curl -fsSL https://raw.githubusercontent.com/kfopp-wonder/furniture-brief/main/scripts/install_mac.sh | bash
#
set -euo pipefail
REPO_URL="https://github.com/kfopp-wonder/furniture-brief.git"
APP="$HOME/furniture-brief"
HOME_DIR="$HOME/.furniture-brief"
PLIST="$HOME/Library/LaunchAgents/com.furniturebrief.substack.plist"

echo "→ repo"
if [ -d "$APP/.git" ]; then git -C "$APP" pull -q --rebase; else git clone -q "$REPO_URL" "$APP"; fi

echo "→ python environment (requests, PyYAML, curl_cffi only)"
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q requests PyYAML curl_cffi

mkdir -p "$HOME_DIR"; chmod 700 "$HOME_DIR"
if [ ! -s "$HOME_DIR/substack.sid" ]; then
  echo
  echo "Paste the value of your substack.sid cookie (Chrome: DevTools → Application → Cookies → https://substack.com):"
  read -r SID < /dev/tty
  printf '%s' "$SID" > "$HOME_DIR/substack.sid"; chmod 600 "$HOME_DIR/substack.sid"
fi

echo "→ verifying the cookie"
"$APP/.venv/bin/python" "$APP/scripts/substack_local.py" --check

echo "→ launchd job (every 15 minutes while the Mac is awake)"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.furniturebrief.substack</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-lc</string>
    <string>cd "$APP" && git pull -q --rebase origin main || true; "$APP/.venv/bin/python" "$APP/scripts/substack_local.py"</string>
  </array>
  <key>StartInterval</key><integer>900</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$HOME_DIR/launchd.out</string>
  <key>StandardErrorPath</key><string>$HOME_DIR/launchd.err</string>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo
echo "Done. Drafts will appear under Substack → Dashboard → Posts → Drafts within 15 minutes of each edition"
echo "(the edition is generated at ~5:45am ET; the Mac must be awake). Log: $HOME_DIR/substack_local.log"
echo "To create today's draft right now:  $APP/.venv/bin/python $APP/scripts/substack_local.py --force --open"
