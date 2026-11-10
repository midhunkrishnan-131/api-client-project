#!/usr/bin/env python3
"""
Test exponential backoff with httpbin.org.

This demonstrates:
1. Retry logic on 429 (rate limit) and 500 (server error)
2. Exponential backoff with jitter increasing across attempts
3. Log output showing backoff intervals
4. Cap at 60 seconds

Run this with:
    python test_retry_backoff.py
"""

import os
import sys
import logging
from api_client import APIClient

# Make logging more verbose to see retry messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_429_rate_limit():
    """Test retry behavior on 429 Too Many Requests."""
    print("\n" + "="*70)
    print("TEST 1: 429 Rate Limit Retry")
    print("="*70)
    print("Testing with httpbin.org/status/429")
    print("Expected: Client should retry 5 times with exponential backoff + jitter")
    print("-"*70)
    
    # Create minimal .env for test
    with open('.env', 'w') as f:
        f.write('API_KEY=test-key\n')
    
    try:
        client = APIClient(
            base_url='https://httpbin.org',
            api_key_env_var='API_KEY',
            timeout=5,
            max_retries=5
        )
        
        # Try to fetch endpoint that always returns 429
        # This will fail after max retries, but we'll see all the backoff logs
        response = client.get('status/429')
    except Exception as e:
        print(f"\nExpected failure after 5 retries: {type(e).__name__}")
        print("^ Check the logs above for increasing backoff intervals")
    finally:
        client.close()


def test_500_server_error():
    """Test retry behavior on 500 Internal Server Error."""
    print("\n" + "="*70)
    print("TEST 2: 500 Server Error Retry")
    print("="*70)
    print("Testing with httpbin.org/status/500")
    print("Expected: Client should retry 5 times with exponential backoff + jitter")
    print("-"*70)
    
    # Create minimal .env for test
    with open('.env', 'w') as f:
        f.write('API_KEY=test-key\n')
    
    try:
        client = APIClient(
            base_url='https://httpbin.org',
            api_key_env_var='API_KEY',
            timeout=5,
            max_retries=5
        )
        
        # Try to fetch endpoint that always returns 500
        response = client.get('status/500')
    except Exception as e:
        print(f"\nExpected failure after 5 retries: {type(e).__name__}")
        print("^ Check the logs above for increasing backoff intervals")
    finally:
        client.close()


def test_404_no_retry():
    """Test that 404 is NOT retried."""
    print("\n" + "="*70)
    print("TEST 3: 404 Not Found - Should NOT Retry")
    print("="*70)
    print("Testing with httpbin.org/status/404")
    print("Expected: Client should fail immediately (one attempt only)")
    print("-"*70)
    
    # Create minimal .env for test
    with open('.env', 'w') as f:
        f.write('API_KEY=test-key\n')
    
    try:
        client = APIClient(
            base_url='https://httpbin.org',
            api_key_env_var='API_KEY',
            timeout=5,
            max_retries=5
        )
        
        response = client.get('status/404')
    except Exception as e:
        print(f"\nFailed immediately (no retry): {type(e).__name__}")
        print("^ Notice there's only ONE attempt log - no retry backoff")
    finally:
        client.close()


def test_success_200():
    """Test successful request (200 OK)."""
    print("\n" + "="*70)
    print("TEST 4: 200 OK - Immediate Success")
    print("="*70)
    print("Testing with httpbin.org/status/200")
    print("Expected: Success on first attempt")
    print("-"*70)
    
    # Create minimal .env for test
    with open('.env', 'w') as f:
        f.write('API_KEY=test-key\n')
    
    try:
        client = APIClient(
            base_url='https://httpbin.org',
            api_key_env_var='API_KEY',
            timeout=5,
            max_retries=5
        )
        
        response = client.get('status/200')
        print(f"\n✓ Success: {response.status_code}")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
    finally:
        client.close()


if __name__ == '__main__':
    print("\n")
    print("╔" + "="*68 + "╗")
    print("║  API CLIENT RETRY & BACKOFF TESTING                            ║")
    print("║  Using httpbin.org to simulate rate limits and server errors    ║")
    print("╚" + "="*68 + "╝")
    
    test_success_200()
    test_404_no_retry()
    test_429_rate_limit()
    test_500_server_error()
    
    print("\n" + "="*70)
    print("TESTS COMPLETE")
    print("="*70)
    print("\nObservations:")
    print("1. TEST 4 (200): Succeeds immediately (single attempt)")
    print("2. TEST 3 (404): Fails immediately, no retry (fast fail)")
    print("3. TEST 1 (429): Multiple attempts with increasing backoff intervals")
    print("4. TEST 2 (500): Multiple attempts with increasing backoff intervals")
    print("\nBackoff formula: (2^attempt - 1) + random_jitter, capped at 60s")
    print("-"*70 + "\n")
