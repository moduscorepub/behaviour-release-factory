# RFQs from client chat for the London gilt desk

The file is an example of an approved specification. In a real project, the file would be a snapshot of version 3 of the approved Confluence page 100002. The ID after each rule names the matching requirement in `spec.yaml`.

## What the desk needs

Clients write in the gilt client chat rooms to ask for prices on the following UK government bonds: the 4½% 2028, the 4¼% 2032 and the 3¾% 2038. Clients use desk slang, e.g., "4¼s of 32", "ukt 38" or "32s". The engine turns each request into a request for quote (RFQ) and sends the RFQ to the London gilt traders. When a trader picks up the RFQ, the engine posts one "LIVE" message in the chat of the traders (GILT-RFQ-008).

## Rules for new requests

- Each client request creates exactly one RFQ. The RFQ must have the side, the gilt and the amount that the client asked for, and the side is bid, offer or two-way (GILT-RFQ-001).
- Lines of quoted chat history start with ">" and are only background, so the engine never treats them as a new request (GILT-RFQ-004).
- The amount must be between 1 million and 250 million pounds. If the side, the amount or the gilt is unclear, the engine doesn't create an RFQ (GILT-RFQ-005).

## Rules for changes and cancellations

- The words "make it", "actually", "cxl" and "cancel" apply to the most recent open request of the client (GILT-RFQ-006).
- Once a request is cancelled, it stays cancelled. If a reply from a trader arrives late or arrives twice, the engine must not reactivate the request or send it anywhere (GILT-RFQ-002).

## Rules for reliability

- If a message is delivered twice, or if the system reconnects or restarts, the engine must not send anything to the traders or to the chat twice. The engine must also never lose a client message (GILT-RFQ-003).

## Rules for other products and other desks

- Requests for other products in the gilt rooms aren't gilt RFQs, e.g., requests for US Treasuries, swaps, German bonds or futures (GILT-RFQ-007).
- The gilt desk must never pick up messages from the US Treasury client rooms (GILT-RFQ-007).
