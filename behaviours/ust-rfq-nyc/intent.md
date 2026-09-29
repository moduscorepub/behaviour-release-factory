# NYC UST RFQ capture from client chat

Example approved specification: Confluence page 100001, version 7 (illustrative).

## Business intent
Clients in the UST client rooms request prices on US Treasury benchmarks (2y, 5y, 10y, 30y).
The engine captures each request as an RFQ for the NYC UST traders and, once a trader acknowledges it,
posts a LIVE suggestion into the UST trader chat.

## Rules
- One client request produces exactly one RFQ with the side, benchmark and notional the client asked for.
- A cancelled request stays cancelled: a delayed or replayed trader acknowledgement must never
  reactivate or re-route it.
- Redelivery, reconnects and restarts must not duplicate anything sent to traders or back to the chat platform,
  and must not lose a client message.
- Quoted chat history (lines starting with ">") is context, never a new request.
- Notional must be between 1mm and 500mm; ambiguous side, size or benchmark means no RFQ.
- "make it", "actually" and "cxl"/"cancel" apply to the client's most recent open request.
- Requests for other products (swaps, CDS, bunds, gilts, futures) in the same room are not UST RFQs.
