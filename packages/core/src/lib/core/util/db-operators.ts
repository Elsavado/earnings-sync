// db-operators.ts

import { isPostgres } from '@irtranscripts/config';

// Define the like operator based on the database type
export const LIKE_OPERATOR = isPostgres() ? 'ILIKE' : 'LIKE';
