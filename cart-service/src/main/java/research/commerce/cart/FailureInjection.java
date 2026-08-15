package research.commerce.cart;

import java.nio.charset.StandardCharsets;
import java.util.Optional;
import java.util.zip.CRC32;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

@Component
class FailureInjection {
    void before(String operation, String scenario, double failureRate, String seed, String transactionId) {
        if ("f1-cart-http-500".equals(scenario) && "create_cart".equals(operation) && shouldFail(failureRate, seed, transactionId, operation)) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "CART_HTTP_500");
        }
    }

    void after(String operation, String scenario, double failureRate, String seed, String transactionId) {
        if ("cart-persisted-response-lost".equals(scenario) && "create_cart".equals(operation) && shouldFail(failureRate, seed, transactionId, operation)) {
            sleepPastClientTimeout();
        }
    }

    private boolean shouldFail(double failureRate, String seed, String transactionId, String operation) {
        if (failureRate <= 0.0) {
            return false;
        }
        CRC32 crc32 = new CRC32();
        crc32.update((Optional.ofNullable(seed).orElse("7") + ":" + transactionId + ":" + operation).getBytes(StandardCharsets.UTF_8));
        double sample = (crc32.getValue() % 10_000) / 10_000.0;
        return sample < failureRate;
    }

    private void sleepPastClientTimeout() {
        try {
            Thread.sleep(1_500);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        }
    }
}

