import { schedules, logger, retry } from "@trigger.dev/sdk";

export const orchestratorTick = schedules.task({
  id: "orchestrator-tick",
  cron: "0 * * * *", // every 60 minutes
  run: async () => {
    const apiUrl = process.env.ORCHESTRATOR_API_URL || "https://api.outboundengine.dev";
    const secret = process.env.INTERNAL_SCHEDULER_SECRET;

    if (!secret) {
      logger.error("INTERNAL_SCHEDULER_SECRET is not set");
      return { status: "error", message: "missing scheduler secret" };
    }

    const response = await retry.fetch(`${apiUrl}/api/internal/orchestrator/tick`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Internal-Scheduler-Secret": secret,
      },
      body: JSON.stringify({ dry_run: false }),
      retry: {
        byStatus: {
          "500-599": {
            strategy: "backoff",
            maxAttempts: 3,
            factor: 2,
            minTimeoutInMs: 1000,
            maxTimeoutInMs: 10000,
          },
        },
      },
    });

    const result = await response.json();
    logger.info("Orchestrator tick completed", { result });

    return result;
  },
});
