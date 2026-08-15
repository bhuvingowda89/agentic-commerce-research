package research.commerce.order;

record CreateOrderRequest(String transactionId, String idempotencyKey, String cartId, String customerId) {
}

