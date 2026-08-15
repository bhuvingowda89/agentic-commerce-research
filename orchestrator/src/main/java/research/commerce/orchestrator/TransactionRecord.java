package research.commerce.orchestrator;

record TransactionRecord(
    String transactionId,
    String idempotencyKey,
    TransactionState state,
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
    TransactionResponse toResponse() {
        return new TransactionResponse(
            transactionId,
            idempotencyKey,
            state.name(),
            cartId,
            orderId,
            paymentId,
            retryCount,
            operationRetryCount,
            compensationRetryCount,
            failureReason,
            recovered,
            compensated,
            duplicateDetected
        );
    }
}
