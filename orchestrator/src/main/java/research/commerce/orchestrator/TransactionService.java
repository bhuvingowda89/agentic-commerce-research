package research.commerce.orchestrator;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.ResourceAccessException;

@Service
class TransactionService {
    private final TransactionRepository repository;
    private final CommerceClient commerceClient;
    private final int maxAttempts;
    private final V2CrashPointRegistry crashPointRegistry;
    private final MechanismEventRepository mechanismEvents;

    @Autowired
    TransactionService(
        TransactionRepository repository,
        CommerceClient commerceClient,
        @Value("${retry.maxAttempts:3}") int maxAttempts,
        V2CrashPointRegistry crashPointRegistry,
        MechanismEventRepository mechanismEvents
    ) {
        this.repository = repository;
        this.commerceClient = commerceClient;
        this.maxAttempts = maxAttempts;
        this.crashPointRegistry = crashPointRegistry;
        this.mechanismEvents = mechanismEvents;
    }

    TransactionService(
        TransactionRepository repository,
        CommerceClient commerceClient,
        @Value("${retry.maxAttempts:3}") int maxAttempts,
        V2CrashPointRegistry crashPointRegistry
    ) {
        this(repository, commerceClient, maxAttempts, crashPointRegistry, null);
    }

    TransactionService(
        TransactionRepository repository,
        CommerceClient commerceClient,
        @Value("${retry.maxAttempts:3}") int maxAttempts
    ) {
        this(repository, commerceClient, maxAttempts, new V2CrashPointRegistry(), null);
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
        return execute(request, idempotencyKey, mode, scenario, failureRate, randomSeed, v2Configuration, null, null);
    }

    TransactionRecord execute(
        TransactionRequest request,
        String idempotencyKey,
        String mode,
        String scenario,
        double failureRate,
        String randomSeed,
        String v2Configuration,
        String v2CrashPoint,
        String v2CrashToken
    ) {
        if ("C0".equals(v2Configuration) || "C1".equals(v2Configuration)) {
            return executeV2CorrectedBaseline(request, idempotencyKey, scenario, failureRate, randomSeed, v2Configuration);
        }
        if (v2Configuration != null && !v2Configuration.isBlank()) {
            V2MechanismPolicy policy = V2MechanismPolicy.fromConfiguration(v2Configuration);
            return executeResilient(request, idempotencyKey, scenario, failureRate, randomSeed, v2CrashPoint, v2CrashToken, policy);
        }
        if ("BASELINE".equalsIgnoreCase(mode)) {
            return executeBaseline(request, idempotencyKey, scenario, failureRate, randomSeed);
        }
        return executeResilient(request, idempotencyKey, scenario, failureRate, randomSeed, v2CrashPoint, v2CrashToken);
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
        return recoverOne(idempotencyKey, scenario, failureRate, randomSeed, null);
    }

    TransactionRecord recoverOne(String idempotencyKey, String scenario, double failureRate, String randomSeed, String v2Configuration) {
        V2MechanismPolicy policy = V2MechanismPolicy.historicalResilient();
        if (v2Configuration != null && !v2Configuration.isBlank()) {
            policy = V2MechanismPolicy.fromConfiguration(v2Configuration);
            if (!policy.restartRecovery()) {
                recordEvent(idempotencyKey, "unknown", "RECOVERY_FAILED", "restart_recovery", "recover_one", null, null, "disabled:" + policy.name());
                throw new IllegalStateException("V2_RESTART_RECOVERY_DISABLED_FOR_" + policy.name());
            }
        }
        TransactionRecord record = repository.findByIdempotencyKey(idempotencyKey).orElseThrow();
        recordEvent(record, "RECOVERY_STARTED", "restart_recovery", "recover_one", record.state(), null, null, policy);
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
                true,
                null,
                null,
                policy
            );
            attempts++;
        }
        recordEvent(
            record,
            isTerminal(record.state()) ? "RECOVERY_SUCCEEDED" : "RECOVERY_FAILED",
            "restart_recovery",
            "recover_one",
            previous,
            record.state(),
            "attempts=" + attempts,
            policy
        );
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
        return executeResilient(request, idempotencyKey, scenario, failureRate, randomSeed, null, null);
    }

    private TransactionRecord executeResilient(
        TransactionRequest request,
        String idempotencyKey,
        String scenario,
        double failureRate,
        String randomSeed,
        String v2CrashPoint,
        String v2CrashToken
    ) {
        return executeResilient(
            request,
            idempotencyKey,
            scenario,
            failureRate,
            randomSeed,
            v2CrashPoint,
            v2CrashToken,
            V2MechanismPolicy.historicalResilient()
        );
    }

    private TransactionRecord executeResilient(
        TransactionRequest request,
        String idempotencyKey,
        String scenario,
        double failureRate,
        String randomSeed,
        String v2CrashPoint,
        String v2CrashToken,
        V2MechanismPolicy policy
    ) {
        TransactionRecord existing = repository.findByIdempotencyKey(idempotencyKey).orElse(null);
        if (existing != null && isTerminal(existing.state()) && policy.idempotentSideEffectLookup()) {
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
        return continueResilient(request, record, scenario, failureRate, randomSeed, false, v2CrashPoint, v2CrashToken, policy);
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
        return continueResilient(request, record, scenario, failureRate, randomSeed, recovered, null, null);
    }

    private TransactionRecord continueResilient(
        TransactionRequest request,
        TransactionRecord record,
        String scenario,
        double failureRate,
        String randomSeed,
        boolean recovered,
        String v2CrashPoint,
        String v2CrashToken
    ) {
        return continueResilient(
            request,
            record,
            scenario,
            failureRate,
            randomSeed,
            recovered,
            v2CrashPoint,
            v2CrashToken,
            V2MechanismPolicy.historicalResilient()
        );
    }

    private TransactionRecord continueResilient(
        TransactionRequest request,
        TransactionRecord record,
        String scenario,
        double failureRate,
        String randomSeed,
        boolean recovered,
        String v2CrashPoint,
        String v2CrashToken,
        V2MechanismPolicy policy
    ) {
        CommerceClient.FailureHeaders headers = new CommerceClient.FailureHeaders(scenario, failureRate, randomSeed);
        try {
            if (record.state() == TransactionState.STARTED) {
                TransactionRecord current = record;
                RetryCounter retryCounter = new RetryCounter();
                CartResponse cart = attemptWithPolicy(
                    "create_cart",
                    current,
                    () -> createCartWithPolicy(current, request, headers, policy),
                    retryCounter,
                    policy
                );
                record = withOperationRetries(record, retryCounter.count());
                record = repository.save(withCart(record, cart.cartId(), recovered));
            }

            if (record.state() == TransactionState.CART_CREATED) {
                CommerceClient.OrderResponse order;
                RetryCounter retryCounter = new RetryCounter();
                try {
                    TransactionRecord current = record;
                    order = attemptWithPolicy(
                        "create_order",
                        current,
                        () -> createOrderWithPolicy(current, request, headers, policy),
                        retryCounter,
                        policy
                    );
                    record = withOperationRetries(record, retryCounter.count());
                    record = repository.save(withOrder(record, order.orderId(), recovered));
                    awaitExternalCrashIfRequested(record, v2CrashPoint, v2CrashToken);
                } catch (ResourceAccessException ex) {
                    record = withOperationRetries(record, retryCounter.count());
                    if (policy.lostResponseReconciliation()) {
                        recordEvent(record, "RECONCILIATION_STARTED", "lost_response_reconciliation", "create_order", record.state(), null, rootMessage(ex), policy);
                    }
                    if (policy.lostResponseReconciliation() && commerceClient.inspect(record.idempotencyKey()).orderCount() > 0) {
                        recordEvent(record, "RECONCILIATION_FOUND_EFFECT", "lost_response_reconciliation", "create_order", record.state(), null, null, policy);
                        record = repository.save(withOrder(record, "order-" + record.transactionId(), recovered));
                        recordEvent(record, "RECONCILIATION_SUCCEEDED", "lost_response_reconciliation", "create_order", TransactionState.CART_CREATED, record.state(), null, policy);
                    } else {
                        if (policy.lostResponseReconciliation()) {
                            recordEvent(record, "RECONCILIATION_NOT_FOUND", "lost_response_reconciliation", "create_order", record.state(), null, null, policy);
                            recordEvent(record, "RECONCILIATION_FAILED", "lost_response_reconciliation", "create_order", record.state(), null, rootMessage(ex), policy);
                        }
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
                RetryCounter retryCounter = new RetryCounter();
                try {
                    TransactionRecord current = record;
                    payment = attemptWithPolicy(
                        "execute_payment",
                        current,
                        () -> executePaymentWithPolicy(current, request, headers, policy),
                        retryCounter,
                        policy
                    );
                    record = withOperationRetries(record, retryCounter.count());
                    record = repository.save(withPayment(record, payment.paymentId(), TransactionState.PAYMENT_COMPLETED, recovered));
                } catch (ResourceAccessException ex) {
                    record = withOperationRetries(record, retryCounter.count());
                    if (policy.lostResponseReconciliation()) {
                        recordEvent(record, "RECONCILIATION_STARTED", "lost_response_reconciliation", "execute_payment", record.state(), null, rootMessage(ex), policy);
                    }
                    if (policy.lostResponseReconciliation() && commerceClient.inspect(record.idempotencyKey()).successfulPaymentCount() > 0) {
                        recordEvent(record, "RECONCILIATION_FOUND_EFFECT", "lost_response_reconciliation", "execute_payment", record.state(), null, null, policy);
                        record = repository.save(withPayment(record, "payment-" + record.transactionId(), TransactionState.PAYMENT_COMPLETED, recovered));
                        recordEvent(record, "RECONCILIATION_SUCCEEDED", "lost_response_reconciliation", "execute_payment", TransactionState.PAYMENT_PENDING, record.state(), null, policy);
                    } else {
                        if (policy.lostResponseReconciliation()) {
                            recordEvent(record, "RECONCILIATION_NOT_FOUND", "lost_response_reconciliation", "execute_payment", record.state(), null, null, policy);
                            recordEvent(record, "RECONCILIATION_FAILED", "lost_response_reconciliation", "execute_payment", record.state(), null, rootMessage(ex), policy);
                        }
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
            return failOrCompensate(record, ex, recovered, headers, policy);
        }
    }

    private TransactionRecord failOrCompensate(TransactionRecord record, Exception ex, boolean recovered, CommerceClient.FailureHeaders headers, V2MechanismPolicy policy) {
        if (record.orderId() != null && policy.compensation()) {
            recordEvent(record, "COMPENSATION_STARTED", "compensation", "cancel_order", record.state(), TransactionState.COMPENSATING, rootMessage(ex), policy);
            TransactionRecord compensating = repository.save(withState(record, TransactionState.COMPENSATING, recovered));
            int retries = 0;
            while (true) {
                try {
                    commerceClient.cancelOrder(compensating.orderId(), headers);
                    int compensationRetries = compensating.compensationRetryCount() + retries;
                    TransactionRecord compensated = repository.save(new TransactionRecord(
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
                    recordEvent(compensated, "COMPENSATION_SUCCEEDED", "compensation", "cancel_order", TransactionState.COMPENSATING, compensated.state(), "retries=" + retries, policy);
                    return compensated;
                } catch (Exception compensationFailure) {
                    retries++;
                    if (retries >= maxAttempts) {
                        break;
                    }
                    recordEvent(compensating, "COMPENSATION_RETRY", "compensation", "cancel_order", TransactionState.COMPENSATING, TransactionState.COMPENSATING, rootMessage(compensationFailure), policy);
                }
            }
            recordEvent(compensating, "COMPENSATION_FAILED", "compensation", "cancel_order", TransactionState.COMPENSATING, TransactionState.COMPENSATING, "exhausted", policy);
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

    private CartResponse createCartWithPolicy(
        TransactionRecord record,
        TransactionRequest request,
        CommerceClient.FailureHeaders headers,
        V2MechanismPolicy policy
    ) {
        if (policy.v2() && policy.idempotentSideEffectLookup()) {
            recordEvent(record, "IDEMPOTENT_LOOKUP_ATTEMPT", "idempotent_side_effect_lookup", "create_cart", record.state(), record.state(), null, policy);
            if (commerceClient.inspect(record.idempotencyKey()).cartCount() > 0) {
                recordEvent(record, "IDEMPOTENT_LOOKUP_FOUND", "idempotent_side_effect_lookup", "create_cart", record.state(), record.state(), null, policy);
                return new CartResponse("cart-" + record.transactionId(), record.transactionId(), record.idempotencyKey(), request.customerId(), "OPEN", List.of());
            }
            recordEvent(record, "IDEMPOTENT_LOOKUP_NOT_FOUND", "idempotent_side_effect_lookup", "create_cart", record.state(), record.state(), null, policy);
        }
        return commerceClient.createCart(record, request, headers);
    }

    private CommerceClient.OrderResponse createOrderWithPolicy(
        TransactionRecord record,
        TransactionRequest request,
        CommerceClient.FailureHeaders headers,
        V2MechanismPolicy policy
    ) {
        if (policy.v2() && policy.idempotentSideEffectLookup()) {
            recordEvent(record, "IDEMPOTENT_LOOKUP_ATTEMPT", "idempotent_side_effect_lookup", "create_order", record.state(), record.state(), null, policy);
            if (commerceClient.inspect(record.idempotencyKey()).orderCount() > 0) {
                recordEvent(record, "IDEMPOTENT_LOOKUP_FOUND", "idempotent_side_effect_lookup", "create_order", record.state(), record.state(), null, policy);
                return new CommerceClient.OrderResponse("order-" + record.transactionId(), record.transactionId(), record.idempotencyKey(), record.cartId(), request.customerId(), "ACTIVE");
            }
            recordEvent(record, "IDEMPOTENT_LOOKUP_NOT_FOUND", "idempotent_side_effect_lookup", "create_order", record.state(), record.state(), null, policy);
        }
        return commerceClient.createOrder(record, request, headers);
    }

    private CommerceClient.PaymentResponse executePaymentWithPolicy(
        TransactionRecord record,
        TransactionRequest request,
        CommerceClient.FailureHeaders headers,
        V2MechanismPolicy policy
    ) {
        if (policy.v2() && policy.idempotentSideEffectLookup()) {
            recordEvent(record, "IDEMPOTENT_LOOKUP_ATTEMPT", "idempotent_side_effect_lookup", "execute_payment", record.state(), record.state(), null, policy);
            if (commerceClient.inspect(record.idempotencyKey()).successfulPaymentCount() > 0) {
                recordEvent(record, "IDEMPOTENT_LOOKUP_FOUND", "idempotent_side_effect_lookup", "execute_payment", record.state(), record.state(), null, policy);
                return new CommerceClient.PaymentResponse("payment-" + record.transactionId(), record.transactionId(), record.idempotencyKey(), record.orderId(), request.amount(), request.currency(), "SUCCEEDED");
            }
            recordEvent(record, "IDEMPOTENT_LOOKUP_NOT_FOUND", "idempotent_side_effect_lookup", "execute_payment", record.state(), record.state(), null, policy);
        }
        return commerceClient.executePayment(record, request, headers);
    }

    private <T> T attemptWithPolicy(String operationName, TransactionRecord record, Operation<T> operation, RetryCounter retryCounter, V2MechanismPolicy policy) {
        if (policy.boundedRetry()) {
            return retry(operationName, record, operation, retryCounter, policy);
        }
        return operation.run();
    }

    private <T> T retry(String operationName, TransactionRecord record, Operation<T> operation, RetryCounter retryCounter, V2MechanismPolicy policy) {
        RuntimeException last = null;
        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                T value = operation.run();
                if (attempt > 1) {
                    recordEvent(record, "RETRY_SUCCEEDED", "bounded_retry", operationName, record.state(), record.state(), "attempt=" + attempt, policy);
                }
                return value;
            } catch (RuntimeException ex) {
                last = ex;
                if (attempt == maxAttempts || !isTransient(ex)) {
                    if (attempt > 1 || isTransient(ex)) {
                        recordEvent(record, "RETRY_EXHAUSTED", "bounded_retry", operationName, record.state(), record.state(), rootMessage(ex), policy);
                    }
                    throw ex;
                }
                retryCounter.increment();
                recordEvent(record, "RETRY_ATTEMPT", "bounded_retry", operationName, record.state(), record.state(), "nextAttempt=" + (attempt + 1), policy);
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

    private void awaitExternalCrashIfRequested(TransactionRecord record, String v2CrashPoint, String v2CrashToken) {
        if (!"after-order-persisted".equals(v2CrashPoint)) {
            return;
        }
        crashPointRegistry.reached(v2CrashToken, v2CrashPoint, record.transactionId(), record.state().name());
        crashPointRegistry.awaitKill(v2CrashToken);
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

    private void recordEvent(
        TransactionRecord record,
        String eventType,
        String mechanism,
        String operation,
        TransactionState stateBefore,
        TransactionState stateAfter,
        String detail,
        V2MechanismPolicy policy
    ) {
        if (!policy.v2()) {
            return;
        }
        recordEvent(record.idempotencyKey(), record.transactionId(), eventType, mechanism, operation, stateBefore, stateAfter, detail);
    }

    private void recordEvent(
        String idempotencyKey,
        String transactionId,
        String eventType,
        String mechanism,
        String operation,
        TransactionState stateBefore,
        TransactionState stateAfter,
        String detail
    ) {
        if (mechanismEvents == null) {
            return;
        }
        mechanismEvents.record(idempotencyKey, transactionId, eventType, mechanism, operation, stateBefore, stateAfter, detail);
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
