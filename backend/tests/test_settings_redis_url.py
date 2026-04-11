"""Regression tests for Redis URL handling in base settings.

Hosted Redis providers (Upstash, Railway, Fly) inject TLS URLs with query
parameters like ``rediss://user:pass@host:6379/0?ssl_cert_reqs=required``.
A string-based rsplit derivation silently drops the query string when
swapping DB indexes, which breaks the Django cache (and therefore DRF
throttling + task dedupe locks) even though Celery keeps working off the
raw broker URL.

These tests pin the helper against the failure shape Codex flagged during
the adversarial review on feat/rating-push-9-5.
"""

from config.settings.base import _redis_url_with_db


class TestRedisUrlWithDb:
    def test_plain_redis_url_swaps_db(self):
        assert (
            _redis_url_with_db("redis://localhost:6379/0", 1)
            == "redis://localhost:6379/1"
        )

    def test_rediss_url_preserves_query_params(self):
        """The main reason this helper exists — rediss:// with TLS options."""
        url = "rediss://default:pw@host.upstash.io:6379/0?ssl_cert_reqs=required"
        result = _redis_url_with_db(url, 1)
        assert result.startswith("rediss://default:pw@host.upstash.io:6379/1")
        assert "ssl_cert_reqs=required" in result

    def test_rediss_url_preserves_auth(self):
        url = "rediss://user:password@host:6379/0"
        assert _redis_url_with_db(url, 1) == "rediss://user:password@host:6379/1"

    def test_preserves_multiple_query_params(self):
        url = "rediss://host:6379/0?ssl_cert_reqs=required&socket_timeout=5"
        result = _redis_url_with_db(url, 1)
        assert "ssl_cert_reqs=required" in result
        assert "socket_timeout=5" in result
        assert "/1?" in result

    def test_preserves_fragment(self):
        url = "redis://host:6379/0#note"
        assert _redis_url_with_db(url, 1) == "redis://host:6379/1#note"

    def test_swaps_db_index_across_digits(self):
        assert _redis_url_with_db("redis://host/0", 15) == "redis://host/15"

    def test_cache_location_uses_db_1_not_broker_db(self):
        """Integration — the Django CACHES LOCATION must land on a different
        DB than Celery's broker URL so cache evictions don't blow away queued
        tasks."""
        from django.conf import settings

        broker = settings.CELERY_BROKER_URL
        cache_loc = settings.CACHES["default"]["LOCATION"]

        # Broker sits on /0 (or the default value); cache must differ
        assert cache_loc != broker
        # Cache index must end in /1 (preserving any query fragment)
        assert "/1" in cache_loc
