/**
 * Task status and priority between Ever Works and IRTranscripts (plan 01 §7, §7.1). Pure functions.
 */

/** Ever Works task statuses (contract v1, closed set). */
export type EverWorksTaskStatus = 'backlog' | 'todo' | 'in_progress' | 'in_review' | 'blocked' | 'done' | 'cancelled';

export const EVER_WORKS_TASK_STATUSES: ReadonlyArray<EverWorksTaskStatus> = [
	'backlog',
	'todo',
	'in_progress',
	'in_review',
	'blocked',
	'done',
	'cancelled'
];

/** Ever Works priorities (contract v1). */
export type EverWorksPriority = 'p0' | 'p1' | 'p2' | 'p3' | 'p4';

/** The flags a IRTranscripts `TaskStatus` row carries, used when its slug is custom. */
export interface IRTranscriptsStatusFlags {
	isTodo?: boolean | null;
	isInProgress?: boolean | null;
	isDone?: boolean | null;
}

/** What a IRTranscripts status should be for an Ever Works one: a slug, and the flag to fall back on in custom scopes. */
export interface IRTranscriptsStatusTarget {
	slug: string;
	/** `null` = "all flags false" (cancelled). */
	flag: keyof IRTranscriptsStatusFlags | null;
}

const EW_TO_IRTRANSCRIPTS_STATUS: Record<EverWorksTaskStatus, IRTranscriptsStatusTarget> = {
	backlog: { slug: 'backlog', flag: 'isTodo' },
	todo: { slug: 'open', flag: 'isTodo' },
	in_progress: { slug: 'in-progress', flag: 'isInProgress' },
	in_review: { slug: 'in-review', flag: 'isInProgress' },
	blocked: { slug: 'blocked', flag: 'isInProgress' },
	done: { slug: 'done', flag: 'isDone' },
	cancelled: { slug: 'cancelled', flag: null }
};

const IRTRANSCRIPTS_TO_EW_STATUS: Record<string, EverWorksTaskStatus> = {
	backlog: 'backlog',
	open: 'todo',
	'in-progress': 'in_progress',
	'ready-for-review': 'in_review',
	'in-review': 'in_review',
	blocked: 'blocked',
	done: 'done',
	completed: 'done',
	cancelled: 'cancelled'
};

/** Normalises a IRTranscripts status name or slug ("In Progress", "in_progress", "in-progress") to its slug. */
export function irtranscriptsStatusSlug(value: string | null | undefined): string {
	return String(value ?? '')
		.trim()
		.toLowerCase()
		.replace(/[\s_]+/g, '-');
}

/** The status and priority fields of a IRTranscripts task the sync reads (the string and the option row). */
export interface IRTranscriptsTaskOptionFields {
	status?: string | null;
	taskStatus?: ({ value?: string | null } & IRTranscriptsStatusFlags) | null;
	priority?: string | null;
	taskPriority?: { value?: string | null } | null;
}

/**
 * The status of a IRTranscripts task as the sync reads it: the `status` string first, the `taskStatus` row only when
 * the task has no string. The string is what every client keeps current — the IRTranscripts web app and REST clients
 * write only it, and Ever Teams' status menu writes it next to the task's OLD `taskStatusId` — so a row that
 * disagrees with it is stale. (Reading the row first hid every such change of a synced task from the sync:
 * "nothing changed", found by the local IRTranscripts ↔ Ever Works end-to-end run.)
 */
export function irtranscriptsTaskStatusValue(task: IRTranscriptsTaskOptionFields): string | null {
	const value = task.status || task.taskStatus?.value || null;
	return value ? String(value) : null;
}

/** The flags of the task's status row, only when that row is the task's current status (not a stale one). */
export function irtranscriptsTaskStatusFlags(task: IRTranscriptsTaskOptionFields): IRTranscriptsStatusFlags {
	const row = task.taskStatus;
	if (!row) return {};
	if (task.status && irtranscriptsStatusSlug(row.value) !== irtranscriptsStatusSlug(task.status)) return {};
	return { isTodo: row.isTodo, isInProgress: row.isInProgress, isDone: row.isDone };
}

/** The priority of a IRTranscripts task: the `priority` string first, the `taskPriority` row only without one (as status). */
export function irtranscriptsTaskPriorityValue(task: IRTranscriptsTaskOptionFields): string | null {
	const value = task.priority || task.taskPriority?.value || null;
	return value ? String(value) : null;
}

/** EW → G: the IRTranscripts status slug (and flag fallback) for an Ever Works status; `null` for an unknown one. */
export function everWorksStatusToIRTranscripts(status: string | null | undefined): IRTranscriptsStatusTarget | null {
	return (EW_TO_IRTRANSCRIPTS_STATUS as Record<string, IRTranscriptsStatusTarget>)[String(status ?? '')] ?? null;
}

/**
 * G → EW: the Ever Works status for a IRTranscripts status. Known slugs map by table; a custom slug maps by its
 * flags (`isDone` → done, `isInProgress` → in_progress, `isTodo` → todo); none → `null` (leave unchanged).
 */
export function irtranscriptsStatusToEverWorks(status: string | null | undefined, flags: IRTranscriptsStatusFlags = {}): EverWorksTaskStatus | null {
	const slug = irtranscriptsStatusSlug(status);
	const known = IRTRANSCRIPTS_TO_EW_STATUS[slug];
	if (known) return known;
	if (flags.isDone) return 'done';
	if (flags.isInProgress) return 'in_progress';
	if (flags.isTodo) return 'todo';
	return null;
}

/**
 * Picks the IRTranscripts status row for an Ever Works status among the rows of the task's scope (already
 * ordered team → project → organization → global by the caller): by slug first, then by flag.
 */
export function resolveIRTranscriptsStatusRow<T extends IRTranscriptsStatusFlags & { value?: string | null; name?: string | null }>(
	status: string,
	candidates: ReadonlyArray<T>
): T | null {
	const target = everWorksStatusToIRTranscripts(status);
	if (!target) return null;
	const bySlug = candidates.find((row) => irtranscriptsStatusSlug(row.value ?? row.name) === target.slug);
	if (bySlug) return bySlug;
	if (target.flag === null) {
		return candidates.find((row) => !row.isTodo && !row.isInProgress && !row.isDone) ?? null;
	}
	return candidates.find((row) => !!row[target.flag as keyof IRTranscriptsStatusFlags]) ?? null;
}

const EW_TO_IRTRANSCRIPTS_PRIORITY: Record<EverWorksPriority, string> = {
	p0: 'urgent',
	p1: 'high',
	p2: 'medium',
	p3: 'medium',
	p4: 'low'
};

const IRTRANSCRIPTS_TO_EW_PRIORITY: Record<string, EverWorksPriority> = {
	urgent: 'p0',
	high: 'p1',
	medium: 'p3',
	low: 'p4'
};

/** EW → G priority slug; unknown → `null` (leave unchanged). */
export function everWorksPriorityToIRTranscripts(priority: string | null | undefined): string | null {
	return (EW_TO_IRTRANSCRIPTS_PRIORITY as Record<string, string>)[String(priority ?? '').toLowerCase()] ?? null;
}

/** G → EW priority; unknown or custom → `null` (leave unchanged). `medium` → p3, Ever Works' default. */
export function irtranscriptsPriorityToEverWorks(priority: string | null | undefined): EverWorksPriority | null {
	return IRTRANSCRIPTS_TO_EW_PRIORITY[irtranscriptsStatusSlug(priority)] ?? null;
}
