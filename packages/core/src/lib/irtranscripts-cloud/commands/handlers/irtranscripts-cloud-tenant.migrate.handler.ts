import { CommandHandler, ICommandHandler } from '@nestjs/cqrs';
import { catchError, tap } from 'rxjs/operators';
import { of as observableOf } from 'rxjs';
import { ITenant } from '@irtranscripts/contracts';
import { IRTranscriptsCloudService } from '../../irtranscripts-cloud.service';
import { RoleService } from './../../../role/role.service';
import { IRTranscriptsCloudTenantMigrateCommand } from './../irtranscripts-cloud-tenant.migrate.command';
import { RolePermissionService } from './../../../role-permission/role-permission.service';

@CommandHandler(IRTranscriptsCloudTenantMigrateCommand)
export class IRTranscriptsCloudTenantMigrateHandler implements ICommandHandler<IRTranscriptsCloudTenantMigrateCommand> {

	constructor(
		private readonly _irtranscriptsCloudService: IRTranscriptsCloudService,
		private readonly _roleService: RoleService,
		private readonly _rolePermissionService: RolePermissionService
	) {}

	public async execute(command: IRTranscriptsCloudTenantMigrateCommand): Promise<any> {
		const { input, token } = command;
		return this._irtranscriptsCloudService.migrateTenant(input, token).pipe(
			tap(async (response: any) => {
				if (response && response.data) {
					const tenant = response.data;

					this.migrateRoles(tenant, token);
					this.migratePermissions(tenant, token);
				}
			}),
			catchError((error) => {
				console.log('Bad Promise:', error);
				return observableOf(error)
			})
		);
	}

	private async migrateRoles(
		tenant: ITenant, 
		token: string
	) {
		return this._irtranscriptsCloudService.migrateRoles(
			await this._roleService.migrateRoles(), 
			token, 
			tenant
		)
		.subscribe();
	}

	private async migratePermissions(
		tenant: ITenant, 
		token: string
	) {
		return this._irtranscriptsCloudService.migrateRolePermissions(
			await this._rolePermissionService.migratePermissions(), 
			token, 
			tenant
		)
		.subscribe();
	}
}
