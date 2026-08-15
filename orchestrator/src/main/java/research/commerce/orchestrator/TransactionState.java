package research.commerce.orchestrator;

enum TransactionState {
    STARTED,
    CART_CREATED,
    ORDER_CREATED,
    PAYMENT_PENDING,
    PAYMENT_COMPLETED,
    COMPLETED,
    COMPENSATING,
    COMPENSATED,
    FAILED
}

