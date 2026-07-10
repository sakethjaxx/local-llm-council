# API Design Decision: REST vs GraphQL vs gRPC

We are building the public API for a developer platform (think: Stripe, Twilio-style). Need a council decision on the right API style.

## Product Context

- Developers integrate our service to send transactional notifications (email, SMS, push)
- Expected API consumers: mobile apps, web frontends, backend services, third-party integrations
- Expected scale: 100M API calls/day at peak
- Team: 4 backend engineers, no dedicated API team

## Option A: REST

- Industry standard, every developer knows it
- Easy to version (v1/, v2/)
- Simple caching via HTTP
- Webhook pattern for async events
- Pain: over-fetching, multiple round trips for complex clients

## Option B: GraphQL

- Single endpoint, clients fetch exactly what they need
- Strong typing via schema
- Great for frontend teams with varying data needs
- Pain: N+1 query problem, caching complexity, learning curve, not natural for mutations/webhooks

## Option C: gRPC

- Best raw performance (Protocol Buffers, HTTP/2)
- Strongly typed, great for service-to-service
- Streaming built-in
- Pain: not browser-native, tooling overhead, harder to debug

## Constraints

- Must have a great developer experience (DX is a product differentiator)
- Must support SDKs in Python, Node, Go, Ruby
- Must work well with Stripe-style idempotency keys
- Team has zero gRPC production experience

## Council Question

Which approach? Can we hybrid? What are the real risks of each?
