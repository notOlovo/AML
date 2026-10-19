#!/usr/bin/env bash
# Copy the shared datasets into data/real/ (needs: aws sso login --profile hackathon)
set -euo pipefail
cd "$(dirname "$0")/.."
B=s3://ai-hackathon-datasets-422928733782
mkdir -p data/real
aws s3 cp "$B/CNB/" data/real/ --recursive --region eu-central-1
aws s3 cp "$B/MostlyRIght/" data/real/MostlyRIght/ --recursive --region eu-central-1 || echo "Mostly Right not copied"
ls -la data/real
