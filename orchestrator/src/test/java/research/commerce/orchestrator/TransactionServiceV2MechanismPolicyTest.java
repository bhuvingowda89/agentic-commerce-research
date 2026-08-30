package research.commerce.orchestrator;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.web.client.ResourceAccessException;

class TransactionServiceV2MechanismPolicyTest {
    @Test
    void policyTableMatchesApprovedConfigurationSemantics() {
        assertPolicy("C2", true, true, false, false, false, false, false);
        assertPolicy("C3", true, true, false, true, false, false, false);
        assertPolicy("C4", true, true, true, false, false, false, false);
        assertPolicy("C5", true, true, true, false, true, false, false);
        assertPolicy("C6", true, true, false, false, false, true, false);
        assertPolicy("C7", true, true, true, false, false, false, true);
        assertPolicy("C8", true, true, true, true, true, true, true);
        assertThrows(IllegalArgumentException.class, () -> V2MechanismPolicy.fromConfiguration("C9"));
    }

    @Test
    void c2PersistsStateButDoesNotRetryReconcileCompensateOrRecover() {
        FakeCommerceClient client = new FakeCommerceClient();
        client.paymentTransientFailuresRemaining = 1;
        FakeRepository repository = new FakeRepository();
        TransactionService service = new TransactionService(repository, client, 3);

        TransactionRecord record = service.execute(request("logical-001"), "same-key", "RESILIENT", "f11-transient-payment-failure-recovery", 1.0, "7", "C2");

        assertEquals(TransactionState.FAILED, record.state());
        assertEquals("tx-logical-001", record.transactionId());
        assertEquals(1, repository.createCalls);
        assertTrue(repository.saveCalls > 0);
        assertEquals(1, client.paymentCalls);
        assertEquals(0, record.operationRetryCount());
        assertEquals(0, client.inspectCalls);
        assertEquals(0, client.cancelCalls);
        assertThrows(IllegalStateException.class, () -> service.recoverOne("same-key", "f0-no-failure", 0.0, "7", "C2"));
    }

    @Test
    void c3RetriesPreSideEffectTransientPaymentFailureWithoutReconciliationOrCompensation() {
        FakeCommerceClient client = new FakeCommerceClient();
        client.paymentTransientFailuresRemaining = 2;
        FakeMechanismEventRepository events = new FakeMechanismEventRepository();
        TransactionService service = new TransactionService(new FakeRepository(), client, 3, new V2CrashPointRegistry(), events);

        TransactionRecord record = service.execute(request("logical-001"), "same-key", "RESILIENT", "f11-transient-payment-failure-recovery", 1.0, "7", "C3");

        assertEquals(TransactionState.COMPLETED, record.state());
        assertEquals(3, client.paymentCalls);
        assertEquals(2, record.operationRetryCount());
        assertEquals(0, client.inspectCalls);
        assertEquals(0, client.cancelCalls);
        assertTrue(events.has("RETRY_ATTEMPT", "bounded_retry", "execute_payment"));
        assertTrue(events.has("RETRY_SUCCEEDED", "bounded_retry", "execute_payment"));
    }

    @Test
    void c3RecordsRetryExhaustionWithoutReconciliationOrCompensation() {
        FakeCommerceClient client = new FakeCommerceClient();
        client.paymentTransientFailuresRemaining = 5;
        FakeMechanismEventRepository events = new FakeMechanismEventRepository();
        TransactionService service = new TransactionService(new FakeRepository(), client, 3, new V2CrashPointRegistry(), events);

        TransactionRecord record = service.execute(request("logical-001"), "same-key", "RESILIENT", "f11-transient-payment-failure-recovery", 1.0, "7", "C3");

        assertEquals(TransactionState.FAILED, record.state());
        assertEquals(3, client.paymentCalls);
        assertEquals(2, record.operationRetryCount());
        assertEquals(0, client.inspectCalls);
        assertEquals(0, client.cancelCalls);
        assertTrue(record.failureReason().contains("TRANSIENT_PAYMENT_FAILURE"));
        assertTrue(events.has("RETRY_EXHAUSTED", "bounded_retry", "execute_payment"));
    }

    @Test
    void c4ReusesExistingSideEffectsButDoesNotReconcileLostResponses() {
        FakeCommerceClient client = new FakeCommerceClient();
        client.serviceState = new CommerceClient.ServiceState(1, 1, 1, 1);
        TransactionService service = new TransactionService(new FakeRepository(), client, 3);

        TransactionRecord record = service.execute(request("logical-001"), "same-key", "RESILIENT", "f0-no-failure", 0.0, "7", "C4");

        assertEquals(TransactionState.COMPLETED, record.state());
        assertEquals("cart-tx-logical-001", record.cartId());
        assertEquals("order-tx-logical-001", record.orderId());
        assertEquals("payment-tx-logical-001", record.paymentId());
        assertEquals(0, client.cartCalls);
        assertEquals(0, client.orderCalls);
        assertEquals(0, client.paymentCalls);
        assertTrue(client.inspectCalls >= 3);

        FakeCommerceClient lostResponseClient = new FakeCommerceClient();
        lostResponseClient.paymentLostResponseCreatesSideEffect = true;
        TransactionRecord failed = new TransactionService(new FakeRepository(), lostResponseClient, 3)
            .execute(request("logical-002"), "lost-key", "RESILIENT", "f5-payment-succeeds-response-lost", 1.0, "7", "C4");

        assertEquals(TransactionState.FAILED, failed.state());
        assertEquals(1, lostResponseClient.paymentCalls);
        assertEquals(1, lostResponseClient.successfulPayments);
        assertEquals(0, lostResponseClient.cancelCalls);
    }

    @Test
    void c5ReconcilesPostSideEffectPaymentResponseLoss() {
        FakeCommerceClient client = new FakeCommerceClient();
        client.paymentLostResponseCreatesSideEffect = true;
        FakeMechanismEventRepository events = new FakeMechanismEventRepository();
        TransactionService service = new TransactionService(new FakeRepository(), client, 3, new V2CrashPointRegistry(), events);

        TransactionRecord record = service.execute(request("logical-001"), "same-key", "RESILIENT", "f5-payment-succeeds-response-lost", 1.0, "7", "C5");

        assertEquals(TransactionState.COMPLETED, record.state());
        assertEquals("payment-tx-logical-001", record.paymentId());
        assertEquals(1, client.paymentCalls);
        assertTrue(client.inspectCalls >= 4);
        assertEquals(1, client.successfulPayments);
        assertEquals(0, record.operationRetryCount());
        assertTrue(events.has("RECONCILIATION_STARTED", "lost_response_reconciliation", "execute_payment"));
        assertTrue(events.has("RECONCILIATION_FOUND_EFFECT", "lost_response_reconciliation", "execute_payment"));
        assertTrue(events.has("RECONCILIATION_SUCCEEDED", "lost_response_reconciliation", "execute_payment"));
    }

    @Test
    void c5FailsWhenReconciliationFindsNoExistingEffect() {
        FakeCommerceClient client = new FakeCommerceClient();
        client.paymentLostResponseWithoutSideEffect = true;
        TransactionService service = new TransactionService(new FakeRepository(), client, 3);

        TransactionRecord record = service.execute(request("logical-001"), "same-key", "RESILIENT", "f5-payment-succeeds-response-lost", 1.0, "7", "C5");

        assertEquals(TransactionState.FAILED, record.state());
        assertEquals(1, client.paymentCalls);
        assertTrue(client.inspectCalls >= 4);
        assertEquals(0, client.successfulPayments);
    }

    @Test
    void c6CompensatesAfterPermanentPaymentFailureAndRetriesCompensation() {
        FakeCommerceClient client = new FakeCommerceClient();
        client.paymentPermanentFailure = true;
        client.cancelTransientFailuresRemaining = 1;
        FakeMechanismEventRepository events = new FakeMechanismEventRepository();
        TransactionService service = new TransactionService(new FakeRepository(), client, 3, new V2CrashPointRegistry(), events);

        TransactionRecord record = service.execute(request("logical-001"), "same-key", "RESILIENT", "f12-compensation-failure-retry", 1.0, "7", "C6");

        assertEquals(TransactionState.COMPENSATED, record.state());
        assertTrue(record.compensated());
        assertEquals(2, client.cancelCalls);
        assertEquals(1, record.compensationRetryCount());
        assertEquals(0, client.inspectCalls);
        assertEquals(1, client.paymentCalls);
        assertTrue(events.has("COMPENSATION_STARTED", "compensation", "cancel_order"));
        assertTrue(events.has("COMPENSATION_RETRY", "compensation", "cancel_order"));
        assertTrue(events.has("COMPENSATION_SUCCEEDED", "compensation", "cancel_order"));
    }

    @Test
    void c7AllowsRestartRecoveryButDoesNotEnableRetryReconciliationOrCompensation() {
        FakeRepository repository = new FakeRepository();
        TransactionRecord interrupted = new TransactionRecord(
            "tx-logical-001",
            "same-key",
            TransactionState.ORDER_CREATED,
            "cart-tx-logical-001",
            "order-tx-logical-001",
            null,
            0,
            0,
            0,
            null,
            false,
            false,
            false
        );
        repository.record = interrupted;
        FakeCommerceClient client = new FakeCommerceClient();
        FakeMechanismEventRepository events = new FakeMechanismEventRepository();
        TransactionService service = new TransactionService(repository, client, 3, new V2CrashPointRegistry(), events);

        TransactionRecord recovered = service.recoverOne("same-key", "f0-no-failure", 0.0, "7", "C7");

        assertEquals(TransactionState.COMPLETED, recovered.state());
        assertTrue(recovered.recovered());
        assertEquals("tx-logical-001", recovered.transactionId());
        assertEquals("order-tx-logical-001", recovered.orderId());
        assertEquals(1, client.paymentCalls);
        assertEquals(0, client.cancelCalls);
        assertEquals(0, recovered.operationRetryCount());
        assertEquals(0, recovered.compensationRetryCount());
        assertThrows(IllegalStateException.class, () -> service.recoverOne("same-key", "f0-no-failure", 0.0, "7", "C3"));
        assertTrue(events.has("RECOVERY_STARTED", "restart_recovery", "recover_one"));
        assertTrue(events.has("RECOVERY_SUCCEEDED", "restart_recovery", "recover_one"));
    }

    @Test
    void c8CombinesRetryReconciliationCompensationAndRestartRecovery() {
        FakeCommerceClient retryClient = new FakeCommerceClient();
        retryClient.paymentTransientFailuresRemaining = 1;
        TransactionRecord retryRecord = new TransactionService(new FakeRepository(), retryClient, 3)
            .execute(request("logical-001"), "retry-key", "RESILIENT", "f11-transient-payment-failure-recovery", 1.0, "7", "C8");
        assertEquals(TransactionState.COMPLETED, retryRecord.state());
        assertEquals(1, retryRecord.operationRetryCount());

        FakeCommerceClient reconciliationClient = new FakeCommerceClient();
        reconciliationClient.paymentLostResponseCreatesSideEffect = true;
        TransactionRecord reconciled = new TransactionService(new FakeRepository(), reconciliationClient, 3)
            .execute(request("logical-002"), "reconcile-key", "RESILIENT", "f5-payment-succeeds-response-lost", 1.0, "7", "C8");
        assertEquals(TransactionState.COMPLETED, reconciled.state());
        assertTrue(reconciliationClient.inspectCalls > 0);

        FakeCommerceClient compensationClient = new FakeCommerceClient();
        compensationClient.paymentPermanentFailure = true;
        TransactionRecord compensated = new TransactionService(new FakeRepository(), compensationClient, 3)
            .execute(request("logical-003"), "comp-key", "RESILIENT", "f12-compensation-failure-retry", 1.0, "7", "C8");
        assertEquals(TransactionState.COMPENSATED, compensated.state());
    }

    private static void assertPolicy(
        String name,
        boolean deterministicIdentity,
        boolean durableState,
        boolean idempotentLookup,
        boolean boundedRetry,
        boolean reconciliation,
        boolean compensation,
        boolean restartRecovery
    ) {
        V2MechanismPolicy policy = V2MechanismPolicy.fromConfiguration(name);
        assertTrue(policy.v2());
        assertEquals(deterministicIdentity, policy.deterministicIdentity());
        assertEquals(durableState, policy.durableState());
        assertEquals(idempotentLookup, policy.idempotentSideEffectLookup());
        assertEquals(boundedRetry, policy.boundedRetry());
        assertEquals(reconciliation, policy.lostResponseReconciliation());
        assertEquals(compensation, policy.compensation());
        assertEquals(restartRecovery, policy.restartRecovery());
    }

    private TransactionRequest request(String logicalTransactionId) {
        return new TransactionRequest(logicalTransactionId, "customer-001", "sku-001", 1, BigDecimal.valueOf(19.99), "USD");
    }

    private static class FakeCommerceClient extends CommerceClient {
        private int cartCalls;
        private int orderCalls;
        private int paymentCalls;
        private int inspectCalls;
        private int cancelCalls;
        private int paymentTransientFailuresRemaining;
        private int cancelTransientFailuresRemaining;
        private int successfulPayments;
        private boolean paymentLostResponseCreatesSideEffect;
        private boolean paymentLostResponseWithoutSideEffect;
        private boolean paymentPermanentFailure;
        private CommerceClient.ServiceState serviceState = new CommerceClient.ServiceState(0, 0, 0, 0);

        FakeCommerceClient() {
            super(new RestTemplateBuilder(), "http://cart", "http://order", "http://payment");
        }

        @Override
        CartResponse createCart(TransactionRecord record, TransactionRequest request, FailureHeaders headers) {
            cartCalls++;
            return new CartResponse("cart-" + record.transactionId(), record.transactionId(), record.idempotencyKey(), request.customerId(), "OPEN", List.of());
        }

        @Override
        OrderResponse createOrder(TransactionRecord record, TransactionRequest request, FailureHeaders headers) {
            orderCalls++;
            return new OrderResponse("order-" + record.transactionId(), record.transactionId(), record.idempotencyKey(), record.cartId(), request.customerId(), "ACTIVE");
        }

        @Override
        PaymentResponse executePayment(TransactionRecord record, TransactionRequest request, FailureHeaders headers) {
            paymentCalls++;
            if (paymentTransientFailuresRemaining > 0) {
                paymentTransientFailuresRemaining--;
                throw new ResourceAccessException("TRANSIENT_PAYMENT_FAILURE");
            }
            if (paymentLostResponseCreatesSideEffect) {
                successfulPayments++;
                serviceState = new CommerceClient.ServiceState(serviceState.cartCount(), serviceState.orderCount(), serviceState.activeOrderCount(), successfulPayments);
                throw new ResourceAccessException("PAYMENT_RESPONSE_LOST_AFTER_SIDE_EFFECT");
            }
            if (paymentLostResponseWithoutSideEffect) {
                throw new ResourceAccessException("PAYMENT_RESPONSE_LOST_WITHOUT_SIDE_EFFECT");
            }
            if (paymentPermanentFailure) {
                throw new IllegalStateException("PAYMENT_PERMANENTLY_FAILS");
            }
            successfulPayments++;
            return new PaymentResponse("payment-" + record.transactionId(), record.transactionId(), record.idempotencyKey(), record.orderId(), request.amount(), request.currency(), "SUCCEEDED");
        }

        @Override
        void cancelOrder(String orderId, FailureHeaders headers) {
            cancelCalls++;
            if (cancelTransientFailuresRemaining > 0) {
                cancelTransientFailuresRemaining--;
                throw new ResourceAccessException("COMPENSATION_TRANSIENT_FAILURE");
            }
        }

        @Override
        ServiceState inspect(String idempotencyKey) {
            inspectCalls++;
            return serviceState;
        }
    }

    private static class FakeRepository extends TransactionRepository {
        private final Map<String, TransactionRecord> records = new HashMap<>();
        private TransactionRecord record;
        private int createCalls;
        private int saveCalls;

        FakeRepository() {
            super(null);
        }

        @Override
        Optional<TransactionRecord> findByIdempotencyKey(String idempotencyKey) {
            if (record != null && record.idempotencyKey().equals(idempotencyKey)) {
                return Optional.of(record);
            }
            return Optional.ofNullable(records.get(idempotencyKey));
        }

        @Override
        TransactionRecord create(String transactionId, String idempotencyKey) {
            createCalls++;
            TransactionRecord created = new TransactionRecord(transactionId, idempotencyKey, TransactionState.STARTED, null, null, null, 0, 0, 0, null, false, false, false);
            records.putIfAbsent(idempotencyKey, created);
            record = records.get(idempotencyKey);
            return record;
        }

        @Override
        TransactionRecord save(TransactionRecord updated) {
            saveCalls++;
            records.put(updated.idempotencyKey(), updated);
            record = updated;
            return updated;
        }

        @Override
        List<TransactionRecord> intermediateRecords() {
            return records.values().stream().filter(item -> item.state() != TransactionState.COMPLETED && item.state() != TransactionState.COMPENSATED && item.state() != TransactionState.FAILED).toList();
        }
    }

    private static class FakeMechanismEventRepository extends MechanismEventRepository {
        private final List<MechanismEvent> events = new ArrayList<>();

        FakeMechanismEventRepository() {
            super(null);
        }

        @Override
        void record(
            String idempotencyKey,
            String transactionId,
            String eventType,
            String mechanism,
            String operation,
            TransactionState stateBefore,
            TransactionState stateAfter,
            String detail
        ) {
            events.add(new MechanismEvent(
                events.size() + 1,
                idempotencyKey,
                transactionId,
                eventType,
                mechanism,
                operation,
                stateBefore == null ? null : stateBefore.name(),
                stateAfter == null ? null : stateAfter.name(),
                detail,
                Instant.EPOCH
            ));
        }

        boolean has(String eventType, String mechanism, String operation) {
            return events.stream().anyMatch(event ->
                event.eventType().equals(eventType)
                    && event.mechanism().equals(mechanism)
                    && event.operation().equals(operation)
            );
        }
    }
}
