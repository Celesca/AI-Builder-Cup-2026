#!/usr/bin/env bash
# Compute Engine startup script: installs Docker and git. Runs as root on every boot and is safe to repeat.
set -euo pipefail
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
apt-get install -y git >/dev/null
systemctl enable --now docker
