package research.commerce.orchestrator;

record TransactionResponse(
    String transactionId,
    String idempotencyKey,
    String state,
    String cartId,
    String orderId,
    String paymentId,
    int retryCount,
    int operationRetryCount,
    int compensationRetryCount,
    String failureReason,
    boolean recovered,
    boolean compensated,
    boolean duplicateDetected
) {
}
