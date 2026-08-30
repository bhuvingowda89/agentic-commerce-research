package research.commerce.orchestrator;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class TransactionServiceV2BaselineTest {
    @Test
    void c0UsesFreshExecutionIdentityForDuplicateLogicalTransaction() {
        FakeCommerceClient commerceClient = new FakeCommerceClient();
        TransactionService service = new TransactionService(new FakeRepository(), commerceClient, 3);
        TransactionRequest request = request("logical-001");

        TransactionRecord first = service.execute(request, "same-key", "BASELINE", "f0-no-failure", 0.0, "7", "C0");
        TransactionRecord second = service.execute(request, "same-key", "BASELINE", "f0-no-failure", 0.0, "7", "C0");

        assertEquals("logical-001", request.logicalTransactionId());
        assertNotEquals(first.transactionId(), second.transactionId());
        assertNotEquals(first.cartId(), second.cartId());
        assertNotEquals(first.orderId(), second.orderId());
        assertNotEquals(first.paymentId(), second.paymentId());
        assertEquals(2, commerceClient.createdPayments.size());
    }

    @Test
    void c1UsesStableExecutionIdentityForDuplicateLogicalTransaction() {
        FakeCommerceClient commerceClient = new FakeCommerceClient();
        TransactionService service = new TransactionService(new FakeRepository(), commerceClient, 3);
        TransactionRequest request = request("logical-001");

        TransactionRecord first = service.execute(request, "same-key", "BASELINE", "f0-no-failure", 0.0, "7", "C1");
        TransactionRecord second = service.execute(request, "same-key", "BASELINE", "f0-no-failure", 0.0, "7", "C1");

        assertEquals("tx-logical-001", first.transactionId());
        assertEquals(first.transactionId(), second.transactionId());
        assertEquals(first.cartId(), second.cartId());
        assertEquals(first.orderId(), second.orderId());
        assertEquals(first.paymentId(), second.paymentId());
    }

    @Test
    void historicalBaselineKeepsDeterministicLogicalIdentityWhenNoV2HeaderIsPresent() {
        TransactionService service = new TransactionService(new FakeRepository(), new FakeCommerceClient(), 3);
        TransactionRequest request = request("logical-001");

        TransactionRecord record = service.execute(request, "same-key", "BASELINE", "f0-no-failure", 0.0, "7");

        assertEquals("tx-logical-001", record.transactionId());
    }

    @Test
    void historicalResilientModeStillUsesRepositoryStateWhenNoV2HeaderIsPresent() {
        FakeRepository repository = new FakeRepository();
        TransactionService service = new TransactionService(repository, new FakeCommerceClient(), 3);

        service.execute(request("logical-001"), "same-key", "RESILIENT", "f0-no-failure", 0.0, "7");

        assertEquals(1, repository.createCalls);
        assertEquals(5, repository.saveCalls);
    }

    private TransactionRequest request(String logicalTransactionId) {
        return new TransactionRequest(logicalTransactionId, "customer-001", "sku-001", 1, BigDecimal.valueOf(19.99), "USD");
    }

    private static class FakeCommerceClient extends CommerceClient {
        private final List<String> createdPayments = new ArrayList<>();

        FakeCommerceClient() {
            super(new org.springframework.boot.web.client.RestTemplateBuilder(), "http://cart", "http://order", "http://payment");
        }

        @Override
        CartResponse createCart(TransactionRecord record, TransactionRequest request, FailureHeaders headers) {
            return new CartResponse("cart-" + record.transactionId(), record.transactionId(), record.idempotencyKey(), request.customerId(), "OPEN", List.of());
        }

        @Override
        OrderResponse createOrder(TransactionRecord record, TransactionRequest request, FailureHeaders headers) {
            return new OrderResponse("order-" + record.transactionId(), record.transactionId(), record.idempotencyKey(), record.cartId(), request.customerId(), "ACTIVE");
        }

        @Override
        PaymentResponse executePayment(TransactionRecord record, TransactionRequest request, FailureHeaders headers) {
            String paymentId = "payment-" + record.transactionId();
            createdPayments.add(paymentId);
            return new PaymentResponse(paymentId, record.transactionId(), record.idempotencyKey(), record.orderId(), request.amount(), request.currency(), "SUCCEEDED");
        }
    }

    private static class FakeRepository extends TransactionRepository {
        private TransactionRecord record;
        private int createCalls;
        private int saveCalls;

        FakeRepository() {
            super(null);
        }

        @Override
        Optional<TransactionRecord> findByIdempotencyKey(String idempotencyKey) {
            return Optional.ofNullable(record);
        }

        @Override
        TransactionRecord create(String transactionId, String idempotencyKey) {
            createCalls++;
            record = new TransactionRecord(transactionId, idempotencyKey, TransactionState.STARTED, null, null, null, 0, 0, 0, null, false, false, false);
            return record;
        }

        @Override
        TransactionRecord save(TransactionRecord updated) {
            saveCalls++;
            record = updated;
            return record;
        }

        @Override
        List<TransactionRecord> intermediateRecords() {
            return record == null ? List.of() : List.of(record);
        }
    }
}
