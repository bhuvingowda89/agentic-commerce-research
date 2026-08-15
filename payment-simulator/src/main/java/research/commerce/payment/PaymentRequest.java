package research.commerce.payment;

import java.math.BigDecimal;

record PaymentRequest(String transactionId, String idempotencyKey, String orderId, BigDecimal amount, String currency) {
}

