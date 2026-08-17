# Post-Incident Review: Production Outage

Analyze this incident and produce: root cause, contributing factors, and prevention plan.

## Incident Summary

**Duration:** 4 hours 17 minutes (2:14 AM – 6:31 AM UTC)
**Impact:** 100% of API requests failed. 80K users affected. $240K estimated revenue loss.
**Severity:** SEV-1

## Timeline

- 02:14 — Automated deploy of v3.8.2 triggered (routine release)
- 02:16 — Deploy completes. No alerts fire.
- 02:31 — First customer ticket: "API returning 503"
- 02:45 — On-call engineer paged (PagerDuty delay: 14 min)
- 03:10 — Engineer identifies pod crash-looping in Kubernetes
- 03:45 — Rollback to v3.8.1 attempted. Fails. Helm state corrupt.
- 04:30 — Decision made to redeploy from scratch
- 05:50 — Fresh cluster provisioning complete
- 06:31 — Full traffic restored

## Root Cause (preliminary)

v3.8.2 included a new environment variable `MAX_POOL_SIZE` with no default. When not set in the cluster, the connection pool raised an unhandled exception at startup. All pods crashed on boot. Liveness probe passed (HTTP /health returns 200 before pool init). Readiness probe never fired because pods never reached ready state — but traffic was briefly routed before that check completed.

## Contributing Factors

1. No staging environment (staging cluster was deleted 3 weeks ago to save costs)
2. Liveness probe checked wrong endpoint — didn't exercise DB connection
3. PagerDuty escalation policy had 14-minute delay before paging on-call
4. Helm release state corruption caused by a partial rollback 6 months ago, never cleaned up
5. No runbook for "cluster from scratch" restore procedure

## Questions for Council

1. Is the root cause analysis correct or are we missing something?
2. Which contributing factor do we fix first?
3. How do we prevent the next deploy from doing this?
4. Should we restore staging? What's the minimum viable staging setup?
