/**
 * The Sim routes check the caller's own role.
 *
 * `TenantPermissionGuard` asks only whether some role of the tenant holds a permission, so with it alone the
 * `@Permissions(INTEGRATION_*)` the routes state were met by the tenant's ADMIN role for every caller: an EMPLOYEE
 * could replace the tenant's Sim API key, map timer and sign-up events to a workflow of their own and read the
 * executions. `PermissionGuard` is what checks the caller's role, as on the other integration controllers.
 */
jest.mock('@irtranscripts/core', () => {
	class TenantPermissionGuard {}
	class PermissionGuard {}
	const { SetMetadata } = jest.requireActual('@nestjs/common');
	const { PERMISSIONS_METADATA } = jest.requireActual('@irtranscripts/constants');

	return {
		TenantPermissionGuard,
		PermissionGuard,
		Permissions: (...permissions: string[]) => SetMetadata(PERMISSIONS_METADATA, permissions),
		UUIDValidationPipe: class {}
	};
});
jest.mock('./sim.service', () => ({ SimService: class {} }));

import { GUARDS_METADATA, METHOD_METADATA } from '@nestjs/common/constants';
import { PERMISSIONS_METADATA } from '@irtranscripts/constants';
import { PermissionGuard, TenantPermissionGuard } from '@irtranscripts/core';
import { SimController } from './sim.controller';

describe('SimController — the caller’s own permissions', () => {
	it('runs PermissionGuard after TenantPermissionGuard on every route', () => {
		expect(Reflect.getMetadata(GUARDS_METADATA, SimController)).toEqual([TenantPermissionGuard, PermissionGuard]);
	});

	it('states a permission on every route', () => {
		const routes = Object.getOwnPropertyNames(SimController.prototype).filter(
			(name) => Reflect.getMetadata(METHOD_METADATA, (SimController.prototype as any)[name]) !== undefined
		);

		expect(routes.length).toBeGreaterThan(0);
		for (const route of routes) {
			expect([route, Reflect.getMetadata(PERMISSIONS_METADATA, (SimController.prototype as any)[route])]).toEqual(
				[route, expect.arrayContaining([expect.stringMatching(/^INTEGRATION_/)])]
			);
		}
	});
});
