# Database Schema Review

Review this schema for a social media analytics platform. Identify performance, scaling, and design issues.

## Schema (PostgreSQL)

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255),
    username VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE posts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    content TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE likes (
    id SERIAL PRIMARY KEY,
    post_id INTEGER REFERENCES posts(id),
    user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE follows (
    id SERIAL PRIMARY KEY,
    follower_id INTEGER REFERENCES users(id),
    following_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE hashtags (
    id SERIAL PRIMARY KEY,
    tag VARCHAR(100),
    post_id INTEGER REFERENCES posts(id)
);
```

## Query We Need To Be Fast

```sql
-- Get feed for user 42: posts from followed users, last 7 days, sorted by likes desc
SELECT p.*, COUNT(l.id) as like_count
FROM posts p
JOIN follows f ON p.user_id = f.following_id
LEFT JOIN likes l ON l.post_id = p.id
WHERE f.follower_id = 42
  AND p.created_at > NOW() - INTERVAL '7 days'
GROUP BY p.id
ORDER BY like_count DESC
LIMIT 50;
```

## Scale Targets

- 2M users
- 500K posts/day
- Peak: 10K concurrent feed loads/min

## Questions

1. Which indexes are missing?
2. What breaks first at scale?
3. Should we denormalize? Where?
4. Is this the right DB for this workload?
