package research.commerce.order;

import java.nio.charset.StandardCharsets;
import java.util.Optional;
import java.util.zip.CRC32;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

@Component
class FailureInjection {
    void before(String operation, String scenario, double failureRate, String seed, String transactionId) {
        if ("f2-order-http-500".equals(scenario) && "create_order".equals(operation) && shouldFail(failureRate, seed, transactionId, operation)) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "ORDER_HTTP_500");
        }
        if ("f12-compensation-failure-retry".equals(scenario) && "cancel_order".equals(operation)) {
            String key = operation + ":" + transactionId;
            int attempts = attemptsByKey.merge(key, 1, Integer::sum);
            if (attempts == 1) {
                throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "COMPENSATION_TRANSIENT_FAILURE");
            }
        }
    }

    private final java.util.Map<String, Integer> attemptsByKey = new java.util.concurrent.ConcurrentHashMap<>();

    void after(String operation, String scenario, double failureRate, String seed, String transactionId) {
        if ("f6-order-succeeds-response-lost".equals(scenario) && "create_order".equals(operation) && shouldFail(failureRate, seed, transactionId, operation)) {
            sleepPastClientTimeout();
        }
    }

    private boolean shouldFail(double failureRate, String seed, String transactionId, String operation) {
        if (failureRate <= 0.0) {
            return false;
        }
        CRC32 crc32 = new CRC32();
        crc32.update((Optional.ofNullable(seed).orElse("7") + ":" + transactionId + ":" + operation).getBytes(StandardCharsets.UTF_8));
        return ((crc32.getValue() % 10_000) / 10_000.0) < failureRate;
    }

    private void sleepPastClientTimeout() {
        try {
            Thread.sleep(1_500);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        }
    }
}
