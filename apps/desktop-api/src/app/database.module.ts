import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { MikroOrmModule } from '@mikro-orm/nestjs';
import { EntityCaseNamingStrategy } from '@mikro-orm/core';
import { BetterSqliteDriver, Options as MikroOrmSqliteOptions } from '@mikro-orm/better-sqlite';
import { Wakatime } from '@irtranscripts/plugin-integration-wakatime';

const coreEntities = [Wakatime];
const dbPath = process.env.IRTRANSCRIPTS_USER_PATH ? `${process.env.IRTRANSCRIPTS_USER_PATH}/irtranscripts.sqlite3` : '';

@Module({
	imports: [
		// TypeORM DB Config (SQLite3)
		TypeOrmModule.forRootAsync({
			useFactory: () => ({
				type: 'better-sqlite3',
				database: dbPath,
				keepConnectionAlive: true,
				logging: 'all',
				logger: 'file', //Removes console logging, instead logs all queries in a file ormlogs.log
				synchronize: true,
				entities: coreEntities
			}),
			inject: []
		}),
		// MikroORM DB Config (SQLite3)
		MikroOrmModule.forRootAsync({
			useFactory: (): MikroOrmSqliteOptions => ({
				driver: BetterSqliteDriver,
				dbName: dbPath,
				entities: coreEntities,
				namingStrategy: EntityCaseNamingStrategy,
				debug: ['query'] // by default set to false only
			}),
			driver: BetterSqliteDriver,
			inject: []
		})
	]
})
export class DatabaseModule {}
