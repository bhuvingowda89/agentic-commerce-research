package research.commerce.orchestrator;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.ResourceAccessException;

@Service
class TransactionService {
    private final TransactionRepository repository;
    private final CommerceClient commerceClient;
    private final int maxAttempts;

    TransactionService(
        TransactionRepository repository,
        CommerceClient commerceClient,
        @Value("${retry.maxAttempts:3}") int maxAttempts
    ) {
        this.repository = repository;
        this.commerceClient = commerceClient;
        this.maxAttempts = maxAttempts;
    }

    TransactionRecord execute(
        TransactionRequest request,
        String idempotencyKey,
        String mode,
        String scenario,
        double failureRate,
        String randomSeed
    ) {
        return execute(request, idempotencyKey, mode, scenario, failureRate, randomSeed, null);
    }

    TransactionRecord execute(
        TransactionRequest request,
        String idempotencyKey,
        String mode,
        String scenario,
        double failureRate,
        String randomSeed,
        String v2Configuration
    ) {
        if (v2Configuration != null && !v2Configuration.isBlank()) {
            return executeV2CorrectedBaseline(request, idempotencyKey, scenario, failureRate, randomSeed, v2Configuration);
        }
        if ("BASELINE".equalsIgnoreCase(mode)) {
            return executeBaseline(request, idempotencyKey, scenario, failureRate, randomSeed);
        }
        return executeResilient(request, idempotencyKey, scenario, failureRate, randomSeed);
    }

    private TransactionRecord executeV2CorrectedBaseline(
        TransactionRequest request,
        String idempotencyKey,
        String scenario,
        double failureRate,
        String randomSeed,
        String v2Configuration
    ) {
        if (!"C0".equals(v2Configuration) && !"C1".equals(v2Configuration)) {
            throw new IllegalArgumentException("Only v2 corrected baseline configurations C0 and C1 are supported in this phase");
        }
        String transactionId = "C0".equals(v2Configuration)
            ? "tx-v2-c0-" + UUID.randomUUID()
            : transactionIdFor(request);
        TransactionRecord record = new TransactionRecord(
            transactionId,
            idempotencyKey,
            TransactionState.STARTED,
            null,
            null,
            null,
            0,
            0,
            0,
            null,
            false,
            false,
            false
        );
        CommerceClient.FailureHeaders headers = new CommerceClient.FailureHeaders(scenario, failureRate, randomSeed);
        CartResponse cart = commerceClient.createCart(record, request, headers);
        record = withCart(record, cart.cartId());
        CommerceClient.OrderResponse order = commerceClient.createOrder(record, request, headers);
        record = withOrder(record, order.orderId());
        if ("f9-orchestrator-interruption-after-order".equals(scenario)) {
            throw new IllegalStateException("SIMULATED_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER");
        }
        CommerceClient.PaymentResponse payment = commerceClient.executePayment(record, request, headers);
        return withPayment(record, payment.paymentId(), TransactionState.COMPLETED);
    }

    List<TransactionRecord> recover(String scenario, double failureRate, String randomSeed) {
        return repository.intermediateRecords().stream()
            .map(record -> continueResilient(
                new TransactionRequest("recovered", "recovered-customer", "sku-001", 1, BigDecimal.valueOf(19.99), "USD"),
                record,
                scenario,
                failureRate,
                randomSeed,
                true
            ))
            .toList();
    }

    TransactionRecord recoverOne(String idempotencyKey, String scenario, double failureRate, String randomSeed) {
        TransactionRecord record = repository.findByIdempotencyKey(idempotencyKey).orElseThrow();
        TransactionState previous = null;
        int attempts = 0;
        while (!isTerminal(record.state()) && record.state() != previous && attempts < maxAttempts) {
            previous = record.state();
            record = continueResilient(
                new TransactionRequest("recovered", "recovered-customer", "sku-001", 1, BigDecimal.valueOf(19.99), "USD"),
                record,
                scenario,
                failureRate,
                randomSeed,
                true
            );
            attempts++;
        }
        return record;
    }

    private TransactionRecord executeBaseline(
        TransactionRequest request,
        String idempotencyKey,
        String scenario,
        double failureRate,
        String randomSeed
    ) {
        TransactionRecord record = new TransactionRecord(
            transactionIdFor(request),
            idempotencyKey,
            TransactionState.STARTED,
            null,
            null,
            null,
            0,
            0,
            0,
            null,
            false,
            false,
            false
        );
        CommerceClient.FailureHeaders headers = new CommerceClient.FailureHeaders(scenario, failureRate, randomSeed);
        CartResponse cart = commerceClient.createCart(record, request, headers);
        record = withCart(record, cart.cartId());
        CommerceClient.OrderResponse order = commerceClient.createOrder(record, request, headers);
        record = withOrder(record, order.orderId());
        if ("f9-orchestrator-interruption-after-order".equals(scenario)) {
            throw new IllegalStateException("SIMULATED_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER");
        }
        CommerceClient.PaymentResponse payment = commerceClient.executePayment(record, request, headers);
        return withPayment(record, payment.paymentId(), TransactionState.COMPLETED);
    }

    private TransactionRecord executeResilient(
        TransactionRequest request,
        String idempotencyKey,
        String scenario,
        double failureRate,
        String randomSeed
    ) {
        TransactionRecord existing = repository.findByIdempotencyKey(idempotencyKey).orElse(null);
        if (existing != null && isTerminal(existing.state())) {
            return new TransactionRecord(
                existing.transactionId(),
                existing.idempotencyKey(),
                existing.state(),
                existing.cartId(),
                existing.orderId(),
                existing.paymentId(),
                existing.retryCount(),
                existing.operationRetryCount(),
                existing.compensationRetryCount(),
                existing.failureReason(),
                existing.recovered(),
                existing.compensated(),
                true
            );
        }

        TransactionRecord record = existing == null
            ? repository.create(transactionIdFor(request), idempotencyKey)
            : existing;
        return continueResilient(request, record, scenario, failureRate, randomSeed, false);
    }

    private String transactionIdFor(TransactionRequest request) {
        if (request.logicalTransactionId() != null && !request.logicalTransactionId().isBlank()) {
            return "tx-" + request.logicalTransactionId();
        }
        return UUID.nameUUIDFromBytes((request.customerId() + ":" + request.sku()).getBytes(StandardCharsets.UTF_8)).toString();
    }

    private TransactionRecord continueResilient(
        TransactionRequest request,
        TransactionRecord record,
        String scenario,
        double failureRate,
        String randomSeed,
        boolean recovered
    ) {
        CommerceClient.FailureHeaders headers = new CommerceClient.FailureHeaders(scenario, failureRate, randomSeed);
        try {
            if (record.state() == TransactionState.STARTED) {
                TransactionRecord current = record;
                RetryCounter retryCounter = new RetryCounter();
                CartResponse cart = retry(() -> commerceClient.createCart(current, request, headers), retryCounter);
                record = withOperationRetries(record, retryCounter.count());
                record = repository.save(withCart(record, cart.cartId(), recovered));
            }

            if (record.state() == TransactionState.CART_CREATED) {
                CommerceClient.OrderResponse order;
                try {
                    TransactionRecord current = record;
                    RetryCounter retryCounter = new RetryCounter();
                    order = retry(() -> commerceClient.createOrder(current, request, headers), retryCounter);
                    record = withOperationRetries(record, retryCounter.count());
                    record = repository.save(withOrder(record, order.orderId(), recovered));
                } catch (ResourceAccessException ex) {
                    CommerceClient.ServiceState state = commerceClient.inspect(record.idempotencyKey());
                    if (state.orderCount() > 0) {
                        record = repository.save(withOrder(record, "order-" + record.transactionId(), recovered));
                    } else {
                        throw ex;
                    }
                }
                if ("f9-orchestrator-interruption-after-order".equals(scenario) && !recovered) {
                    throw new IllegalStateException("SIMULATED_ORCHESTRATOR_INTERRUPTION_AFTER_ORDER");
                }
            }

            if (record.state() == TransactionState.ORDER_CREATED) {
                record = repository.save(withState(record, TransactionState.PAYMENT_PENDING, recovered));
            }

            if (record.state() == TransactionState.PAYMENT_PENDING) {
                CommerceClient.PaymentResponse payment;
                try {
                    TransactionRecord current = record;
                    RetryCounter retryCounter = new RetryCounter();
                    payment = retry(() -> commerceClient.executePayment(current, request, headers), retryCounter);
                    record = withOperationRetries(record, retryCounter.count());
                    record = repository.save(withPayment(record, payment.paymentId(), TransactionState.PAYMENT_COMPLETED, recovered));
                } catch (ResourceAccessException ex) {
                    CommerceClient.ServiceState state = commerceClient.inspect(record.idempotencyKey());
                    if (state.successfulPaymentCount() > 0) {
                        record = repository.save(withPayment(record, "payment-" + record.transactionId(), TransactionState.PAYMENT_COMPLETED, recovered));
                    } else {
                        throw ex;
                    }
                }
            }

            if (record.state() == TransactionState.PAYMENT_COMPLETED) {
                return repository.save(withState(record, TransactionState.COMPLETED, recovered));
            }
            return record;
        } catch (Exception ex) {
            if (rootMessage(ex).contains("SIMULATED_ORCHESTRATOR_INTERRUPTION")) {
                throw ex;
            }
            return failOrCompensate(record, ex, recovered, headers);
        }
    }

    private TransactionRecord failOrCompensate(TransactionRecord record, Exception ex, boolean recovered, CommerceClient.FailureHeaders headers) {
        if (record.orderId() != null) {
            TransactionRecord compensating = repository.save(withState(record, TransactionState.COMPENSATING, recovered));
            int retries = 0;
            while (true) {
                try {
                    commerceClient.cancelOrder(compensating.orderId(), headers);
                    int compensationRetries = compensating.compensationRetryCount() + retries;
                    return repository.save(new TransactionRecord(
                        compensating.transactionId(),
                        compensating.idempotencyKey(),
                        TransactionState.COMPENSATED,
                        compensating.cartId(),
                        compensating.orderId(),
                        compensating.paymentId(),
                        compensating.operationRetryCount() + compensationRetries,
                        compensating.operationRetryCount(),
                        compensationRetries,
                        rootMessage(ex),
                        recovered,
                        true,
                        compensating.duplicateDetected()
                    ));
                } catch (Exception compensationFailure) {
                    retries++;
                    if (retries >= maxAttempts) {
                        break;
                    }
                }
            }
        }
        return repository.save(new TransactionRecord(
            record.transactionId(),
            record.idempotencyKey(),
            TransactionState.FAILED,
            record.cartId(),
            record.orderId(),
            record.paymentId(),
            record.retryCount(),
            record.operationRetryCount(),
            record.compensationRetryCount(),
            rootMessage(ex),
            recovered,
            false,
            record.duplicateDetected()
        ));
    }

    private <T> T retry(Operation<T> operation, RetryCounter retryCounter) {
        RuntimeException last = null;
        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                return operation.run();
            } catch (RuntimeException ex) {
                last = ex;
                if (attempt == maxAttempts || !isTransient(ex)) {
                    throw ex;
                }
                retryCounter.increment();
            }
        }
        throw last == null ? new IllegalStateException("operation failed") : last;
    }

    private boolean isTransient(RuntimeException ex) {
        String message = rootMessage(ex);
        return ex instanceof ResourceAccessException
            || message.contains("TRANSIENT")
            || message.contains("TIMEOUT")
            || (ex instanceof RestClientResponseException response && response.getStatusCode().value() == 503);
    }

    private boolean isTerminal(TransactionState state) {
        return state == TransactionState.COMPLETED || state == TransactionState.COMPENSATED || state == TransactionState.FAILED;
    }

    private TransactionRecord withCart(TransactionRecord record, String cartId) {
        return withCart(record, cartId, record.recovered());
    }

    private TransactionRecord withCart(TransactionRecord record, String cartId, boolean recovered) {
        return new TransactionRecord(record.transactionId(), record.idempotencyKey(), TransactionState.CART_CREATED, cartId, record.orderId(), record.paymentId(), record.retryCount(), record.operationRetryCount(), record.compensationRetryCount(), record.failureReason(), recovered, record.compensated(), record.duplicateDetected());
    }

    private TransactionRecord withOrder(TransactionRecord record, String orderId) {
        return withOrder(record, orderId, record.recovered());
    }

    private TransactionRecord withOrder(TransactionRecord record, String orderId, boolean recovered) {
        return new TransactionRecord(record.transactionId(), record.idempotencyKey(), TransactionState.ORDER_CREATED, record.cartId(), orderId, record.paymentId(), record.retryCount(), record.operationRetryCount(), record.compensationRetryCount(), record.failureReason(), recovered, record.compensated(), record.duplicateDetected());
    }

    private TransactionRecord withPayment(TransactionRecord record, String paymentId, TransactionState state) {
        return withPayment(record, paymentId, state, record.recovered());
    }

    private TransactionRecord withPayment(TransactionRecord record, String paymentId, TransactionState state, boolean recovered) {
        return new TransactionRecord(record.transactionId(), record.idempotencyKey(), state, record.cartId(), record.orderId(), paymentId, record.retryCount(), record.operationRetryCount(), record.compensationRetryCount(), record.failureReason(), recovered, record.compensated(), record.duplicateDetected());
    }

    private TransactionRecord withState(TransactionRecord record, TransactionState state, boolean recovered) {
        return new TransactionRecord(record.transactionId(), record.idempotencyKey(), state, record.cartId(), record.orderId(), record.paymentId(), record.retryCount(), record.operationRetryCount(), record.compensationRetryCount(), record.failureReason(), recovered, record.compensated(), record.duplicateDetected());
    }

    private TransactionRecord withOperationRetries(TransactionRecord record, int additionalRetries) {
        if (additionalRetries == 0) {
            return record;
        }
        int operationRetries = record.operationRetryCount() + additionalRetries;
        return new TransactionRecord(record.transactionId(), record.idempotencyKey(), record.state(), record.cartId(), record.orderId(), record.paymentId(), operationRetries + record.compensationRetryCount(), operationRetries, record.compensationRetryCount(), record.failureReason(), record.recovered(), record.compensated(), record.duplicateDetected());
    }

    private String rootMessage(Exception ex) {
        return ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage();
    }

    private interface Operation<T> {
        T run();
    }

    private static class RetryCounter {
        private int count;

        void increment() {
            count++;
        }

        int count() {
            return count;
        }
    }
}
