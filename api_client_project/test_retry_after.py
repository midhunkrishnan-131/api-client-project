#!/usr/bin/env python3
"""Unit tests for Retry-After handling. No network access."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock, patch

import requests

from api_client import APIClient


def _response(status_code, headers=None):
    response = requests.Response()
    response.status_code = status_code
    response.url = "https://api.example.com/things"
    response.reason = "OK" if status_code < 400 else "Error"
    if headers:
        response.headers.update(headers)
    return response


class RetryAfterParsingTests(unittest.TestCase):
    def setUp(self):
        os.environ["API_KEY"] = "unit-test-key"
        self.client = APIClient(
            base_url="https://api.example.com",
            timeout=1,
            max_retries=3,
        )
        self.addCleanup(self.client.close)

    def test_whole_seconds(self):
        self.assertEqual(self.client._parse_retry_after("12"), 12.0)

    def test_fractional_seconds(self):
        self.assertEqual(self.client._parse_retry_after("1.5"), 1.5)

    def test_surrounding_whitespace(self):
        self.assertEqual(self.client._parse_retry_after("  8 "), 8.0)

    def test_zero_seconds(self):
        self.assertEqual(self.client._parse_retry_after("0"), 0.0)

    def test_http_date_in_the_past_is_ready_now(self):
        # RFC 9110 example. int() used to raise ValueError on this value.
        header = "Wed, 21 Oct 2015 07:28:00 GMT"
        self.assertEqual(self.client._parse_retry_after(header), 0.0)

    def test_http_date_in_the_future(self):
        target = datetime.now(timezone.utc) + timedelta(seconds=40)
        header = format_datetime(target, usegmt=True)
        parsed = self.client._parse_retry_after(header)
        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed, 40, delta=2)

    def test_unusable_values_are_rejected(self):
        for header in ("-5", "not-a-date", "", "   ", "nan", "inf", "-inf"):
            with self.subTest(header=header):
                self.assertIsNone(self.client._parse_retry_after(header))


class GetRetryAfterTests(unittest.TestCase):
    def setUp(self):
        os.environ["API_KEY"] = "unit-test-key"
        self.client = APIClient(
            base_url="https://api.example.com",
            timeout=1,
            max_retries=2,
        )
        self.addCleanup(self.client.close)

    def _stub_get(self, responses):
        self.client.session.get = Mock(side_effect=responses)

    def test_numeric_retry_after_is_honored(self):
        self._stub_get([
            _response(429, {"Retry-After": "4"}),
            _response(200),
        ])
        with patch("api_client.time.sleep") as sleep:
            result = self.client.get("things")
        self.assertEqual(result.status_code, 200)
        sleep.assert_called_once_with(4.0)
        self.assertEqual(self.client.session.get.call_count, 2)

    def test_fractional_retry_after_is_honored(self):
        self._stub_get([
            _response(503, {"Retry-After": "0.5"}),
            _response(200),
        ])
        with patch("api_client.time.sleep") as sleep:
            result = self.client.get("things")
        self.assertEqual(result.status_code, 200)
        sleep.assert_called_once_with(0.5)

    def test_http_date_does_not_abort_the_retry(self):
        self._stub_get([
            _response(429, {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}),
            _response(200),
        ])
        with patch("api_client.time.sleep") as sleep:
            result = self.client.get("things")
        self.assertEqual(result.status_code, 200)
        sleep.assert_called_once_with(0.0)

    def test_future_http_date_sleeps_until_that_time(self):
        target = datetime.now(timezone.utc) + timedelta(seconds=25)
        header = format_datetime(target, usegmt=True)
        self._stub_get([
            _response(429, {"Retry-After": header}),
            _response(200),
        ])
        with patch("api_client.time.sleep") as sleep:
            result = self.client.get("things")
        self.assertEqual(result.status_code, 200)
        waited = sleep.call_args[0][0]
        self.assertGreater(waited, 20)
        self.assertLess(waited, 30)

    def test_malformed_header_falls_back_to_backoff(self):
        self._stub_get([
            _response(429, {"Retry-After": "Wednesday"}),
            _response(200),
        ])
        with patch("api_client.time.sleep") as sleep, patch.object(
            self.client, "_calculate_backoff", return_value=2.25
        ):
            result = self.client.get("things")
        self.assertEqual(result.status_code, 200)
        sleep.assert_called_once_with(2.25)

    def test_negative_header_falls_back_to_backoff(self):
        self._stub_get([
            _response(500, {"Retry-After": "-5"}),
            _response(200),
        ])
        with patch("api_client.time.sleep") as sleep, patch.object(
            self.client, "_calculate_backoff", return_value=1.5
        ):
            result = self.client.get("things")
        self.assertEqual(result.status_code, 200)
        sleep.assert_called_once_with(1.5)

    def test_missing_header_still_uses_backoff(self):
        self._stub_get([
            _response(429),
            _response(200),
        ])
        with patch("api_client.time.sleep") as sleep, patch.object(
            self.client, "_calculate_backoff", return_value=3.0
        ):
            result = self.client.get("things")
        self.assertEqual(result.status_code, 200)
        sleep.assert_called_once_with(3.0)

    def test_last_attempt_raises_without_sleeping(self):
        self.client.max_retries = 1
        self._stub_get([_response(429, {"Retry-After": "10"})])
        with patch("api_client.time.sleep") as sleep:
            with self.assertRaises(requests.HTTPError):
                self.client.get("things")
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
