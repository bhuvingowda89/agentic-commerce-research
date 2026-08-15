package research.commerce.orchestrator;

import org.springframework.stereotype.Service;

@Service
class CreateCartFlowService {
    private final CartClient cartClient;

    CreateCartFlowService(CartClient cartClient) {
        this.cartClient = cartClient;
    }

    CartResponse createCart(CreateCartFlowRequest request) {
        return cartClient.createCart(request);
    }
}

