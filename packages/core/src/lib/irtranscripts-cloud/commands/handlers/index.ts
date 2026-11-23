import { IRTranscriptsCloudOrganizationMigrateHandler } from './irtranscripts-cloud-organization.migrate.handler';
import { IRTranscriptsCloudTenantMigrateHandler } from './irtranscripts-cloud-tenant.migrate.handler';
import { IRTranscriptsCloudUserMigrateHandler } from './irtranscripts-cloud-user.migrate.handler';

export const CommandHandlers = [
    IRTranscriptsCloudUserMigrateHandler,
    IRTranscriptsCloudTenantMigrateHandler,
    IRTranscriptsCloudOrganizationMigrateHandler
];
