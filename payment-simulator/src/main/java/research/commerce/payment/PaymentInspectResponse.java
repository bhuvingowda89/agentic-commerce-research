package research.commerce.payment;

import java.util.List;

record PaymentInspectResponse(int successfulPaymentCount, List<String> paymentIds) {
}

