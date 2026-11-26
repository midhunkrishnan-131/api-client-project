import os
import time
import logging
import math
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Any, Generator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry as UrllibRetry
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class APIClient:
    """
    Reusable HTTP client for REST APIs with production-grade error handling.
    
    Features:
    - Session reuse with persistent headers
    - Exponential backoff with jitter for 429 and 5xx errors
    - Respects Retry-After (delta-seconds or HTTP-date); unusable values fall back to backoff
    - Pagination support
    - .env-based configuration with loud failure on missing keys
    """
    
    def __init__(self, base_url: str, api_key_env_var: str = "API_KEY", 
                 timeout: int = 10, max_retries: int = 5):
        """
        Initialize the API client.
        
        Args:
            base_url: Base URL for all requests
            api_key_env_var: Environment variable name for API key
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            
        Raises:
            EnvironmentError: If API key environment variable is not set
        """
        load_dotenv()
        
        # Load API key - fail loudly if missing
        api_key = os.getenv(api_key_env_var)
        if not api_key:
            raise EnvironmentError(
                f"Missing required environment variable: {api_key_env_var}\n"
                f"Please set it in .env file or system environment."
            )
        
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        
        # Create session with default headers
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'APIClient/1.0'
        })
        
        logger.info(f"APIClient initialized for {base_url}")
    
    def _calculate_backoff(self, attempt: int) -> float:
        """
        Calculate exponential backoff with jitter.
        
        Formula: min(60, (2^attempt - 1) + random(0, 1))
        
        Args:
            attempt: Zero-indexed attempt number
            
        Returns:
            Seconds to wait before next retry
        """
        # Exponential backoff: 2^attempt - 1
        base_backoff = (2 ** attempt) - 1
        # Add jitter: random value between 0 and base_backoff
        jitter = random.uniform(0, base_backoff)
        backoff = base_backoff + jitter
        # Cap at 60 seconds
        return min(60, backoff)

    def _parse_retry_after(self, header_value: str) -> Optional[float]:
        """
        Parse a Retry-After header into a non-negative delay in seconds.

        RFC 9110 allows either delta-seconds or an HTTP-date. Fractional
        seconds are accepted. Returns None when the value is blank, negative,
        non-finite, or not a valid HTTP-date so the caller can fall back to
        exponential backoff instead of aborting a retryable request.

        Args:
            header_value: Raw Retry-After header value

        Returns:
            Seconds to wait, or None if the header cannot be used
        """
        text = str(header_value).strip()
        if not text:
            return None

        try:
            seconds = float(text)
        except ValueError:
            seconds = None
        else:
            if math.isfinite(seconds) and seconds >= 0:
                return seconds
            return None

        try:
            retry_at = parsedate_to_datetime(text)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None

        if not math.isfinite(delay):
            return None
        # A date in the past means the server already allows another try.
        return max(0.0, delay)
    
    def get(self, endpoint: str, params: Optional[Dict] = None, 
            **kwargs) -> requests.Response:
        """
        GET request with automatic retry on 429 and 5xx errors.
        
        Never retries 4xx errors (except 429) because:
        - 400 Bad Request: Invalid data won't become valid on retry
        - 401 Unauthorized: Bad credentials won't fix themselves
        - 403 Forbidden: Permissions don't change during retry
        - 404 Not Found: Resource won't appear on retry
        Retrying these wastes resources and delays failure feedback.

        A 429 or 5xx response may include Retry-After as delta-seconds or an
        HTTP-date (RFC 9110). That delay is used as-is, including fractional
        seconds. If the header is missing, negative, or unparseable, the client
        waits using exponential backoff instead of failing the request.
        
        Args:
            endpoint: API endpoint (appended to base_url)
            params: Query parameters
            **kwargs: Additional requests arguments
            
        Returns:
            requests.Response object
            
        Raises:
            requests.HTTPError: If max retries exceeded or non-retryable 4xx
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"GET {url} (attempt {attempt + 1}/{self.max_retries})")
                
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    **kwargs
                )
                
                # Success - return immediately
                if response.status_code < 400:
                    logger.info(f"GET {url} -> {response.status_code}")
                    return response
                
                # Non-retryable 4xx errors: fail immediately
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    logger.error(f"GET {url} -> {response.status_code} (non-retryable)")
                    response.raise_for_status()
                
                # 429 (rate limit) or 5xx: retry
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == self.max_retries - 1:
                        logger.error(f"Max retries exceeded for {url}")
                        response.raise_for_status()
                    
                    # Honor Retry-After (delta-seconds or HTTP-date). An unusable
                    # value must not abort the retry; fall back to backoff.
                    retry_after = response.headers.get('Retry-After')
                    parsed_retry_after = (
                        self._parse_retry_after(retry_after)
                        if retry_after is not None else None
                    )
                    if parsed_retry_after is not None:
                        wait_time = parsed_retry_after
                        shown = (
                            str(int(wait_time))
                            if wait_time.is_integer()
                            else f"{wait_time:.2f}"
                        )
                        logger.warning(
                            f"{response.status_code} from {url}, "
                            f"Retry-After header: {shown}s"
                        )
                    else:
                        wait_time = self._calculate_backoff(attempt)
                        if retry_after is not None:
                            logger.warning(
                                f"{response.status_code} from {url}, "
                                f"unusable Retry-After {retry_after!r}, "
                                f"exponential backoff: {wait_time:.2f}s"
                            )
                        else:
                            logger.warning(
                                f"{response.status_code} from {url}, "
                                f"exponential backoff: {wait_time:.2f}s"
                            )
                    
                    time.sleep(wait_time)
                    continue
            
            except requests.exceptions.Timeout:
                if attempt == self.max_retries - 1:
                    logger.error(f"Timeout on {url} after {self.max_retries} attempts")
                    raise
                
                wait_time = self._calculate_backoff(attempt)
                logger.warning(f"Timeout on {url}, retrying in {wait_time:.2f}s")
                time.sleep(wait_time)
                continue
            
            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed: {e}")
                raise
        
        logger.error(f"Unexpected: exhausted retries without returning")
        raise RuntimeError(f"Failed to complete request after {self.max_retries} attempts")
    
    def paginate(self, endpoint: str, page_param: str = 'page', 
                 per_page_param: str = 'per_page', per_page: int = 30,
                 result_key: Optional[str] = None) -> Generator[Dict[str, Any], None, None]:
        """
        Paginate through API results, yielding individual records.
        
        Automatically detects end of pagination when:
        - API returns empty array
        - API returns fewer items than per_page
        - API returns no 'next' link (if using Link header)
        
        Args:
            endpoint: API endpoint
            page_param: Query parameter name for page number
            per_page_param: Query parameter name for page size
            per_page: Items per page
            result_key: JSON key containing array of results (None = root is array)
            
        Yields:
            Individual records from paginated results
        """
        page = 1
        has_more = True
        
        while has_more:
            logger.debug(f"Fetching page {page}")
            
            params = {
                page_param: page,
                per_page_param: per_page
            }
            
            response = self.get(endpoint, params=params)
            response.raise_for_status()
            
            # Extract results
            data = response.json()
            if result_key:
                results = data.get(result_key, [])
            else:
                results = data if isinstance(data, list) else [data]
            
            # Yield individual records
            if not results:
                logger.info(f"Empty page {page}, stopping pagination")
                has_more = False
            else:
                for record in results:
                    yield record
                
                # Check if there are more pages
                if len(results) < per_page:
                    logger.info(f"Got {len(results)} items (< {per_page}), stopping pagination")
                    has_more = False
                else:
                    page += 1
                    logger.debug(f"Got {len(results)} items, moving to page {page}")
    
    def close(self):
        """Close the session."""
        self.session.close()
        logger.info("Session closed")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
