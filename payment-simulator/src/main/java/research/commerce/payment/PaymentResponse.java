package research.commerce.payment;

import java.math.BigDecimal;

record PaymentResponse(String paymentId, String transactionId, String idempotencyKey, String orderId, BigDecimal amount, String currency, String status) {
}

