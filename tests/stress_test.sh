#!/bin/bash

# Usage: ./curl_loop.sh <url> <count>
URL="$1"
COUNT="$2"

# Default values if not provided
if [ -z "$URL" ]; then
  echo "Usage: $0 <url> <count>"
  exit 1
fi

if [ -z "$COUNT" ]; then
  COUNT=30
fi

for ((i=1; i<=COUNT; i++)); do
  echo "Request $i:"
  curl -s "$URL"
  echo -e "\n"
done

