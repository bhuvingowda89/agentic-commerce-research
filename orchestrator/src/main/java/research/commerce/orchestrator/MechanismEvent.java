package research.commerce.orchestrator;

import java.time.Instant;

record MechanismEvent(
    long eventId,
    String idempotencyKey,
    String transactionId,
    String eventType,
    String mechanism,
    String operation,
    String stateBefore,
    String stateAfter,
    String detail,
    Instant createdAt
) {
}
