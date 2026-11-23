import {
	EVER_WORKS_TASK_STATUSES,
	everWorksPriorityToIRTranscripts,
	everWorksStatusToIRTranscripts,
	irtranscriptsPriorityToEverWorks,
	irtranscriptsStatusSlug,
	irtranscriptsStatusToEverWorks,
	irtranscriptsTaskPriorityValue,
	irtranscriptsTaskStatusFlags,
	irtranscriptsTaskStatusValue,
	resolveIRTranscriptsStatusRow
} from './status-priority.mapper';

describe('reading a IRTranscripts task status / priority (string first, the row only without one)', () => {
	// A synced task carries the option rows the sync wrote; the web app, REST clients and Ever Teams' status menu
	// then change only the string (Ever Teams sends the OLD taskStatusId along). The string is current.
	const backlogRow = { value: 'backlog', isTodo: true, isInProgress: false, isDone: false };
	const highRow = { value: 'high' };

	it('takes the status string over a stale status row', () => {
		expect(irtranscriptsTaskStatusValue({ status: 'in-progress', taskStatus: backlogRow })).toBe('in-progress');
		expect(irtranscriptsStatusToEverWorks(irtranscriptsTaskStatusValue({ status: 'in-progress', taskStatus: backlogRow }))).toBe(
			'in_progress'
		);
	});

	it('falls back to the row when the task has no status string', () => {
		expect(irtranscriptsTaskStatusValue({ status: null, taskStatus: backlogRow })).toBe('backlog');
		expect(irtranscriptsTaskStatusValue({})).toBeNull();
	});

	it('uses the row flags only when the row is the current status', () => {
		const custom = { value: 'qa-check', isTodo: false, isInProgress: true, isDone: false };
		expect(irtranscriptsTaskStatusFlags({ status: 'qa-check', taskStatus: custom })).toEqual({
			isTodo: false,
			isInProgress: true,
			isDone: false
		});
		expect(irtranscriptsTaskStatusFlags({ taskStatus: custom })).toEqual({
			isTodo: false,
			isInProgress: true,
			isDone: false
		});
		expect(irtranscriptsTaskStatusFlags({ status: 'another-custom', taskStatus: custom })).toEqual({});
		expect(irtranscriptsTaskStatusFlags({ status: 'qa-check' })).toEqual({});
	});

	it('takes the priority string over a stale priority row', () => {
		expect(irtranscriptsTaskPriorityValue({ priority: 'low', taskPriority: highRow })).toBe('low');
		expect(irtranscriptsPriorityToEverWorks(irtranscriptsTaskPriorityValue({ priority: 'low', taskPriority: highRow }))).toBe('p4');
		expect(irtranscriptsTaskPriorityValue({ priority: null, taskPriority: highRow })).toBe('high');
		expect(irtranscriptsTaskPriorityValue({})).toBeNull();
	});
});

describe('status mapping (plan 01 §7.1)', () => {
	it.each([
		['backlog', 'backlog', 'isTodo'],
		['todo', 'open', 'isTodo'],
		['in_progress', 'in-progress', 'isInProgress'],
		['in_review', 'in-review', 'isInProgress'],
		['blocked', 'blocked', 'isInProgress'],
		['done', 'done', 'isDone'],
		['cancelled', 'cancelled', null]
	])('EW %s → G %s (fallback %s)', (ew, slug, flag) => {
		expect(everWorksStatusToIRTranscripts(ew)).toEqual({ slug, flag });
	});

	it('EW → G: an unknown status maps to nothing', () => {
		expect(everWorksStatusToIRTranscripts('archived')).toBeNull();
		expect(everWorksStatusToIRTranscripts(undefined)).toBeNull();
	});

	it.each([
		['backlog', 'backlog'],
		['open', 'todo'],
		['Open', 'todo'],
		['in-progress', 'in_progress'],
		['In Progress', 'in_progress'],
		['in_progress', 'in_progress'],
		['ready-for-review', 'in_review'],
		['in-review', 'in_review'],
		['blocked', 'blocked'],
		['done', 'done'],
		['completed', 'done'],
		['cancelled', 'cancelled']
	])('G %s → EW %s', (g, ew) => {
		expect(irtranscriptsStatusToEverWorks(g)).toBe(ew);
	});

	it('G → EW: a custom status maps by its flags, done first; no flag → unchanged', () => {
		expect(irtranscriptsStatusToEverWorks('shipped', { isDone: true, isInProgress: true })).toBe('done');
		expect(irtranscriptsStatusToEverWorks('qa', { isInProgress: true })).toBe('in_progress');
		expect(irtranscriptsStatusToEverWorks('triage', { isTodo: true })).toBe('todo');
		expect(irtranscriptsStatusToEverWorks('parked', {})).toBeNull();
	});

	it('round-trips every Ever Works status through its IRTranscripts slug', () => {
		for (const status of EVER_WORKS_TASK_STATUSES) {
			expect(irtranscriptsStatusToEverWorks(everWorksStatusToIRTranscripts(status)!.slug)).toBe(status);
		}
	});

	it('resolves the IRTranscripts row by slug, then by flag; cancelled → a row with no flag', () => {
		const rows = [
			{ value: 'Ready', isTodo: true },
			{ value: 'Doing', isInProgress: true },
			{ value: 'Shipped', isDone: true },
			{ value: 'Dropped' },
			{ value: 'in-review', isInProgress: true }
		];
		expect(resolveIRTranscriptsStatusRow('in_review', rows)?.value).toBe('in-review');
		expect(resolveIRTranscriptsStatusRow('in_progress', rows)?.value).toBe('Doing');
		expect(resolveIRTranscriptsStatusRow('todo', rows)?.value).toBe('Ready');
		expect(resolveIRTranscriptsStatusRow('done', rows)?.value).toBe('Shipped');
		expect(resolveIRTranscriptsStatusRow('cancelled', rows)?.value).toBe('Dropped');
		expect(resolveIRTranscriptsStatusRow('nonsense', rows)).toBeNull();
		expect(irtranscriptsStatusSlug(' In_Review ')).toBe('in-review');
	});
});

describe('priority mapping (plan 01 §7)', () => {
	it.each([
		['p0', 'urgent'],
		['p1', 'high'],
		['p2', 'medium'],
		['p3', 'medium'],
		['p4', 'low'],
		['P1', 'high'],
		['p9', null]
	])('EW %s → G %s', (ew, g) => expect(everWorksPriorityToIRTranscripts(ew)).toBe(g));

	it.each([
		['urgent', 'p0'],
		['high', 'p1'],
		['medium', 'p3'],
		['Medium', 'p3'],
		['low', 'p4'],
		['custom', null],
		[null, null]
	])('G %s → EW %s', (g, ew) => expect(irtranscriptsPriorityToEverWorks(g)).toBe(ew));
});
