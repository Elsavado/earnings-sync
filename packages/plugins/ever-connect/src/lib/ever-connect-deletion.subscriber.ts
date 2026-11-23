import { Subject } from 'rxjs';
import { EventSubscriber } from 'typeorm';
import { BaseEntityEventSubscriber, Organization, Tenant } from '@irtranscripts/core';

/**
 * A IRTranscripts tenant or organization was deleted (or soft-deleted). The ORMs make the subscribers below
 * themselves, outside Nest, so they only signal here; the cleanup service of the module handles it.
 */
export const IRTRANSCRIPTS_OWNER_DELETED = new Subject<void>();

/** Organizations deleted through their entity (TypeORM and MikroORM). */
@EventSubscriber()
export class EverConnectOrganizationDeletionSubscriber extends BaseEntityEventSubscriber<Organization> {
	listenTo() {
		return Organization;
	}

	async afterEntityDelete(): Promise<void> {
		IRTRANSCRIPTS_OWNER_DELETED.next();
	}

	async afterEntitySoftRemove(): Promise<void> {
		IRTRANSCRIPTS_OWNER_DELETED.next();
	}
}

/** Tenants deleted through their entity (TypeORM and MikroORM). */
@EventSubscriber()
export class EverConnectTenantDeletionSubscriber extends BaseEntityEventSubscriber<Tenant> {
	listenTo() {
		return Tenant;
	}

	async afterEntityDelete(): Promise<void> {
		IRTRANSCRIPTS_OWNER_DELETED.next();
	}

	async afterEntitySoftRemove(): Promise<void> {
		IRTRANSCRIPTS_OWNER_DELETED.next();
	}
}
