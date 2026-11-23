import { IEmployeeProposalTemplateCreateInput } from '@irtranscripts/contracts';
import { IntersectionType } from '@nestjs/mapped-types';
import { EmployeeFeatureDTO } from '@irtranscripts/core';
import { ProposalTemplateDTO } from './proposal-template.dto';

/**
 * Create proposal template request DTO validation
 *
 */
export class CreateProposalTemplateDTO
	extends IntersectionType(ProposalTemplateDTO, EmployeeFeatureDTO)
	implements IEmployeeProposalTemplateCreateInput {}
