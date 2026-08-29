package research.commerce.orchestrator;

import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
class MechanismEventRepository {
    private final JdbcTemplate jdbcTemplate;

    MechanismEventRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    void record(
        String idempotencyKey,
        String transactionId,
        String eventType,
        String mechanism,
        String operation,
        TransactionState stateBefore,
        TransactionState stateAfter,
        String detail
    ) {
        jdbcTemplate.update("""
            insert into orchestrator_mechanism_events(
              idempotency_key, transaction_id, event_type, mechanism, operation,
              state_before, state_after, detail
            )
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            idempotencyKey,
            transactionId,
            eventType,
            mechanism,
            operation,
            stateBefore == null ? null : stateBefore.name(),
            stateAfter == null ? null : stateAfter.name(),
            detail
        );
    }

    List<MechanismEvent> findByIdempotencyKey(String idempotencyKey) {
        return jdbcTemplate.query(
            """
            select event_id, idempotency_key, transaction_id, event_type, mechanism,
                   operation, state_before, state_after, detail, created_at
            from orchestrator_mechanism_events
            where idempotency_key = ?
            order by event_id
            """,
            (rs, rowNum) -> new MechanismEvent(
                rs.getLong("event_id"),
                rs.getString("idempotency_key"),
                rs.getString("transaction_id"),
                rs.getString("event_type"),
                rs.getString("mechanism"),
                rs.getString("operation"),
                rs.getString("state_before"),
                rs.getString("state_after"),
                rs.getString("detail"),
                rs.getTimestamp("created_at").toInstant()
            ),
            idempotencyKey
        );
    }
}
