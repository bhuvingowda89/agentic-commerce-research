package research.commerce.payment;

import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;

@Configuration
class PaymentSchema {
    @Bean
    ApplicationRunner initializePaymentSchema(JdbcTemplate jdbcTemplate) {
        return args -> jdbcTemplate.execute("""
            create table if not exists payments (
              payment_id text primary key,
              transaction_id text not null,
              idempotency_key text not null,
              order_id text not null,
              amount numeric not null,
              currency text not null,
              status text not null,
              created_at timestamptz not null default now()
            )
            """);
    }
}

