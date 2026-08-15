package research.commerce.cart;

public record CreateCartRequest(String transactionId, String idempotencyKey, String customerId) {
}
