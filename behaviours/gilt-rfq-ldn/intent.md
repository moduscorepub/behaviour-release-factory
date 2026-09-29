# LDN gilt RFQ capture from client chat

Example approved specification: Confluence page 100002, version 3 (illustrative desk onboarding).

## Business intent
Clients in the gilt client rooms request prices on conventional gilts (4½% 2028, 4¼% 2032, 3¾% 2038)
using desk slang such as "4¼s of 32", "ukt 38" or "32s". The engine captures each request as an RFQ for the
LDN gilt traders and, once a trader acknowledges it, posts a LIVE suggestion into the gilt trader chat.

## Rules
- One client request produces exactly one RFQ with the side, gilt and nominal the client asked for.
- A cancelled request stays cancelled: a delayed or replayed trader acknowledgement must never
  reactivate or re-route it.
- Redelivery, reconnects and restarts must not duplicate anything sent to traders or back to the chat platform,
  and must not lose a client message.
- Quoted chat history (lines starting with ">") is context, never a new request.
- Nominal must be between 1m and 250m GBP; ambiguous side, size or gilt means no RFQ.
- "make it", "actually" and "cxl"/"cancel" apply to the client's most recent open request.
- Requests for other products (Treasuries, swaps, bunds, futures) in the same rooms are not gilt RFQs.
- The gilt desk must never capture messages from the UST client rooms.
