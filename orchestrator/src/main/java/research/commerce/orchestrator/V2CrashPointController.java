package research.commerce.orchestrator;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

@RestController
class V2CrashPointController {
    private final V2CrashPointRegistry registry;

    V2CrashPointController(V2CrashPointRegistry registry) {
        this.registry = registry;
    }

    @GetMapping("/v2/crash-points/{token}")
    V2CrashPointRegistry.CrashPointStatus status(@PathVariable("token") String token) {
        return registry.status(token);
    }
}
