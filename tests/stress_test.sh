#!/bin/bash

# Usage: ./curl_loop.sh [url] [count]
URL="${1:-http://127.0.0.1:8080/api/test}"
COUNT="${2:-1}"

for ((i=1; i<=COUNT; i++)); do
  (
    echo "Request $i:"
    curl -s "$URL"
    echo -e "\n"
  ) &
done

wait

