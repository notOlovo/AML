#!/usr/bin/env bash
# Build and run the analyst UI in Podman (or Docker: ENGINE=docker scripts/run_container.sh)
# Put clients.csv and transactions.csv into data/real/ first; open http://localhost:8501
set -euo pipefail
cd "$(dirname "$0")/.."
ENGINE="${ENGINE:-podman}"
PORT="${PORT:-8501}"
mkdir -p data/real
$ENGINE build -t aml-copilot -f Containerfile .
$ENGINE rm -f aml-copilot >/dev/null 2>&1 || true
AWS_ARGS=()
[ -d "$HOME/.aws" ] && AWS_ARGS=(-v "$HOME/.aws:/root/.aws:Z" -e AWS_PROFILE="${AWS_PROFILE:-hackathon}")
$ENGINE run -d --name aml-copilot -p "$PORT:8501" \
  -v "$PWD/data/real:/app/data/real:ro,Z" ${AWS_ARGS[@]+"${AWS_ARGS[@]}"} aml-copilot
echo "AML Triage Copilot: http://localhost:$PORT   (logs: $ENGINE logs -f aml-copilot)"
