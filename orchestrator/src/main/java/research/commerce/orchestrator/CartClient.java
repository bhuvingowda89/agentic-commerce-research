package research.commerce.orchestrator;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
class CartClient {
    private final RestClient restClient;

    CartClient(
        RestClient.Builder restClientBuilder,
        @Value("${commerce.cart-service.base-url}") String cartServiceBaseUrl
    ) {
        this.restClient = restClientBuilder.baseUrl(cartServiceBaseUrl).build();
    }

    CartResponse createCart(CreateCartFlowRequest request) {
        String customerId = request.customerId() == null ? "" : request.customerId().trim();
        return restClient.post()
            .uri("/carts")
            .body(new CartCreateRequest("create-cart-flow-" + customerId, "create-cart-flow-" + customerId, customerId))
            .retrieve()
            .body(CartResponse.class);
    }
}
