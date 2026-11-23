import { ITaskLinkedIssueCreateInput } from '@irtranscripts/contracts';
import { TaskLinkedIssueDTO } from './task-linked-issue.dto';

export class CreateTaskLinkedIssueDTO extends TaskLinkedIssueDTO implements ITaskLinkedIssueCreateInput { }
