package research.commerce.orchestrator;

import java.math.BigDecimal;

record TransactionRequest(String logicalTransactionId, String customerId, String sku, int quantity, BigDecimal amount, String currency) {
}
