import { Injectable } from '@nestjs/common';
import * as chalk from 'chalk';
import { environment } from '@irtranscripts/config';
import { ConnectionEntityManager, SeedDataService } from '@irtranscripts/core';
import { createDefaultJobSearchCategories } from './job-search-category/job-search-category.seed';
import { createDefaultJobSearchOccupations } from './job-search-occupation/job-search-occupation.seed';

/**
 * Service dealing with help center based operations.
 *
 * @class
 */
@Injectable()
export class JobSeederService {
    /**
     * Create an instance of class.
     *
     * @constructs
     *
     */
    constructor(
        private readonly connectionEntityManager: ConnectionEntityManager,
        private readonly seeder: SeedDataService
    ) { }

    /**
     * Seeds job data into the database.
     *
     * This function seeds default job search categories and occupations using the provided connection,
     * tenant, and default organization. It logs the seeding process and any errors encountered.
     */
    public async seedDefaultJobsData(): Promise<void> {
        try {
            // Log the start of the seeding process
            this.seeder.log(chalk.green(`🌱 SEEDING ${environment.production ? 'PRODUCTION' : ''} JOBS DATABASE...`));

            // Seed default job search categories
            await this.seeder.tryExecute(
                'Default Job Search Categories',
                createDefaultJobSearchCategories(
                    this.connectionEntityManager.rawConnection,
                    this.seeder.tenant,
                    this.seeder.defaultOrganization
                )
            );

            // Seed default job search occupations
            await this.seeder.tryExecute(
                'Default Job Search Occupations',
                createDefaultJobSearchOccupations(
                    this.connectionEntityManager.rawConnection,
                    this.seeder.tenant,
                    this.seeder.defaultOrganization
                )
            );

            // Log the completion of the seeding process
            this.seeder.log(chalk.green(`✅ SEEDED ${environment.production ? 'PRODUCTION' : ''} JOBS DATABASE`));
        } catch (error) {
            // Log any errors encountered during the seeding process
            console.log('Error while job data seeding: %s', error.message);
        }
    }
}
