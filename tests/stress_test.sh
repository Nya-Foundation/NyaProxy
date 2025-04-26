#!/bin/bash

# Usage: ./curl_loop.sh [url] [count]
URL="${1:-http://127.0.0.1:8080/api/test/v1/status}"
COUNT="${2:-30}"

for ((i=1; i<=COUNT; i++)); do
  (
    echo "Request $i:"
    curl -s "$URL" -H "x-real-ip: 10.1.1.1"
    echo -e "\n"
  ) &
done

wait

