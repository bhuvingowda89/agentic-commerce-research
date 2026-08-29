package research.commerce.orchestrator;

import java.time.Instant;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.springframework.stereotype.Component;

@Component
class V2CrashPointRegistry {
    private final Map<String, CrashPoint> crashPoints = new ConcurrentHashMap<>();

    void reached(String token, String point, String transactionId, String state) {
        if (token == null || token.isBlank()) {
            return;
        }
        crashPoints.computeIfAbsent(token, ignored -> new CrashPoint()).markReached(point, transactionId, state);
    }

    CrashPointStatus status(String token) {
        CrashPoint crashPoint = crashPoints.get(token);
        if (crashPoint == null) {
            return new CrashPointStatus(token, false, null, null, null, null);
        }
        return crashPoint.status(token);
    }

    void awaitKill(String token) {
        if (token == null || token.isBlank()) {
            return;
        }
        try {
            crashPoints.computeIfAbsent(token, ignored -> new CrashPoint()).awaitKill();
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        }
    }

    private static class CrashPoint {
        private final CountDownLatch killLatch = new CountDownLatch(1);
        private volatile boolean reached;
        private volatile String point;
        private volatile String transactionId;
        private volatile String state;
        private volatile Instant reachedAt;

        void markReached(String point, String transactionId, String state) {
            this.reached = true;
            this.point = point;
            this.transactionId = transactionId;
            this.state = state;
            this.reachedAt = Instant.now();
        }

        void awaitKill() throws InterruptedException {
            killLatch.await(1, TimeUnit.HOURS);
        }

        CrashPointStatus status(String token) {
            return new CrashPointStatus(token, reached, point, transactionId, state, reachedAt);
        }
    }

    record CrashPointStatus(String token, boolean reached, String point, String transactionId, String state, Instant reachedAt) {
    }
}
