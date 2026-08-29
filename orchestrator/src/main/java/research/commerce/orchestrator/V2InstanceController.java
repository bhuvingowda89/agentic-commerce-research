package research.commerce.orchestrator;

import java.time.Instant;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
class V2InstanceController {
    private final OrchestratorInstance instance;

    V2InstanceController(OrchestratorInstance instance) {
        this.instance = instance;
    }

    @GetMapping("/v2/instance")
    InstanceResponse instance() {
        return new InstanceResponse(instance.instanceId(), instance.startedAt());
    }

    record InstanceResponse(String orchestratorInstanceId, Instant startedAt) {
    }
}
