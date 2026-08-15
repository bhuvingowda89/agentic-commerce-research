package research.commerce.orchestrator;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
class CreateCartFlowController {
    private final CreateCartFlowService createCartFlowService;

    CreateCartFlowController(CreateCartFlowService createCartFlowService) {
        this.createCartFlowService = createCartFlowService;
    }

    @PostMapping("/flows/create-cart")
    CartResponse createCart(@RequestBody CreateCartFlowRequest request) {
        return createCartFlowService.createCart(request);
    }
}

