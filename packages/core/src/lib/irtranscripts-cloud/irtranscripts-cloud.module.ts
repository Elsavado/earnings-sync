import { Module } from '@nestjs/common';
import { CqrsModule } from '@nestjs/cqrs';
import { HttpModule } from '@nestjs/axios';
import { ConfigModule, ConfigService } from '@irtranscripts/config';
import { RoleModule } from './../role/role.module';
import { RolePermissionModule } from './../role-permission/role-permission.module';
import { IRTranscriptsCloudController } from './irtranscripts-cloud.controller';
import { IRTranscriptsCloudService } from './irtranscripts-cloud.service';
import { CommandHandlers } from './commands/handlers';

@Module({
	imports: [
		HttpModule.registerAsync({
			imports: [ConfigModule],
			useFactory: async (configService: ConfigService) => ({
				baseURL: configService.get('irtranscriptsCloudEndpoint') as string,
				timeout: 60 * 5 * 1000,
				maxRedirects: 5,
				headers: {
					'Content-Type': 'application/json'
				}
			}),
			inject: [ConfigService]
		}),
		CqrsModule,
		RoleModule,
		RolePermissionModule
	],
	controllers: [IRTranscriptsCloudController],
	providers: [IRTranscriptsCloudService, ...CommandHandlers]
})
export class IRTranscriptsCloudModule {}
