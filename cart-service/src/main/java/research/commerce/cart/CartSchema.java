package research.commerce.cart;

import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;

@Configuration
class CartSchema {
    @Bean
    ApplicationRunner initializeCartSchema(JdbcTemplate jdbcTemplate) {
        return args -> jdbcTemplate.execute("""
            create table if not exists carts (
              cart_id text primary key,
              transaction_id text not null,
              idempotency_key text not null,
              customer_id text not null,
              status text not null,
              created_at timestamptz not null default now()
            )
            """);
    }
}

