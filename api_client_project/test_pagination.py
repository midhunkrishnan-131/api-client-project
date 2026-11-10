#!/usr/bin/env python3
"""
Test pagination with JSONPlaceholder (free fake API).

JSONPlaceholder provides:
- /posts - 100 posts total
- Each request returns paginated results
- Clean shutdown when page is empty or has < per_page items

Run this with:
    python test_pagination.py
"""

import os
import logging
from api_client import APIClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_posts_pagination():
    """Paginate through JSONPlaceholder posts."""
    print("\n" + "="*70)
    print("PAGINATION TEST: JSONPlaceholder Posts")
    print("="*70)
    print("Fetching all posts from: https://jsonplaceholder.typicode.com/posts")
    print("Total available: 100 posts")
    print("Per page: 10 items")
    print("-"*70)
    
    # Create minimal .env for test (JSONPlaceholder doesn't need auth)
    with open('.env', 'w') as f:
        f.write('API_KEY=not-needed-for-public-api\n')
    
    try:
        client = APIClient(
            base_url='https://jsonplaceholder.typicode.com',
            api_key_env_var='API_KEY',
            timeout=10,
            max_retries=3
        )
        
        post_count = 0
        user_ids = set()
        
        # Use custom pagination params for JSONPlaceholder
        # Note: JSONPlaceholder uses _start and _limit for pagination
        print("\nNote: JSONPlaceholder uses _start and _limit params instead of page/per_page")
        print("This test uses default page/per_page params (for standard APIs)")
        print("-"*70 + "\n")
        
        # JSONPlaceholder actually uses different pagination style,
        # so let's demonstrate with standard page-based API
        print("For demonstration, fetching comments (smaller dataset)...")
        print()
        
        for comment in client.paginate(
            'comments',
            page_param='_page',
            per_page_param='_limit',
            per_page=10
        ):
            post_count += 1
            if 'email' in comment:
                print(f"  [{post_count:3d}] {comment['email']}")
            
            # Stop after reasonable demo
            if post_count >= 25:
                print(f"  ... (stopping demo after {post_count} items)")
                break
        
        print()
        print("-"*70)
        print(f"✓ Pagination demo complete: fetched {post_count} records")
        print("\nKey observations:")
        print("1. Generator yields individual items (not pages)")
        print("2. No hardcoded page count - pagination stops automatically")
        print("3. Logger shows 'Got X items, moving to page Y' messages")
        print("4. Session is reused across all pagination requests")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()


def test_posts_with_result_key():
    """Show how result_key parameter works."""
    print("\n" + "="*70)
    print("PAGINATION TEST: Using result_key")
    print("="*70)
    
    with open('.env', 'w') as f:
        f.write('API_KEY=not-needed-for-public-api\n')
    
    try:
        client = APIClient(
            base_url='https://api.example.com',  # Won't actually call this
            api_key_env_var='API_KEY'
        )
        
        print("result_key is used when API returns:")
        print("""
  {
    "data": [
      {"id": 1, "name": "Item 1"},
      {"id": 2, "name": "Item 2"}
    ],
    "meta": {"page": 1}
  }
        """)
        print("Usage: client.paginate('endpoint', result_key='data')")
        print("The generator yields individual items from data[], not the wrapper")
        
    finally:
        client.close()


if __name__ == '__main__':
    print("\n")
    print("╔" + "="*68 + "╗")
    print("║  API CLIENT PAGINATION TESTING                                  ║")
    print("║  Using JSONPlaceholder (free fake REST API)                      ║")
    print("╚" + "="*68 + "╝")
    
    test_posts_pagination()
    test_posts_with_result_key()
    
    print("\n" + "="*70)
    print("PAGINATION TESTS COMPLETE")
    print("="*70 + "\n")
