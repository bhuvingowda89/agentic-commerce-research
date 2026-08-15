package research.commerce.order;

import java.util.List;

record OrderInspectResponse(int orderCount, int activeOrderCount, List<String> orderIds) {
}

