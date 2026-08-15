package research.commerce.orchestrator;

record CartCreateRequest(String transactionId, String idempotencyKey, String customerId) {
}

