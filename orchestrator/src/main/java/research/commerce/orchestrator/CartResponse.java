package research.commerce.orchestrator;

import java.util.List;

public record CartResponse(String cartId, String transactionId, String idempotencyKey, String customerId, String status, List<CartItem> items) {
    public record CartItem(String sku, int quantity) {
    }
}
