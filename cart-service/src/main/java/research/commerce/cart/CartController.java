package research.commerce.cart;

import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
class CartController {
    private final JdbcTemplate jdbcTemplate;
    private final FailureInjection failureInjection;

    CartController(JdbcTemplate jdbcTemplate, FailureInjection failureInjection) {
        this.jdbcTemplate = jdbcTemplate;
        this.failureInjection = failureInjection;
    }

    @PostMapping("/carts")
    @ResponseStatus(HttpStatus.CREATED)
    CartResponse createCart(
        @RequestBody CreateCartRequest request,
        @RequestHeader(name = "X-Failure-Scenario", defaultValue = "f0-no-failure") String scenario,
        @RequestHeader(name = "X-Failure-Rate", defaultValue = "0.0") double failureRate,
        @RequestHeader(name = "X-Random-Seed", defaultValue = "7") String seed
    ) {
        if (request == null || request.customerId() == null || request.customerId().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "customerId is required");
        }

        String transactionId = required(request.transactionId(), "transactionId");
        String idempotencyKey = required(request.idempotencyKey(), "idempotencyKey");
        String normalizedCustomerId = request.customerId().trim();
        failureInjection.before("create_cart", scenario, failureRate, seed, transactionId);
        String cartId = "cart-" + transactionId;
        jdbcTemplate.update("""
            insert into carts(cart_id, transaction_id, idempotency_key, customer_id, status)
            values (?, ?, ?, ?, 'OPEN')
            on conflict (cart_id) do nothing
            """, cartId, transactionId, idempotencyKey, normalizedCustomerId);
        failureInjection.after("create_cart", scenario, failureRate, seed, transactionId);
        return new CartResponse(cartId, transactionId, idempotencyKey, normalizedCustomerId, "OPEN", List.of());
    }

    @GetMapping("/inspect/idempotency/{idempotencyKey}")
    CartInspectResponse inspect(@PathVariable("idempotencyKey") String idempotencyKey) {
        List<String> cartIds = jdbcTemplate.queryForList(
            "select cart_id from carts where idempotency_key = ? order by created_at",
            String.class,
            idempotencyKey
        );
        return new CartInspectResponse(cartIds.size(), cartIds);
    }

    private String required(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, field + " is required");
        }
        return value.trim();
    }
}
