#!/usr/bin/env bash
# Stage a clean copy of PolicyC and force-push it to a Hugging Face Space.
# Usage: ./deploy/huggingface/push_space.sh <hf-user>/<space-name> [branch]
# Credentials come from git's credential helper / prompt (HF username + write token); nothing secret
# is written to the staged folder or embedded in the remote URL.
set -euo pipefail
SPACE="${1:?usage: push_space.sh <hf-user>/<space-name> [branch]}"
BRANCH="${2:-main}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp "$ROOT/Dockerfile.full" "$STAGE/Dockerfile"; cp "$ROOT/.dockerignore" "$STAGE/"
cp "$HERE/README_SPACE.md" "$STAGE/README.md"

mkdir -p "$STAGE/backend"
tar -C "$ROOT/backend" \
  --exclude='.venv' --exclude='./data' --exclude='./models' --exclude='./tests' \
  --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.ruff_cache' \
  --exclude='.env' --exclude='.env.*' --exclude='*.log' --exclude='*.db' --exclude='*.sqlite' \
  -cf - . | tar -C "$STAGE/backend" -xf -

# The Dockerfile COPYs these paths unconditionally
mkdir -p "$STAGE/backend/seed"
[ -n "$(ls -A "$STAGE/backend/seed")" ] || touch "$STAGE/backend/seed/.keep"
mkdir -p "$STAGE/frontend/dist"
if [ -f "$ROOT/frontend/dist/index.html" ]; then
  cp -R "$ROOT/frontend/dist/." "$STAGE/frontend/dist/"
else
  touch "$STAGE/frontend/dist/.keep"
fi

if find "$STAGE" \( -name '.env*' -o -name '*.pem' -o -name '*.key' \) -print | grep -q .; then
  echo "Refusing to push: sensitive files staged" >&2
  exit 1
fi

cd "$STAGE"
git init -q -b "$BRANCH"
git add -A
git -c user.name=policyc-deploy -c user.email=deploy@localhost commit -q -m "Deploy PolicyC backend"
git remote add space "https://huggingface.co/spaces/$SPACE"
git push --force space "$BRANCH:main"
LOWER="$(echo "$SPACE" | tr '/' '-' | tr '[:upper:]' '[:lower:]')"
echo "Pushed. Logs: https://huggingface.co/spaces/$SPACE  API: https://$LOWER.hf.space/api/health"
