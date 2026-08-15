package research.commerce.orchestrator;

import java.math.BigDecimal;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.HttpStatusCode;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.RestTemplate;

@Component
class CommerceClient {
    private final RestTemplate restTemplate;
    private final String cartBaseUrl;
    private final String orderBaseUrl;
    private final String paymentBaseUrl;

    CommerceClient(
        RestTemplateBuilder builder,
        @Value("${commerce.cart-service.base-url}") String cartBaseUrl,
        @Value("${commerce.order-service.base-url}") String orderBaseUrl,
        @Value("${commerce.payment-service.base-url}") String paymentBaseUrl
    ) {
        this.restTemplate = builder
            .setConnectTimeout(Duration.ofMillis(500))
            .setReadTimeout(Duration.ofMillis(500))
            .build();
        this.cartBaseUrl = cartBaseUrl;
        this.orderBaseUrl = orderBaseUrl;
        this.paymentBaseUrl = paymentBaseUrl;
    }

    CartResponse createCart(TransactionRecord record, TransactionRequest request, FailureHeaders headers) {
        return post(cartBaseUrl + "/carts", new CartCreate(record.transactionId(), record.idempotencyKey(), request.customerId()), headers, CartResponse.class);
    }

    OrderResponse createOrder(TransactionRecord record, TransactionRequest request, FailureHeaders headers) {
        return post(orderBaseUrl + "/orders", new OrderCreate(record.transactionId(), record.idempotencyKey(), record.cartId(), request.customerId()), headers, OrderResponse.class);
    }

    PaymentResponse executePayment(TransactionRecord record, TransactionRequest request, FailureHeaders headers) {
        return post(paymentBaseUrl + "/payments", new PaymentCreate(record.transactionId(), record.idempotencyKey(), record.orderId(), request.amount(), request.currency()), headers, PaymentResponse.class);
    }

    void cancelOrder(String orderId, FailureHeaders headers) {
        restTemplate.postForEntity(orderBaseUrl + "/orders/" + orderId + "/cancel", new org.springframework.http.HttpEntity<>(null, headers.toHttpHeaders()), OrderResponse.class);
    }

    ServiceState inspect(String idempotencyKey) {
        CartInspectResponse carts = restTemplate.getForObject(cartBaseUrl + "/inspect/idempotency/" + idempotencyKey, CartInspectResponse.class);
        OrderInspectResponse orders = restTemplate.getForObject(orderBaseUrl + "/inspect/idempotency/" + idempotencyKey, OrderInspectResponse.class);
        PaymentInspectResponse payments = restTemplate.getForObject(paymentBaseUrl + "/inspect/idempotency/" + idempotencyKey, PaymentInspectResponse.class);
        return new ServiceState(
            carts == null ? 0 : carts.cartCount(),
            orders == null ? 0 : orders.orderCount(),
            orders == null ? 0 : orders.activeOrderCount(),
            payments == null ? 0 : payments.successfulPaymentCount()
        );
    }

    private <T> T post(String url, Object body, FailureHeaders headers, Class<T> responseType) {
        try {
            return restTemplate.postForEntity(url, new org.springframework.http.HttpEntity<>(body, headers.toHttpHeaders()), responseType).getBody();
        } catch (RestClientResponseException ex) {
            if (ex.getStatusCode().isSameCodeAs(HttpStatusCode.valueOf(500))) {
                throw new IllegalStateException(ex.getResponseBodyAsString(), ex);
            }
            throw ex;
        }
    }

    record FailureHeaders(String scenario, double failureRate, String randomSeed) {
        org.springframework.http.HttpHeaders toHttpHeaders() {
            org.springframework.http.HttpHeaders headers = new org.springframework.http.HttpHeaders();
            headers.set("X-Failure-Scenario", scenario);
            headers.set("X-Failure-Rate", Double.toString(failureRate));
            headers.set("X-Random-Seed", randomSeed);
            return headers;
        }
    }

    record CartCreate(String transactionId, String idempotencyKey, String customerId) {}
    record OrderCreate(String transactionId, String idempotencyKey, String cartId, String customerId) {}
    record PaymentCreate(String transactionId, String idempotencyKey, String orderId, BigDecimal amount, String currency) {}
    record OrderResponse(String orderId, String transactionId, String idempotencyKey, String cartId, String customerId, String status) {}
    record PaymentResponse(String paymentId, String transactionId, String idempotencyKey, String orderId, BigDecimal amount, String currency, String status) {}
    record CartInspectResponse(int cartCount, java.util.List<String> cartIds) {}
    record OrderInspectResponse(int orderCount, int activeOrderCount, java.util.List<String> orderIds) {}
    record PaymentInspectResponse(int successfulPaymentCount, java.util.List<String> paymentIds) {}
    record ServiceState(int cartCount, int orderCount, int activeOrderCount, int successfulPaymentCount) {}
}
