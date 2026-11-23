import { UploadedFile } from '@irtranscripts/contracts';

/**
 * Interface for file processing strategy
 */
export interface FileProcessingStrategy {
	process(file: any, provider: any): Promise<UploadedFile | UploadedFile[]>;
}
