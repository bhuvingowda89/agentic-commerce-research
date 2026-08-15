package research.commerce.payment;

import java.math.BigDecimal;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
class PaymentController {
    private final JdbcTemplate jdbcTemplate;
    private final FailureInjection failureInjection;

    PaymentController(JdbcTemplate jdbcTemplate, FailureInjection failureInjection) {
        this.jdbcTemplate = jdbcTemplate;
        this.failureInjection = failureInjection;
    }

    @PostMapping("/payments")
    @ResponseStatus(HttpStatus.CREATED)
    PaymentResponse executePayment(
        @RequestBody PaymentRequest request,
        @RequestHeader(name = "X-Failure-Scenario", defaultValue = "f0-no-failure") String scenario,
        @RequestHeader(name = "X-Failure-Rate", defaultValue = "0.0") double failureRate,
        @RequestHeader(name = "X-Random-Seed", defaultValue = "7") String seed
    ) {
        String transactionId = required(request.transactionId(), "transactionId");
        String idempotencyKey = required(request.idempotencyKey(), "idempotencyKey");
        String orderId = required(request.orderId(), "orderId");
        failureInjection.before("execute_payment", scenario, failureRate, seed, transactionId);
        String paymentId = "payment-" + transactionId;
        jdbcTemplate.update("""
            insert into payments(payment_id, transaction_id, idempotency_key, order_id, amount, currency, status)
            values (?, ?, ?, ?, ?, ?, 'SUCCEEDED')
            on conflict (payment_id) do nothing
            """, paymentId, transactionId, idempotencyKey, orderId, request.amount(), request.currency());
        failureInjection.after("execute_payment", scenario, failureRate, seed, transactionId);
        return new PaymentResponse(paymentId, transactionId, idempotencyKey, orderId, request.amount(), request.currency(), "SUCCEEDED");
    }

    @GetMapping("/inspect/idempotency/{idempotencyKey}")
    PaymentInspectResponse inspect(@PathVariable("idempotencyKey") String idempotencyKey) {
        List<String> paymentIds = jdbcTemplate.queryForList(
            "select payment_id from payments where idempotency_key = ? and status = 'SUCCEEDED' order by created_at",
            String.class,
            idempotencyKey
        );
        return new PaymentInspectResponse(paymentIds.size(), paymentIds);
    }

    private String required(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, field + " is required");
        }
        return value.trim();
    }
}
