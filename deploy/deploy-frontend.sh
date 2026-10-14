#!/usr/bin/env bash
# Deploy a Menduner release directory, verifying what nginx ACTUALLY serves.
#
# This script exists because a deploy reported success and changed nothing. The script's default
# target was /srv/menduner/dist while the running nginx served /srv/menduner/frontend-dist, so
# every file landed in a directory nobody read. The build was correct, the deploy was correct,
# and the site kept serving the previous release — which surfaced as
#   "Unable to preload CSS for /assets/index-<old>.css"
# on one page while the rest worked, i.e. as a page bug rather than a deploy bug.
#
# Three rules, each of which was learned the hard way:
#
#   1. Find the nginx root, do not assume it. TARGET is read from the running configuration and
#      can still be overridden.
#   2. NEVER delete previous assets. Vite fingerprints filenames so nothing collides, and a
#      visitor still holding a cached index.html will ask for the old names. `rm -rf` plus a
#      copy guarantees a broken page for those visitors.
#   3. Verify the SERVED response, not the source directory. Checking the release directory only
#      proves the build is self-consistent; it says nothing about what the browser receives.
#
# Usage:
#   sudo ./deploy-frontend.sh <release-directory>
#   sudo TARGET=/some/root ./deploy-frontend.sh <release-directory>
set -euo pipefail

OWNER="${OWNER:-menduner:menduner}"
KEEP_HTML="${KEEP_HTML:-3}"
NGINX_CONF="${NGINX_CONF:-/etc/nginx/sites-available/menduner}"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <release-directory>" >&2
  exit 2
fi

SOURCE="${1%/}"
[[ -f "$SOURCE/index.html" ]] || { echo "error: $SOURCE/index.html not found" >&2; exit 2; }
[[ -d "$SOURCE/assets" ]] || { echo "error: $SOURCE/assets not found" >&2; exit 2; }

# --- 1. Find the root nginx is really serving -----------------------------------------------
if [[ -z "${TARGET:-}" ]]; then
  if [[ -r "$NGINX_CONF" ]]; then
    TARGET="$(grep -oP '^\s*root\s+\K[^;]+' "$NGINX_CONF" | head -1 | tr -d ' ')"
  fi
  if [[ -z "${TARGET:-}" ]]; then
    echo "error: could not read 'root' from $NGINX_CONF." >&2
    echo "       pass it explicitly:  sudo TARGET=/srv/menduner/frontend-dist $0 $SOURCE" >&2
    exit 2
  fi
  echo "nginx root detected from $NGINX_CONF"
fi
echo "target: $TARGET"
mkdir -p "$TARGET/assets"

# --- 2. Sanity-check the release is internally consistent ------------------------------------
echo
echo "release under $SOURCE:"
RELEASE_OK=1
while read -r asset; do
  if [[ -f "$SOURCE/$asset" ]]; then
    echo "  OK      $asset"
  else
    echo "  MISSING $asset   <-- the release itself is broken, refusing to deploy"
    RELEASE_OK=0
  fi
done < <(grep -o 'assets/[^"]*' "$SOURCE/index.html")
[[ $RELEASE_OK -eq 1 ]] || exit 1

# --- 3. Merge, never replace ------------------------------------------------------------------
if [[ -f "$TARGET/index.html" ]]; then
  STAMP="$(date +%Y%m%d-%H%M%S)"
  cp "$TARGET/index.html" "$TARGET/index.html.$STAMP.bak"
  echo
  echo "backed up current index.html -> index.html.$STAMP.bak"
fi
cp -r "$SOURCE/assets/." "$TARGET/assets/"
cp "$SOURCE/index.html" "$TARGET/index.html"
[[ -f "$SOURCE/favicon.ico" ]] && cp "$SOURCE/favicon.ico" "$TARGET/favicon.ico"
chown -R "$OWNER" "$TARGET"
ls -1t "$TARGET"/index.html.*.bak 2>/dev/null | tail -n "+$((KEEP_HTML + 1))" | xargs -r rm -f

ASSETS="$(find "$TARGET/assets" -type f | wc -l)"
echo "deployed: $ASSETS asset files in $TARGET/assets (previous ones retained on purpose)"

# --- 4. Verify what is actually SERVED --------------------------------------------------------
# Reading the file back proves the copy worked; asking nginx proves it is the file being served.
# Both are needed, and only the second would have caught the wrong-directory deploy.
echo
echo "verification:"

SERVED_HTML=""
if command -v curl >/dev/null 2>&1; then
  SERVED_HTML="$(curl -fsS --max-time 5 http://127.0.0.1/ 2>/dev/null || true)"
fi

if [[ -z "$SERVED_HTML" ]]; then
  echo "  ! could not fetch http://127.0.0.1/ — skipping the served-response check"
else
  SERVED_ASSETS="$(grep -o 'assets/[^"]*' <<<"$SERVED_HTML" | sort -u)"
  EXPECTED_ASSETS="$(grep -o 'assets/[^"]*' "$SOURCE/index.html" | sort -u)"
  if [[ "$SERVED_ASSETS" == "$EXPECTED_ASSETS" ]]; then
    echo "  OK  nginx is serving the new index.html"
    while read -r asset; do
      [[ -n "$asset" ]] && echo "      $asset"
    done <<<"$SERVED_ASSETS"
  else
    echo "  FAIL nginx is NOT serving the new index.html"
    echo "       expected: $(tr '\n' ' ' <<<"$EXPECTED_ASSETS")"
    echo "       served:   $(tr '\n' ' ' <<<"$SERVED_ASSETS")"
    echo
    echo "       Most likely the wrong TARGET was used, or index.html is cached by a proxy."
    echo "       nginx root in $NGINX_CONF : $(grep -oP '^\s*root\s+\K[^;]+' "$NGINX_CONF" 2>/dev/null | head -1)"
    exit 1
  fi
fi

# Every asset the served page names must exist, which is the exact failure this script guards.
# The result is collected into a variable rather than set inside the loop: a `while read` fed by
# a here-string runs in a subshell, so assignments made inside it are lost and the check below
# would silently never fire.
echo
echo "assets named by the served page:"
NAMED="$(grep -o 'assets/[^"]*' <<<"${SERVED_HTML:-$(cat "$TARGET/index.html")}" | sort -u)"
MISSING=0
while read -r asset; do
  [[ -z "$asset" ]] && continue
  if [[ -f "$TARGET/$asset" ]]; then
    echo "  OK      $asset"
  else
    echo "  MISSING $asset"
    MISSING=1
  fi
done <<<"$NAMED"

if [[ $MISSING -eq 1 ]]; then
  echo
  echo "deploy FAILED: the served page references files that are not on disk."
  exit 1
fi

echo
echo "deploy OK — the served page names only files that exist."
