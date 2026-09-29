# RFQs from client chat for the New York US Treasury desk

The file is an example of an approved specification. In a real project, the file would be a snapshot of version 7 of the approved Confluence page 100001. The ID after each rule names the matching requirement in `spec.yaml`.

## What the desk needs

Clients write in the US Treasury client chat rooms to ask for prices on the 2-year, 5-year, 10-year and 30-year Treasury benchmarks. The engine turns each request into a request for quote (RFQ) and sends the RFQ to the New York Treasury traders. When a trader picks up the RFQ, the engine posts one "LIVE" message in the chat of the traders (UST-RFQ-008).

## Rules for new requests

- Each client request creates exactly one RFQ. The RFQ must have the side, the benchmark and the amount that the client asked for, and the side is bid, offer or two-way (UST-RFQ-001).
- Lines of quoted chat history start with ">" and are only background, so the engine never treats them as a new request (UST-RFQ-004).
- The amount must be between 1 million and 500 million. If the side, the amount or the benchmark is unclear, the engine doesn't create an RFQ (UST-RFQ-005).

## Rules for changes and cancellations

- The words "make it", "actually", "cxl" and "cancel" apply to the most recent open request of the client (UST-RFQ-006).
- Once a request is cancelled, it stays cancelled. If a reply from a trader arrives late or arrives twice, the engine must not reactivate the request or send it anywhere (UST-RFQ-002).

## Rules for reliability

- If a message is delivered twice, or if the system reconnects or restarts, the engine must not send anything to the traders or to the chat twice. The engine must also never lose a client message (UST-RFQ-003).

## Rules for other products

- Requests for other products in the same rooms aren't Treasury RFQs, e.g., requests for swaps, credit default swaps, German bonds, UK gilts or futures (UST-RFQ-007).
