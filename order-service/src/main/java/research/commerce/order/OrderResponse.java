package research.commerce.order;

record OrderResponse(String orderId, String transactionId, String idempotencyKey, String cartId, String customerId, String status) {
}

