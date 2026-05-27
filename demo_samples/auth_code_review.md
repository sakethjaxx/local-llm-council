# Code Review: Authentication Service

Review this Python auth module for a production API. Flag security issues, correctness bugs, and design problems.

## Code

```python
import hashlib
import sqlite3
import jwt
import time

SECRET = "supersecret123"
DB = "users.db"

def create_user(username, password):
    conn = sqlite3.connect(DB)
    pw_hash = hashlib.md5(password.encode()).hexdigest()
    conn.execute(f"INSERT INTO users VALUES ('{username}', '{pw_hash}')")
    conn.commit()
    conn.close()

def login(username, password):
    conn = sqlite3.connect(DB)
    pw_hash = hashlib.md5(password.encode()).hexdigest()
    row = conn.execute(
        f"SELECT * FROM users WHERE username='{username}' AND password='{pw_hash}'"
    ).fetchone()
    conn.close()
    if row:
        token = jwt.encode(
            {"user": username, "exp": time.time() + 86400},
            SECRET,
            algorithm="HS256"
        )
        return token
    return None

def get_user(token):
    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
        return payload["user"]
    except:
        return None
```

## Context

- This is being shipped to production next week
- 50,000 users expected at launch
- SOC 2 compliance required in Q3

## Questions for Review

1. Is this safe to ship?
2. What breaks first under load?
3. Priority order of fixes?
