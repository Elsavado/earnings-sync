export const SCHEDULED_JOB_METADATA = 'irtranscripts:scheduler:job';
export const SCHEDULER_MODULE_OPTIONS = Symbol('IRTRANSCRIPTS_SCHEDULER_MODULE_OPTIONS');
export const QUEUE_JOB_HANDLER_METADATA = 'irtranscripts:scheduler:queue-job-handler';
/**
 * Set by `@QueueWorker()` on every host it decorates: `true` when it deferred the worker's start (registered it
 * with `autorun: false` on the caller's behalf) and `QueueWorkerHost` should start it once the application has
 * bootstrapped; `false` when the caller chose `autorun` itself or the host is scoped.
 */
export const QUEUE_WORKER_DEFERRED_START_METADATA = 'irtranscripts:scheduler:queue-worker-deferred-start';
