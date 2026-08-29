package research.commerce.orchestrator;

import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Component;

@Component
class OrchestratorInstance {
    private final String instanceId = UUID.randomUUID().toString();
    private final Instant startedAt = Instant.now();

    String instanceId() {
        return instanceId;
    }

    Instant startedAt() {
        return startedAt;
    }
}
