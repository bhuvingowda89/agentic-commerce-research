package research.commerce.orchestrator;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class V2CrashInfrastructureTest {
    @Test
    void instanceEndpointExposesStableRuntimeInstanceId() throws Exception {
        OrchestratorInstance instance = new OrchestratorInstance();
        MockMvc mockMvc = MockMvcBuilders.standaloneSetup(new V2InstanceController(instance)).build();

        mockMvc.perform(get("/v2/instance"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.orchestratorInstanceId").value(instance.instanceId()));
    }

    @Test
    void separateRuntimeInstancesReceiveDifferentIds() {
        assertNotEquals(new OrchestratorInstance().instanceId(), new OrchestratorInstance().instanceId());
    }

    @Test
    void crashPointStatusReportsReachedDurableState() {
        V2CrashPointRegistry registry = new V2CrashPointRegistry();

        registry.reached("token-1", "after-order-persisted", "tx-1", "ORDER_CREATED");

        V2CrashPointRegistry.CrashPointStatus status = registry.status("token-1");
        assertTrue(status.reached());
        assertEquals("after-order-persisted", status.point());
        assertEquals("tx-1", status.transactionId());
        assertEquals("ORDER_CREATED", status.state());
    }

    @Test
    void c2RejectsExplicitRestartRecovery() {
        TransactionService service = new TransactionService(new FakeRepository(), new FakeCommerceClient(), 3, new V2CrashPointRegistry());

        assertThrows(
            IllegalStateException.class,
            () -> service.recoverOne("same-key", "f0-no-failure", 0.0, "7", "C2")
        );
    }

    @Test
    void transactionCanReachAfterOrderCrashPointBeforeExternalKill() throws Exception {
        V2CrashPointRegistry registry = new V2CrashPointRegistry();
        TransactionService service = new TransactionService(new FakeRepository(), new FakeCommerceClient(), 3, registry);
        ExecutorService executor = Executors.newSingleThreadExecutor();

        var future = executor.submit(() -> service.execute(
            request("logical-001"),
            "same-key",
            "RESILIENT",
            "f0-no-failure",
            0.0,
            "7",
            "C7",
            "after-order-persisted",
            "token-1"
        ));

        V2CrashPointRegistry.CrashPointStatus status = waitForCrashPoint(registry, "token-1");
        assertTrue(status.reached());
        assertEquals("ORDER_CREATED", status.state());

        future.cancel(true);
        executor.shutdownNow();
        executor.awaitTermination(1, TimeUnit.SECONDS);
    }

    private V2CrashPointRegistry.CrashPointStatus waitForCrashPoint(V2CrashPointRegistry registry, String token) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
        while (System.nanoTime() < deadline) {
            V2CrashPointRegistry.CrashPointStatus status = registry.status(token);
            if (status.reached()) {
                return status;
            }
            Thread.sleep(10);
        }
        return registry.status(token);
    }

    private TransactionRequest request(String logicalTransactionId) {
        return new TransactionRequest(logicalTransactionId, "customer-001", "sku-001", 1, BigDecimal.valueOf(19.99), "USD");
    }

    private static class FakeCommerceClient extends CommerceClient {
        FakeCommerceClient() {
            super(new RestTemplateBuilder(), "http://cart", "http://order", "http://payment");
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
            return new PaymentResponse("payment-" + record.transactionId(), record.transactionId(), record.idempotencyKey(), record.orderId(), request.amount(), request.currency(), "SUCCEEDED");
        }
    }

    private static class FakeRepository extends TransactionRepository {
        private TransactionRecord record;

        FakeRepository() {
            super(null);
        }

        @Override
        Optional<TransactionRecord> findByIdempotencyKey(String idempotencyKey) {
            return Optional.ofNullable(record);
        }

        @Override
        TransactionRecord create(String transactionId, String idempotencyKey) {
            record = new TransactionRecord(transactionId, idempotencyKey, TransactionState.STARTED, null, null, null, 0, 0, 0, null, false, false, false);
            return record;
        }

        @Override
        TransactionRecord save(TransactionRecord updated) {
            record = updated;
            return record;
        }
    }
}
