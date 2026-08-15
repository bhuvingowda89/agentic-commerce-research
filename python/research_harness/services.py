from __future__ import annotations

from .failures import FailureInjector
from .models import Cart, Order, Payment, PaymentStatus, TransactionRequest


class CommerceServices:
    def __init__(self, failure_injector: FailureInjector):
        self.failure_injector = failure_injector
        self.carts: dict[str, Cart] = {}
        self.orders: dict[str, Order] = {}
        self.payments: dict[str, Payment] = {}

    def create_cart(self, request: TransactionRequest, transaction_id: str) -> Cart:
        operation = f"create_cart:{transaction_id}"
        self.failure_injector.before_operation(operation)
        cart = Cart(
            cart_id=f"cart-{transaction_id}",
            transaction_id=transaction_id,
            idempotency_key=request.idempotency_key,
            customer_id=request.customer_id,
        )
        self.carts[cart.cart_id] = cart
        self.failure_injector.after_operation(operation)
        return cart

    def add_item(self, cart_id: str, request: TransactionRequest) -> Cart:
        self.failure_injector.before_operation(f"add_item:{cart_id}")
        cart = self.carts[cart_id]
        cart.items.append({"sku": request.sku, "quantity": request.quantity})
        self.failure_injector.after_operation(f"add_item:{cart_id}")
        return cart

    def create_order(self, cart_id: str, request: TransactionRequest, transaction_id: str) -> Order:
        operation = f"create_order:{transaction_id}"
        self.failure_injector.before_operation(operation)
        order = Order(
            order_id=f"order-{transaction_id}",
            transaction_id=transaction_id,
            idempotency_key=request.idempotency_key,
            cart_id=cart_id,
            customer_id=request.customer_id,
        )
        self.orders[order.order_id] = order
        self.failure_injector.after_operation(operation)
        return order

    def execute_payment(self, order_id: str, request: TransactionRequest, transaction_id: str) -> Payment:
        operation = f"execute_payment:{transaction_id}"
        self.failure_injector.before_operation(operation)
        payment = Payment(
            payment_id=f"payment-{transaction_id}",
            transaction_id=transaction_id,
            idempotency_key=request.idempotency_key,
            order_id=order_id,
            amount=request.amount,
            currency=request.currency,
            status=PaymentStatus.SUCCEEDED,
        )
        self.payments[payment.payment_id] = payment
        self.failure_injector.after_operation(operation)
        return payment

    def cancel_order(self, order_id: str) -> None:
        operation = f"cancel_order:{order_id}"
        self.failure_injector.before_operation(operation)
        if order_id in self.orders:
            self.orders[order_id].status = "CANCELLED"
        self.failure_injector.after_operation(operation)

    def successful_payment_count_for_order(self, order_id: str) -> int:
        return sum(
            1
            for payment in self.payments.values()
            if payment.order_id == order_id and payment.status == PaymentStatus.SUCCEEDED
        )

    def order_count_for_idempotency_key(self, idempotency_key: str) -> int:
        return sum(1 for order in self.orders.values() if order.idempotency_key == idempotency_key)

    def successful_payment_count_for_idempotency_key(self, idempotency_key: str) -> int:
        return sum(
            1
            for payment in self.payments.values()
            if payment.idempotency_key == idempotency_key and payment.status == PaymentStatus.SUCCEEDED
        )

    def active_order_count_for_idempotency_key(self, idempotency_key: str) -> int:
        return sum(
            1
            for order in self.orders.values()
            if order.idempotency_key == idempotency_key and order.status == "ACTIVE"
        )

    def cart_for_transaction(self, transaction_id: str) -> Cart | None:
        return next((cart for cart in self.carts.values() if cart.transaction_id == transaction_id), None)

    def order_for_transaction(self, transaction_id: str) -> Order | None:
        return next((order for order in self.orders.values() if order.transaction_id == transaction_id), None)

    def payment_for_transaction(self, transaction_id: str) -> Payment | None:
        return next((payment for payment in self.payments.values() if payment.transaction_id == transaction_id), None)
