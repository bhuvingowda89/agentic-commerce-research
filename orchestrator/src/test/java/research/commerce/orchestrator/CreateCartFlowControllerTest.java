package research.commerce.orchestrator;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class CreateCartFlowControllerTest {
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        CreateCartFlowService fakeService = new CreateCartFlowService(null) {
            @Override
            CartResponse createCart(CreateCartFlowRequest request) {
                return new CartResponse("cart-customer-001", "tx-001", "key-001", "customer-001", "OPEN", List.of());
            }
        };

        mockMvc = MockMvcBuilders
            .standaloneSetup(new CreateCartFlowController(fakeService), new HealthController())
            .build();
    }

    @Test
    void healthReturnsUp() throws Exception {
        mockMvc.perform(get("/health"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.status").value("UP"))
            .andExpect(jsonPath("$.service").value("orchestrator"));
    }

    @Test
    void createCartFlowReturnsCartFromService() throws Exception {
        mockMvc.perform(post("/flows/create-cart")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"customerId\":\"customer-001\"}"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.cartId").value("cart-customer-001"))
            .andExpect(jsonPath("$.customerId").value("customer-001"))
            .andExpect(jsonPath("$.status").value("OPEN"));
    }
}
