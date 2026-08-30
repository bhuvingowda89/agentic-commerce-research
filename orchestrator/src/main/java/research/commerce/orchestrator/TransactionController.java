package research.commerce.orchestrator;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

@RestController
class TransactionController {
    private final TransactionService transactionService;
    private final TransactionRepository transactionRepository;
    private final MechanismEventRepository mechanismEventRepository;

    TransactionController(
        TransactionService transactionService,
        TransactionRepository transactionRepository,
        MechanismEventRepository mechanismEventRepository
    ) {
        this.transactionService = transactionService;
        this.transactionRepository = transactionRepository;
        this.mechanismEventRepository = mechanismEventRepository;
    }

    @PostMapping("/transactions")
    TransactionResponse execute(
        @RequestBody TransactionRequest request,
        @RequestHeader("Idempotency-Key") String idempotencyKey,
        @RequestHeader(name = "X-Execution-Mode", defaultValue = "RESILIENT") String mode,
        @RequestHeader(name = "X-Failure-Scenario", defaultValue = "f0-no-failure") String scenario,
        @RequestHeader(name = "X-Failure-Rate", defaultValue = "0.0") double failureRate,
        @RequestHeader(name = "X-Random-Seed", defaultValue = "7") String randomSeed,
        @RequestHeader(name = "X-V2-Configuration", required = false) String v2Configuration,
        @RequestHeader(name = "X-V2-Crash-Point", required = false) String v2CrashPoint,
        @RequestHeader(name = "X-V2-Crash-Token", required = false) String v2CrashToken
    ) {
        return transactionService.execute(request, idempotencyKey, mode, scenario, failureRate, randomSeed, v2Configuration, v2CrashPoint, v2CrashToken).toResponse();
    }

    @PostMapping("/recovery/run")
    java.util.List<TransactionResponse> recover(
        @RequestHeader(name = "X-Failure-Scenario", defaultValue = "f0-no-failure") String scenario,
        @RequestHeader(name = "X-Failure-Rate", defaultValue = "0.0") double failureRate,
        @RequestHeader(name = "X-Random-Seed", defaultValue = "7") String randomSeed
    ) {
        return transactionService.recover(scenario, failureRate, randomSeed)
            .stream()
            .map(TransactionRecord::toResponse)
            .toList();
    }

    @GetMapping("/transactions/idempotency/{idempotencyKey}")
    TransactionResponse find(@PathVariable("idempotencyKey") String idempotencyKey) {
        return transactionRepository.findByIdempotencyKey(idempotencyKey).orElseThrow().toResponse();
    }

    @PostMapping("/recovery/idempotency/{idempotencyKey}")
    TransactionResponse recoverOne(
        @PathVariable("idempotencyKey") String idempotencyKey,
        @RequestHeader(name = "X-Failure-Scenario", defaultValue = "f0-no-failure") String scenario,
        @RequestHeader(name = "X-Failure-Rate", defaultValue = "0.0") double failureRate,
        @RequestHeader(name = "X-Random-Seed", defaultValue = "7") String randomSeed,
        @RequestHeader(name = "X-V2-Configuration", required = false) String v2Configuration
    ) {
        return transactionService.recoverOne(idempotencyKey, scenario, failureRate, randomSeed, v2Configuration).toResponse();
    }

    @GetMapping("/v2/mechanism-events/idempotency/{idempotencyKey}")
    java.util.List<MechanismEventResponse> mechanismEvents(@PathVariable("idempotencyKey") String idempotencyKey) {
        return mechanismEventRepository.findByIdempotencyKey(idempotencyKey)
            .stream()
            .map(MechanismEventResponse::from)
            .toList();
    }
}
