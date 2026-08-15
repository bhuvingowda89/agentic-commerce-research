package research.commerce.orchestrator;

import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
class TransactionRepository {
    private final JdbcTemplate jdbcTemplate;

    TransactionRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    Optional<TransactionRecord> findByIdempotencyKey(String idempotencyKey) {
        List<TransactionRecord> records = jdbcTemplate.query(
            "select * from orchestrator_transactions where idempotency_key = ?",
            (rs, rowNum) -> new TransactionRecord(
                rs.getString("transaction_id"),
                rs.getString("idempotency_key"),
                TransactionState.valueOf(rs.getString("current_state")),
                rs.getString("cart_id"),
                rs.getString("order_id"),
                rs.getString("payment_id"),
                rs.getInt("retry_count"),
                rs.getInt("operation_retry_count"),
                rs.getInt("compensation_retry_count"),
                rs.getString("failure_reason"),
                rs.getBoolean("recovered"),
                rs.getBoolean("compensated"),
                false
            ),
            idempotencyKey
        );
        return records.stream().findFirst();
    }

    TransactionRecord create(String transactionId, String idempotencyKey) {
        jdbcTemplate.update("""
            insert into orchestrator_transactions(transaction_id, idempotency_key, current_state)
            values (?, ?, ?)
            on conflict do nothing
            """, transactionId, idempotencyKey, TransactionState.STARTED.name());
        return findByIdempotencyKey(idempotencyKey).orElseThrow();
    }

    TransactionRecord save(TransactionRecord record) {
        jdbcTemplate.update("""
            update orchestrator_transactions
            set current_state = ?, cart_id = ?, order_id = ?, payment_id = ?, retry_count = ?,
                operation_retry_count = ?, compensation_retry_count = ?,
                failure_reason = ?, recovered = ?, compensated = ?, updated_at = now()
            where transaction_id = ?
            """,
            record.state().name(),
            record.cartId(),
            record.orderId(),
            record.paymentId(),
            record.retryCount(),
            record.operationRetryCount(),
            record.compensationRetryCount(),
            record.failureReason(),
            record.recovered(),
            record.compensated(),
            record.transactionId()
        );
        return findByIdempotencyKey(record.idempotencyKey()).orElseThrow();
    }

    List<TransactionRecord> intermediateRecords() {
        return jdbcTemplate.query(
            """
            select * from orchestrator_transactions
            where current_state not in ('COMPLETED', 'COMPENSATED', 'FAILED')
            order by updated_at
            """,
            (rs, rowNum) -> new TransactionRecord(
                rs.getString("transaction_id"),
                rs.getString("idempotency_key"),
                TransactionState.valueOf(rs.getString("current_state")),
                rs.getString("cart_id"),
                rs.getString("order_id"),
                rs.getString("payment_id"),
                rs.getInt("retry_count"),
                rs.getInt("operation_retry_count"),
                rs.getInt("compensation_retry_count"),
                rs.getString("failure_reason"),
                rs.getBoolean("recovered"),
                rs.getBoolean("compensated"),
                false
            )
        );
    }
}
