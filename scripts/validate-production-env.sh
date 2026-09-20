#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "production env invalid: $1" >&2
  exit 1
}

[ "${DATABASE_URL:-}" = "" ] && fail "DATABASE_URL is required"
case "$DATABASE_URL" in
  postgresql+psycopg://*) ;;
  *) fail "DATABASE_URL must use postgresql+psycopg://" ;;
esac

[ "${ADD_API_TOKEN:-}" = "" ] && fail "ADD_API_TOKEN is required"
[ "$ADD_API_TOKEN" = "change-me" ] && fail "ADD_API_TOKEN must not use the local default"
[ "${#ADD_API_TOKEN}" -ge 16 ] || fail "ADD_API_TOKEN must contain at least 16 characters"

[ "${API_CORS_ORIGINS:-}" = "" ] && fail "API_CORS_ORIGINS is required"
case "$API_CORS_ORIGINS" in
  *localhost*|*127.0.0.1*) fail "API_CORS_ORIGINS must not expose localhost" ;;
esac
case "$API_CORS_ORIGINS" in
  https://*) ;;
  *) fail "API_CORS_ORIGINS must use HTTPS in production" ;;
esac

[ "${NEXT_PUBLIC_API_URL:-}" = "" ] && fail "NEXT_PUBLIC_API_URL is required"
case "$NEXT_PUBLIC_API_URL" in
  https://*) ;;
  *) fail "NEXT_PUBLIC_API_URL must use HTTPS in production" ;;
esac

echo "production env valid: PostgreSQL, non-default token, HTTPS origins and API URL"
