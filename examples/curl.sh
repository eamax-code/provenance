#!/usr/bin/env bash
# Sample requests. Set API_KEY (from scripts/create_api_key.py) and BASE_URL.
set -euo pipefail
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
: "${API_KEY:?Set API_KEY}"
H="X-API-Key: ${API_KEY}"

echo "# search by ticker"
curl -sS -H "$H" "$BASE_URL/v1/companies/search?q=AAPL" | python -m json.tool

echo "# company profile (202 while on-demand ingestion runs)"
curl -sS -i -H "$H" "$BASE_URL/v1/companies/320193" | head -20

echo "# recent 10-K filings"
curl -sS -H "$H" "$BASE_URL/v1/companies/320193/filings?form_type=10-K&limit=5" | python -m json.tool

echo "# annual revenue with provenance"
curl -sS -H "$H" "$BASE_URL/v1/companies/320193/facts?metric=revenue&period=annual&limit=5" | python -m json.tool

echo "# quarterly, including quarters derived by subtraction (marked derived=true)"
curl -sS -H "$H" "$BASE_URL/v1/companies/320193/facts?metric=revenue&period=quarterly&include_derived=true" | python -m json.tool

echo "# freshness"
curl -sS -H "$H" "$BASE_URL/v1/companies/320193/freshness" | python -m json.tool

echo "# create a webhook watch (secret is shown once)"
curl -sS -H "$H" -H "Content-Type: application/json" -X POST "$BASE_URL/v1/watches" \
  -d '{"cik":"320193","destination_type":"webhook","destination":"https://hooks.example.com/sec"}' | python -m json.tool

echo "# usage"
curl -sS -H "$H" "$BASE_URL/v1/developer/usage" | python -m json.tool

echo "# bounded CSV export"
curl -sS -H "$H" -o facts.csv -D - "$BASE_URL/v1/exports/facts?metric=revenue&ciks=320193&format=csv&limit=100"
head -3 facts.csv
