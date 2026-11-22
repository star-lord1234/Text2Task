#!/bin/sh
# Build the multi-architecture inference image locally and publish it to GHCR.
set -eu

cd "$(dirname "$0")/.."

# Docker Desktop for macOS may install the CLI here before a newly opened shell
# has picked up Docker's PATH configuration.
if ! command -v docker >/dev/null 2>&1 && [ -x "$HOME/.docker/bin/docker" ]; then
  PATH="$HOME/.docker/bin:$PATH"
  export PATH
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install/start Docker Desktop and retry." >&2
  exit 1
fi

: "${T2T_IMAGE:?Set T2T_IMAGE, for example ghcr.io/OWNER/text2task}"
TAG="${1:-0.1.0-silver}"

python3 scripts/prepare_docker_models.py

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --label "org.opencontainers.image.title=Text2Task" \
  --label "org.opencontainers.image.version=$TAG" \
  --label "org.opencontainers.image.description=Text2Task provisional SILVER inference app" \
  --tag "$T2T_IMAGE:$TAG" \
  --tag "$T2T_IMAGE:latest" \
  --push \
  .

echo "Published $T2T_IMAGE:$TAG"
