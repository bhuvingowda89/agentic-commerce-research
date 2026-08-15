package research.commerce.order;

import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;

@Configuration
class OrderSchema {
    @Bean
    ApplicationRunner initializeOrderSchema(JdbcTemplate jdbcTemplate) {
        return args -> jdbcTemplate.execute("""
            create table if not exists orders (
              order_id text primary key,
              transaction_id text not null,
              idempotency_key text not null,
              cart_id text not null,
              customer_id text not null,
              status text not null,
              created_at timestamptz not null default now()
            )
            """);
    }
}

