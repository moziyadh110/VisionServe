-- Analytics queries (Milestone 2). Run with:
--   docker compose exec postgres psql -U visionserve -d visionserve -f /dev/stdin < app/db/analytics.sql
-- Replace :user_id with a real id when running the per-user ones by hand.

-- 1. Requests per user per day, with a 7-day rolling average (window function).
SELECT
  user_id,
  day,
  requests,
  ROUND(AVG(requests) OVER (
    PARTITION BY user_id ORDER BY day
    ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
  ), 2) AS rolling_7d_avg
FROM (
  SELECT user_id, date_trunc('day', created_at) AS day, COUNT(*) AS requests
  FROM inference_requests
  GROUP BY user_id, day
) daily
ORDER BY user_id, day;

-- 2. Top 5 users by requests in the last 24 hours.
SELECT u.id, u.email, COUNT(*) AS requests
FROM inference_requests r
JOIN users u ON u.id = r.user_id
WHERE r.created_at >= now() - interval '24 hours'
GROUP BY u.id, u.email
ORDER BY requests DESC
LIMIT 5;

-- 3. p95 latency per task over the last hour.
SELECT
  task,
  COUNT(*) AS requests,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms
FROM inference_requests
WHERE created_at >= now() - interval '1 hour' AND latency_ms IS NOT NULL
GROUP BY task;

-- 4. Cache hit rate per day.
SELECT
  date_trunc('day', created_at) AS day,
  ROUND(AVG(CASE WHEN cache_hit THEN 1.0 ELSE 0.0 END), 3) AS hit_rate
FROM inference_requests
GROUP BY day
ORDER BY day;

-- 5. Index experiment: one user's most recent requests.
-- Run with the index, then:  DROP INDEX ix_inference_requests_user_id_created_at;
-- run again, compare (Index Scan vs Seq Scan + Sort), then recreate it with:
--   CREATE INDEX ix_inference_requests_user_id_created_at
--     ON inference_requests (user_id, created_at DESC);
EXPLAIN ANALYZE
SELECT id, task, latency_ms, created_at
FROM inference_requests
WHERE user_id = 1
ORDER BY created_at DESC
LIMIT 20;
