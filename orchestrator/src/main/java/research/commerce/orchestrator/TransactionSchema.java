package research.commerce.orchestrator;

import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;

@Configuration
class TransactionSchema {
    @Bean
    ApplicationRunner initializeTransactionSchema(JdbcTemplate jdbcTemplate) {
        return args -> {
            jdbcTemplate.execute("""
            create table if not exists orchestrator_transactions (
              transaction_id text primary key,
              idempotency_key text not null unique,
              current_state text not null,
              cart_id text,
              order_id text,
              payment_id text,
              retry_count integer not null default 0,
              operation_retry_count integer not null default 0,
              compensation_retry_count integer not null default 0,
              failure_reason text,
              recovered boolean not null default false,
              compensated boolean not null default false,
              created_at timestamptz not null default now(),
              updated_at timestamptz not null default now()
            )
            """);
            jdbcTemplate.execute("alter table orchestrator_transactions add column if not exists operation_retry_count integer not null default 0");
            jdbcTemplate.execute("alter table orchestrator_transactions add column if not exists compensation_retry_count integer not null default 0");
        };
    }
}
