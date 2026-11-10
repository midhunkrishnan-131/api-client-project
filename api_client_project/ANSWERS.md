# API Client: Written Answers

## 1. Walk me through how you handle rate limiting.

**Rate limiting is handled at two levels:**

The client detects the 429 (Too Many Requests) status code and treats it as a retriable error. Before retrying, it checks the `Retry-After` response header—if present, it honors that exact value since the server is explicitly telling us when to return. This respects the API's preferred backoff strategy.

If no `Retry-After` header exists, the client uses exponential backoff with jitter: wait time grows as 2^attempt - 1, capped at 60 seconds, with random jitter added to prevent thundering herd (all clients retrying simultaneously). After 5 attempts, if still rate-limited, the request fails loudly rather than silent degradation.

The session is reused across retries, avoiding connection overhead. Logs at each retry show the exact wait time, enabling visibility into rate limit behavior. This design balances aggressive retry with server-friendly backoff.

---

## 2. Why is jitter necessary in exponential backoff?

**Jitter prevents synchronized retry storms ("thundering herd").**

Imagine 1,000 API clients all hit a rate limit simultaneously. Without jitter, all 1,000 would wait exactly 1 second, then all retry at once, hammering the recovering server harder. The server crashes again, all 1,000 wait exactly 2 seconds, then retry simultaneously—creating cascading failures.

With jitter, each client adds randomness: one waits 0.3 seconds, another waits 1.8 seconds, another waits 0.9 seconds. Their retries spread across the time window, gradually distributing load as the server recovers. This transforms a synchronized spike into a gentler gradient, letting the server handle incoming requests without re-triggering the rate limit.

Additionally, jitter prevents recurring collision patterns in periodic systems. Without it, clients with aligned clock cycles could synchronize retries indefinitely.

---

## 3. How would you make a POST safe to retry?

**POST is inherently unsafe to retry blindly because it mutates state. Three approaches:**

**Idempotency Keys**: Include a unique, client-generated `Idempotency-Key` header (UUID). The server stores this key and result. If the same key arrives twice (retry), it returns the cached result without re-executing. If the POST creates a user, first attempt returns user_id; retry with same key returns same user_id without duplication.

**Server-side idempotency**: Design POST endpoints to be naturally idempotent—e.g., "create user only if email doesn't exist" instead of "insert user." This requires API redesign but eliminates retry problems at the source.

**Timeout + status check**: After a POST times out, query a separate GET endpoint to check if the operation succeeded. If `user/email@example.com` exists, the POST likely succeeded; retry is unnecessary.

The idempotency key approach is most practical: minimal API changes, works with any server implementing it (Stripe, etc.), and survives network failures without duplication.

---

## Key Design Principles Used

1. **Fail Loud, Not Silent**: Missing .env keys crash immediately, not later during execution
2. **Retry Only What Recovers**: 4xx client errors won't fix themselves; only retry 429 and 5xx
3. **Respect Server Signals**: Honor Retry-After headers; don't override server guidance
4. **Generator-Based Pagination**: Memory-efficient, no hardcoded page counts, stops automatically
5. **Reusable Session**: Connection pooling across all requests; single place to set auth headers
6. **Observable**: Structured logging at each retry shows exact backoff times and decisions
