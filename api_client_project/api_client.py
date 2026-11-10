import os
import time
import logging
import random
import requests
from typing import Optional, Dict, Any, Generator
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
    - Respects Retry-After header
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
                    
                    # Check for Retry-After header
                    if 'Retry-After' in response.headers:
                        wait_time = int(response.headers['Retry-After'])
                        logger.warning(
                            f"{response.status_code} from {url}, "
                            f"Retry-After header: {wait_time}s"
                        )
                    else:
                        wait_time = self._calculate_backoff(attempt)
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
