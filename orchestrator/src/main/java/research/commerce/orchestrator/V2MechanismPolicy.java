package research.commerce.orchestrator;

record V2MechanismPolicy(
    String name,
    boolean v2,
    boolean deterministicIdentity,
    boolean durableState,
    boolean idempotentSideEffectLookup,
    boolean boundedRetry,
    boolean lostResponseReconciliation,
    boolean compensation,
    boolean restartRecovery
) {
    static V2MechanismPolicy historicalResilient() {
        return new V2MechanismPolicy("HISTORICAL_RESILIENT", false, true, true, true, true, true, true, true);
    }

    static V2MechanismPolicy fromConfiguration(String configuration) {
        return switch (configuration) {
            case "C2" -> new V2MechanismPolicy("C2", true, true, true, false, false, false, false, false);
            case "C3" -> new V2MechanismPolicy("C3", true, true, true, false, true, false, false, false);
            case "C4" -> new V2MechanismPolicy("C4", true, true, true, true, false, false, false, false);
            case "C5" -> new V2MechanismPolicy("C5", true, true, true, true, false, true, false, false);
            case "C6" -> new V2MechanismPolicy("C6", true, true, true, false, false, false, true, false);
            case "C7" -> new V2MechanismPolicy("C7", true, true, true, true, false, false, false, true);
            case "C8" -> new V2MechanismPolicy("C8", true, true, true, true, true, true, true, true);
            default -> throw new IllegalArgumentException("Unsupported v2 configuration for services backend: " + configuration);
        };
    }
}
