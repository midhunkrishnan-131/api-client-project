# API Client - Production-Grade HTTP Client

A reusable, battle-tested HTTP client for REST APIs with automatic retry logic, exponential backoff, rate-limit handling, and pagination support.

## Features

✅ **Session Reuse**: Default headers (Auth, Content-Type) set once, reused across all requests  
✅ **Smart Retry Logic**: Retries only on 429 and 5xx; fails fast on 4xx client errors  
✅ **Exponential Backoff + Jitter**: Prevents thundering herd; capped at 60 seconds  
✅ **Retry-After Header**: Respects server guidance on when to retry  
✅ **Pagination Generator**: Memory-efficient, yields individual items, stops automatically  
✅ **Loud Startup Failures**: Missing .env keys crash immediately, not during execution  
✅ **Observable**: Structured logging shows retry intervals and decisions  

## Installation

```bash
# Clone/extract the project
cd api_client_project

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
# Edit .env and add your API key
```

## Quick Start

```python
from api_client import APIClient

# Initialize with base URL and API key from .env
client = APIClient(
    base_url='https://api.example.com',
    api_key_env_var='API_KEY',  # Loaded from .env or environment
    timeout=10,
    max_retries=5
)

# Single request with auto-retry
response = client.get('users', params={'page': 1})
data = response.json()

# Paginate through all results
for user in client.paginate('users', result_key='data'):
    print(user['name'])

# Context manager (auto-closes session)
with APIClient(base_url='...') as client:
    response = client.get('posts')
```

## Configuration

### .env File

```bash
# Required - API key for authentication
API_KEY=your_actual_api_key_here

# Optional - other configuration
DEBUG=false
```

If `API_KEY` is missing, the client raises `EnvironmentError` at init time:
```
EnvironmentError: Missing required environment variable: API_KEY
Please set it in .env file or system environment.
```

## API Reference

### `APIClient(base_url, api_key_env_var, timeout, max_retries)`

Constructor. Raises `EnvironmentError` if `api_key_env_var` is not set.

**Parameters:**
- `base_url` (str): Base URL for all requests (trailing slash removed)
- `api_key_env_var` (str): Environment variable name for API key. Default: `API_KEY`
- `timeout` (int): Request timeout in seconds. Default: `10`
- `max_retries` (int): Maximum retry attempts. Default: `5`

---

### `get(endpoint, params=None, **kwargs) -> Response`

GET request with automatic retry on 429 and 5xx errors.

**Retry Behavior:**
- ✅ 2xx, 3xx: Return immediately
- ✅ 429, 5xx: Retry with exponential backoff + jitter
- ❌ 4xx (except 429): Fail immediately, no retry

Why no retry on 4xx? Because:
- `400 Bad Request`: Invalid data won't become valid on retry
- `401 Unauthorized`: Bad credentials won't fix themselves
- `403 Forbidden`: Permissions don't change during retry
- `404 Not Found`: Resource won't appear on retry

Retrying these wastes resources and delays failure feedback to the user.

**Parameters:**
- `endpoint` (str): API endpoint (appended to base_url)
- `params` (dict): Query parameters
- `**kwargs`: Additional requests arguments (headers, etc.)

**Returns:** `requests.Response` object

**Raises:** `HTTPError` if max retries exceeded or non-retryable error

**Example:**
```python
response = client.get('users', params={'page': 1, 'per_page': 50})
users = response.json()
```

---

### `paginate(endpoint, page_param='page', per_page_param='per_page', per_page=30, result_key=None)`

Generator that yields individual records across all pages.

**Parameters:**
- `endpoint` (str): API endpoint
- `page_param` (str): Query parameter name for page number. Default: `page`
- `per_page_param` (str): Query parameter name for page size. Default: `per_page`
- `per_page` (int): Items per page. Default: `30`
- `result_key` (str): JSON key containing results array. Default: `None` (root is array)

**Yields:** Individual record dictionaries

**Auto-stops when:**
- API returns empty array
- API returns fewer items than `per_page`
- No hardcoded page count needed

**Example 1: Root is array**
```python
# API returns: [{"id": 1}, {"id": 2}, ...]
for item in client.paginate('items', per_page=50):
    print(item['id'])
```

**Example 2: Results nested in JSON key**
```python
# API returns: {"data": [{"id": 1}, ...], "meta": {...}}
for item in client.paginate('items', result_key='data'):
    print(item['id'])
```

**Example 3: Custom pagination parameters**
```python
# API uses different parameter names
for item in client.paginate(
    'search',
    page_param='_page',      # JSONPlaceholder style
    per_page_param='_limit',
    per_page=50
):
    print(item)
```

---

### Backoff Formula

For attempt N (0-indexed):
```
wait_time = min(60, (2^N - 1) + random(0, 2^N - 1))
```

**Example:**
- Attempt 0: 0-1 seconds
- Attempt 1: 1-3 seconds
- Attempt 2: 3-7 seconds
- Attempt 3: 7-15 seconds
- Attempt 4: 15-31 seconds (max 60s)

If API sends `Retry-After` header, that takes precedence over calculated backoff.

## Testing

### Test 1: Retry Logic with httpbin.org

```bash
python test_retry_backoff.py
```

This demonstrates:
1. **Test 4 (200 OK)**: Succeeds immediately (no retry)
2. **Test 3 (404 Not Found)**: Fails immediately (fast fail, no retry)
3. **Test 1 (429 Rate Limit)**: Retries 5 times with exponential backoff
4. **Test 2 (500 Server Error)**: Retries 5 times with exponential backoff

Watch the logs to see actual backoff intervals like:
```
WARNING - 429 from https://httpbin.org/status/429, exponential backoff: 0.42s
WARNING - 429 from https://httpbin.org/status/429, exponential backoff: 2.15s
WARNING - 429 from https://httpbin.org/status/429, exponential backoff: 5.87s
WARNING - 429 from https://httpbin.org/status/429, exponential backoff: 14.23s
WARNING - 429 from https://httpbin.org/status/429, exponential backoff: 31.45s
ERROR - Max retries exceeded
```

### Test 2: Pagination with JSONPlaceholder

```bash
python test_pagination.py
```

Fetches real paginated data from JSONPlaceholder's public API (no auth required).

## Real-World Usage Example

```python
from api_client import APIClient
import os

# Initialize client
client = APIClient(
    base_url='https://api.github.com',
    api_key_env_var='GITHUB_TOKEN',
    timeout=15,
    max_retries=5
)

# Single request
repos = client.get('user/repos', params={'per_page': 100})
print(f"Status: {repos.status_code}")

# Paginated results
print("All repositories:")
for repo in client.paginate('user/repos', result_key='items', per_page=100):
    print(f"  - {repo['name']} ({repo['language']})")

client.close()
```

Or with context manager (auto-closes):
```python
with APIClient(base_url='https://api.github.com', api_key_env_var='GITHUB_TOKEN') as client:
    for repo in client.paginate('user/repos'):
        print(repo['name'])
```

## Common Pitfalls & Solutions

| Problem | Solution |
|---------|----------|
| "Missing required environment variable" | Create .env file with `API_KEY=...` |
| Timeout errors on slow networks | Increase `timeout` parameter (e.g., `timeout=30`) |
| 401 Unauthorized on every request | Check API key in .env; verify format (Bearer token vs basic auth) |
| Pagination never stops | Ensure API returns empty array or fewer items than `per_page` |
| Too much logging | Set logging level to WARNING: `logging.getLogger().setLevel(logging.WARNING)` |

## Design Philosophy

1. **Fail Loud, Not Silent**: Missing config crashes immediately
2. **Retry Only What Recovers**: 4xx errors are permanent (during request), 5xx are transient
3. **Respect Server Signals**: Honor Retry-After header
4. **Memory Efficient**: Generators for pagination (never load all pages at once)
5. **Reusable Session**: Connection pooling; single place for auth headers
6. **Observable**: Structured logging at each decision point

## File Structure

```
api_client_project/
├── api_client.py              # Main client class (production-ready)
├── .env.example               # Environment template
├── requirements.txt           # Dependencies
├── README.md                  # This file
├── ANSWERS.md                 # Written answers to 3 questions
├── test_retry_backoff.py      # Test retry logic with httpbin
└── test_pagination.py         # Test pagination with JSONPlaceholder
```

## Dependencies

- `requests`: HTTP library
- `python-dotenv`: .env file loading
- `urllib3`: Bundled with requests

## License

Public domain - use as you wish.
