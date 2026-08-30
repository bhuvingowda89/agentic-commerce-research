package research.commerce.orchestrator;

record MechanismEventResponse(
    long eventId,
    String idempotencyKey,
    String transactionId,
    String eventType,
    String mechanism,
    String operation,
    String stateBefore,
    String stateAfter,
    String detail,
    String createdAt
) {
    static MechanismEventResponse from(MechanismEvent event) {
        return new MechanismEventResponse(
            event.eventId(),
            event.idempotencyKey(),
            event.transactionId(),
            event.eventType(),
            event.mechanism(),
            event.operation(),
            event.stateBefore(),
            event.stateAfter(),
            event.detail(),
            event.createdAt().toString()
        );
    }
}
