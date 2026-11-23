import { BadRequestException, ConflictException, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { CommandBus } from '@nestjs/cqrs';
import { Brackets, DataSource, IsNull } from 'typeorm';
import { ID } from '@irtranscripts/contracts';
import { OrganizationProject, OrganizationTeam, RequestContext, TaskUpdateCommand } from '@irtranscripts/core';
import { EverWorksMappingContext, EverWorksMappingContextService } from '../../mapping/ever-works-mapping-context.service';
import { EverWorksLinkType, EverWorksSyncLog } from '../entities/ever-works-sync.entities';
import { EverWorksSyncLogService, logCursorOf, parseLogCursor, serializeDetails } from '../ever-works-sync-log.service';
import type { FieldMergeResult } from '../merge/three-way-merge';
import { EverWorksOutboundQueue } from '../outbound/ever-works-outbound.queue';

/** The `action` of a conflict row in `ever_works_sync_log`. */
export const CONFLICT_ACTION = 'merge_conflict';

/**
 * What a conflict row's `details` hold (plan 03 §C.5: both values, so the UI can offer "use the other
 * value"). Values are in IRTranscripts's representation (an Ever Works status already mapped to IRTranscripts's, for
 * example), so either one can be written back into the IRTranscripts record as it is.
 */
export interface EverWorksConflictDetails {
	/** The shared field (the snapshot's name). */
	field: string;
	/** The IRTranscripts property "use the other value" writes (defaults to `field`). */
	irtranscriptsField?: string;
	irtranscriptsValue: unknown;
	everWorksValue: unknown;
	/** The side last-writer-wins chose. */
	winner: 'irtranscripts' | 'ever_works';
	irtranscriptsAt?: string | null;
	everWorksAt?: string | null;
	/** Set when an admin resolves it. */
	resolution?: 'keep' | 'use_other';
}

/** One conflict to record (a handler calls {@link EverWorksConflictsService.record} after its 3-way merge). */
export interface EverWorksConflictInput extends Omit<EverWorksConflictDetails, 'resolution'> {
	tenantId: ID;
	organizationId: ID;
	integrationTenantId: ID;
	connectionId?: ID | null;
	direction: 'inbound' | 'outbound';
	entityType: EverWorksLinkType | string;
	irtranscriptsId: ID;
	ewId: string;
	message?: string | null;
}

/** A conflict as the Activity tab shows it. */
export interface EverWorksConflictView {
	id: ID;
	createdAt: Date | null;
	direction: string;
	entityType: string | null;
	irtranscriptsId: ID | null;
	ewId: string | null;
	message: string | null;
	details: EverWorksConflictDetails | null;
	resolved: boolean;
	resolvedAt: Date | null;
	resolvedByUserId: ID | null;
	/** Whether "use the other value" can be applied to this record type and field. */
	canUseOther: boolean;
}

/** Writes the losing value of a conflict back into the IRTranscripts record ("use the other value"). */
export interface EverWorksConflictResolver {
	readonly entityTypes: ReadonlyArray<string>;
	/** The IRTranscripts properties it may write (anything else is refused). */
	readonly fields: ReadonlyArray<string>;
	useValue(context: EverWorksMappingContext, irtranscriptsId: ID, field: string, value: unknown): Promise<void>;
}

/**
 * The conflict half of the 3-way merge from a field result (`mergeField`): who won, and both values.
 * `irtranscriptsField` names the IRTranscripts property when it differs from the shared field name.
 */
export function conflictFromMerge(
	field: string,
	result: FieldMergeResult,
	options: { irtranscriptsField?: string; irtranscriptsAt?: Date | string | null; everWorksAt?: Date | string | null } = {}
): Omit<EverWorksConflictDetails, 'resolution'> | null {
	if (!result.conflict || !result.loserSide) return null;
	const winner = result.loserSide === 'irtranscripts' ? 'ever_works' : 'irtranscripts';
	const iso = (value: Date | string | null | undefined) => (value ? new Date(value).toISOString() : null);
	return {
		field,
		...(options.irtranscriptsField && options.irtranscriptsField !== field ? { irtranscriptsField: options.irtranscriptsField } : {}),
		irtranscriptsValue: winner === 'irtranscripts' ? result.value : result.loser,
		everWorksValue: winner === 'ever_works' ? result.value : result.loser,
		winner,
		irtranscriptsAt: iso(options.irtranscriptsAt),
		everWorksAt: iso(options.everWorksAt)
	};
}

/** The other side's value of a conflict: the one last-writer-wins dropped. */
export function otherValue(details: EverWorksConflictDetails): unknown {
	return details.winner === 'irtranscripts' ? details.everWorksValue : details.irtranscriptsValue;
}

/** The most conflicts one page returns. */
export const CONFLICTS_PAGE_MAX = 200;

/**
 * How long a resolution in progress holds its conflict. A resolution that never finished (the process
 * stopped in between) frees the conflict after this, so it can be resolved again.
 */
export const CONFLICT_CLAIM_MS = 2 * 60_000;

/**
 * Conflicts (plan 03 §C.5, plan 06 G-P1-10): last-writer-wins conflicts are `ever_works_sync_log` rows
 * with `status = 'conflict'`, kept until an admin resolves them (the log's 30-day pruning skips them).
 * The Activity tab lists them; resolving one either keeps the merged value or writes the other side's
 * value into the IRTranscripts record through the platform (a task through `TaskUpdateCommand`), as the signed-in
 * admin and outside the sync's own context, so the change is captured and pushed to Ever Works like any
 * IRTranscripts edit.
 */
@Injectable()
export class EverWorksConflictsService {
	private readonly logger = new Logger('EverWorksConflicts');
	private readonly resolvers = new Map<string, EverWorksConflictResolver>();

	constructor(
		private readonly dataSource: DataSource,
		private readonly contexts: EverWorksMappingContextService,
		private readonly log: EverWorksSyncLogService,
		private readonly queue: EverWorksOutboundQueue,
		private readonly commandBus: CommandBus
	) {
		for (const resolver of defaultResolvers(this.dataSource, this.queue, this.commandBus)) this.register(resolver);
	}

	/** Registers the "use the other value" writer of a record type (the later registration wins). */
	register(resolver: EverWorksConflictResolver): void {
		for (const type of resolver.entityTypes) this.resolvers.set(type, resolver);
	}

	/** Records one conflict (both values, the winner). Handlers call this after their 3-way merge. */
	async record(input: EverWorksConflictInput): Promise<void> {
		const details: EverWorksConflictDetails = {
			field: input.field,
			...(input.irtranscriptsField ? { irtranscriptsField: input.irtranscriptsField } : {}),
			irtranscriptsValue: input.irtranscriptsValue,
			everWorksValue: input.everWorksValue,
			winner: input.winner,
			irtranscriptsAt: input.irtranscriptsAt ?? null,
			everWorksAt: input.everWorksAt ?? null
		};
		await this.log.write({
			tenantId: input.tenantId,
			organizationId: input.organizationId,
			integrationTenantId: input.integrationTenantId,
			connectionId: input.connectionId ?? null,
			direction: input.direction,
			entityType: input.entityType,
			irtranscriptsId: input.irtranscriptsId,
			ewId: input.ewId,
			action: CONFLICT_ACTION,
			status: 'conflict',
			message: input.message ?? `${input.field}: both sides changed; ${input.winner === 'irtranscripts' ? 'IRTranscripts' : 'Ever Works'} was written last and won.`,
			details: details as unknown as Record<string, unknown>
		});
	}

	/**
	 * `GET /mappings/:id/conflicts`: newest first; `state` open (default), resolved or all; paged by
	 * `cursor` (the last row's time and id, so conflicts resolved meanwhile never hide later ones).
	 */
	async list(
		integrationTenantId: ID,
		query: { state?: string; limit?: string | number; cursor?: string },
		organizationId?: ID
	): Promise<{ items: EverWorksConflictView[]; nextCursor: string | null }> {
		const context = await this.contexts.forRequest(integrationTenantId, organizationId);
		const state = query.state === 'resolved' || query.state === 'all' ? query.state : 'open';
		const limit = clampLimit(query.limit, 50, CONFLICTS_PAGE_MAX);
		const cursor = parseLogCursor(query.cursor);
		const builder = this.dataSource
			.getRepository(EverWorksSyncLog)
			.createQueryBuilder('log')
			.where('log.tenantId = :tenantId', { tenantId: context.tenantId })
			.andWhere('log.integrationTenantId = :integrationTenantId', { integrationTenantId: context.integrationTenantId })
			.andWhere('log.status = :status', { status: 'conflict' });
		if (state === 'open') builder.andWhere('log.resolvedAt IS NULL');
		if (state === 'resolved') builder.andWhere('log.resolvedAt IS NOT NULL');
		if (cursor) {
			builder.andWhere(
				new Brackets((where) => {
					where.where('log.createdAt < :at', { at: cursor.at }).orWhere(new Brackets((same) => same.where('log.createdAt = :at', { at: cursor.at }).andWhere('log.id < :id', { id: cursor.id })));
				})
			);
		}
		const rows = await builder.orderBy('log.createdAt', 'DESC').addOrderBy('log.id', 'DESC').take(limit + 1).getMany();
		const page = rows.slice(0, limit);
		return {
			items: page.map((row) => this.view(row)),
			nextCursor: rows.length > limit ? logCursorOf(page[page.length - 1] as EverWorksSyncLog & { createdAt?: Date }) : null
		};
	}

	/**
	 * `POST /mappings/:id/conflicts/:conflictId/resolve`: `keep` accepts the merged value; `use_other`
	 * writes the other side's value into the IRTranscripts record (and from there to Ever Works). Once only:
	 *
	 * 1. the conflict is **claimed** (`resolvedByUserId` and the claim time, with a condition), so of two
	 *    requests at once only one goes on; the conflict is still open while claimed;
	 * 2. the value is written (for `use_other`);
	 * 3. the conflict is marked resolved, by the claimer only.
	 *
	 * A write that fails gives the claim back at once; a resolution cut short (the process stopped) frees
	 * it after {@link CONFLICT_CLAIM_MS}, so the admin can resolve the conflict again.
	 */
	async resolve(integrationTenantId: ID, conflictId: ID, resolution: 'keep' | 'use_other', organizationId?: ID): Promise<EverWorksConflictView> {
		const context = await this.contexts.forRequest(integrationTenantId, organizationId);
		const repository = this.dataSource.getRepository(EverWorksSyncLog);
		const row = await repository.findOne({
			where: { id: conflictId, tenantId: context.tenantId, integrationTenantId: context.integrationTenantId, status: 'conflict' } as never
		});
		if (!row) throw new NotFoundException('Conflict not found.');
		if (row.resolvedAt) throw new ConflictException('This conflict is already resolved.');
		const details = parseDetails(row.details);
		let apply: (() => Promise<void>) | null = null;
		if (resolution === 'use_other') {
			if (!details || !row.irtranscriptsId || !row.entityType) throw new BadRequestException('This conflict does not carry the values to apply.');
			const field = details.irtranscriptsField ?? details.field;
			const resolver = this.resolvers.get(row.entityType);
			if (!resolver || !resolver.fields.includes(field)) {
				throw new BadRequestException(`"Use the other value" is not available for ${row.entityType} ${field}; edit the record instead.`);
			}
			apply = () => resolver.useValue(context, row.irtranscriptsId as ID, field, otherValue(details));
		}
		const claimer = (RequestContext.currentUserId() as ID | null) ?? ('system' as ID);
		const now = new Date();
		const claim = this.dataSource.createQueryBuilder().update(EverWorksSyncLog);
		const c = (name: string) => claim.escape(name);
		const claimed = await claim
			.set({ resolvedByUserId: claimer, updatedAt: now } as never)
			.where(`${c('id')} = :id`, { id: row.id })
			.andWhere(`${c('resolvedAt')} IS NULL`)
			.andWhere(
				new Brackets((free) => {
					free.where(`${c('resolvedByUserId')} IS NULL`).orWhere(`${c('updatedAt')} < :stale`, { stale: new Date(now.getTime() - CONFLICT_CLAIM_MS) });
				})
			)
			.execute();
		if (!claimed.affected) throw new ConflictException('This conflict is already resolved, or being resolved right now.');
		const mine = { id: row.id, resolvedAt: IsNull(), resolvedByUserId: claimer };
		if (apply) {
			try {
				await apply();
			} catch (error) {
				// Nothing was applied: the claim is given back and the conflict stays open, as it was.
				await repository.update(mine as never, { resolvedByUserId: null } as never).catch(() => undefined);
				throw error;
			}
		}
		const done = await repository.update(mine as never, {
			resolvedAt: new Date(),
			details: serializeDetails({ ...(details ?? {}), resolution })
		} as never);
		if (!done.affected) throw new ConflictException('This conflict was resolved meanwhile.');
		this.logger.log(`Conflict ${row.id} (${row.entityType} ${row.irtranscriptsId}) resolved: ${resolution}.`);
		const saved = await repository.findOneOrFail({ where: { id: row.id } as never });
		return this.view(saved);
	}

	/** Open conflicts of a mapping. */
	countOpen(tenantId: ID, integrationTenantId: ID): Promise<number> {
		return this.dataSource.getRepository(EverWorksSyncLog).count({
			where: { tenantId, integrationTenantId, status: 'conflict', resolvedAt: IsNull() } as never
		});
	}

	private view(row: EverWorksSyncLog): EverWorksConflictView {
		const details = parseDetails(row.details);
		const field = details ? (details.irtranscriptsField ?? details.field) : null;
		const resolver = row.entityType ? this.resolvers.get(row.entityType) : undefined;
		return {
			id: row.id as ID,
			createdAt: ((row as { createdAt?: Date }).createdAt as Date) ?? null,
			direction: row.direction,
			entityType: row.entityType ?? null,
			irtranscriptsId: (row.irtranscriptsId as ID) ?? null,
			ewId: row.ewId ?? null,
			message: row.message ?? null,
			details,
			resolved: !!row.resolvedAt,
			resolvedAt: row.resolvedAt ?? null,
			// A claim of a resolution in progress is not a resolution.
			resolvedByUserId: row.resolvedAt ? ((row.resolvedByUserId as ID) ?? null) : null,
			canUseOther: !row.resolvedAt && !!resolver && !!field && resolver.fields.includes(field) && !!row.irtranscriptsId
		};
	}
}

/** The writers this version ships: tasks (through the platform's command), teams and projects. */
function defaultResolvers(dataSource: DataSource, queue: EverWorksOutboundQueue, commandBus: CommandBus): EverWorksConflictResolver[] {
	return [
		{
			entityTypes: [EverWorksLinkType.TASK, EverWorksLinkType.IDEA_TASK],
			fields: ['title', 'description', 'priority', 'size', 'status', 'dueDate', 'startDate', 'estimate'],
			// Through the platform's own command, as the signed-in admin: validations run, TaskEvent is
			// published (other integrations mirror it) and the Ever Works listener captures the change.
			useValue: async (context, irtranscriptsId, field, value) => {
				await commandBus.execute(new TaskUpdateCommand(irtranscriptsId, { [field]: value, organizationId: context.organizationId, tenantId: context.tenantId } as never, true));
			}
		},
		{
			entityTypes: [EverWorksLinkType.TEAM],
			fields: ['name', 'emoji'],
			useValue: async (context, irtranscriptsId, field, value) => {
				const repository = dataSource.getRepository(OrganizationTeam);
				const team = await repository.findOne({ where: { id: irtranscriptsId, tenantId: context.tenantId, organizationId: context.organizationId } as never });
				if (!team) throw new NotFoundException('The IRTranscripts team is gone.');
				(team as unknown as Record<string, unknown>)[field] = value;
				await repository.save(team);
				await queue.enqueue({ tenantId: context.tenantId, organizationId: context.organizationId, entityType: EverWorksLinkType.TEAM, irtranscriptsId, op: 'upsert', changedFields: [field] });
			}
		},
		{
			entityTypes: [EverWorksLinkType.PROJECT_WORK],
			fields: ['name', 'description', 'projectUrl', 'openSourceProjectUrl'],
			useValue: async (context, irtranscriptsId, field, value) => {
				const repository = dataSource.getRepository(OrganizationProject);
				const project = await repository.findOne({ where: { id: irtranscriptsId, tenantId: context.tenantId, organizationId: context.organizationId } as never });
				if (!project) throw new NotFoundException('The IRTranscripts project is gone.');
				(project as unknown as Record<string, unknown>)[field] = value;
				await repository.save(project);
			}
		}
	];
}

/** A conflict row's details, or `null` when they are missing or not a conflict's. */
export function parseDetails(raw: string | null | undefined): EverWorksConflictDetails | null {
	if (!raw) return null;
	try {
		const value = JSON.parse(raw) as EverWorksConflictDetails;
		return value && typeof value === 'object' && typeof value.field === 'string' && (value.winner === 'irtranscripts' || value.winner === 'ever_works') ? value : null;
	} catch {
		return null;
	}
}

/** A page size from a query value: an integer in `1..max`, else `fallback`. */
export function clampLimit(raw: string | number | undefined, fallback: number, max: number): number {
	const value = typeof raw === 'number' ? raw : Number.parseInt(String(raw ?? ''), 10);
	if (!Number.isFinite(value) || value < 1) return fallback;
	return Math.min(Math.floor(value), max);
}

