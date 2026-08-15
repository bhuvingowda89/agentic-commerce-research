package research.commerce.order;

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
class OrderController {
    private final JdbcTemplate jdbcTemplate;
    private final FailureInjection failureInjection;

    OrderController(JdbcTemplate jdbcTemplate, FailureInjection failureInjection) {
        this.jdbcTemplate = jdbcTemplate;
        this.failureInjection = failureInjection;
    }

    @PostMapping("/orders")
    @ResponseStatus(HttpStatus.CREATED)
    OrderResponse createOrder(
        @RequestBody CreateOrderRequest request,
        @RequestHeader(name = "X-Failure-Scenario", defaultValue = "f0-no-failure") String scenario,
        @RequestHeader(name = "X-Failure-Rate", defaultValue = "0.0") double failureRate,
        @RequestHeader(name = "X-Random-Seed", defaultValue = "7") String seed
    ) {
        String transactionId = required(request.transactionId(), "transactionId");
        String idempotencyKey = required(request.idempotencyKey(), "idempotencyKey");
        String cartId = required(request.cartId(), "cartId");
        String customerId = required(request.customerId(), "customerId");
        failureInjection.before("create_order", scenario, failureRate, seed, transactionId);
        String orderId = "order-" + transactionId;
        jdbcTemplate.update("""
            insert into orders(order_id, transaction_id, idempotency_key, cart_id, customer_id, status)
            values (?, ?, ?, ?, ?, 'ACTIVE')
            on conflict (order_id) do nothing
            """, orderId, transactionId, idempotencyKey, cartId, customerId);
        failureInjection.after("create_order", scenario, failureRate, seed, transactionId);
        return new OrderResponse(orderId, transactionId, idempotencyKey, cartId, customerId, "ACTIVE");
    }

    @PostMapping("/orders/{orderId}/cancel")
    OrderResponse cancelOrder(
        @PathVariable("orderId") String orderId,
        @RequestHeader(name = "X-Failure-Scenario", defaultValue = "f0-no-failure") String scenario,
        @RequestHeader(name = "X-Failure-Rate", defaultValue = "0.0") double failureRate,
        @RequestHeader(name = "X-Random-Seed", defaultValue = "7") String seed
    ) {
        failureInjection.before("cancel_order", scenario, failureRate, seed, orderId);
        jdbcTemplate.update("update orders set status = 'CANCELLED' where order_id = ?", orderId);
        return jdbcTemplate.queryForObject(
            "select order_id, transaction_id, idempotency_key, cart_id, customer_id, status from orders where order_id = ?",
            (rs, rowNum) -> new OrderResponse(
                rs.getString("order_id"),
                rs.getString("transaction_id"),
                rs.getString("idempotency_key"),
                rs.getString("cart_id"),
                rs.getString("customer_id"),
                rs.getString("status")
            ),
            orderId
        );
    }

    @GetMapping("/inspect/idempotency/{idempotencyKey}")
    OrderInspectResponse inspect(@PathVariable("idempotencyKey") String idempotencyKey) {
        List<String> orderIds = jdbcTemplate.queryForList(
            "select order_id from orders where idempotency_key = ? order by created_at",
            String.class,
            idempotencyKey
        );
        Integer activeCount = jdbcTemplate.queryForObject(
            "select count(*) from orders where idempotency_key = ? and status = 'ACTIVE'",
            Integer.class,
            idempotencyKey
        );
        return new OrderInspectResponse(orderIds.size(), activeCount == null ? 0 : activeCount, orderIds);
    }

    private String required(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, field + " is required");
        }
        return value.trim();
    }
}
