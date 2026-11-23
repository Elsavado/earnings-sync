import { ICommand } from "@nestjs/cqrs";
import { ISharedEntityCreateInput } from "@irtranscripts/contracts";

export class SharedEntityCreateCommand implements ICommand {
    static readonly type = '[SharedEntity] Create';

    constructor(public readonly input: ISharedEntityCreateInput) {}
}
