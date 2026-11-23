import { NgModule } from '@angular/core';
import { NbButtonModule, NbIconModule, NbCardModule, NbListModule, NbDialogModule } from '@nebular/theme';
import { TranslatePipe } from '@ngx-translate/core';
import { IRTranscriptsEditableGridComponent } from './irtranscripts-editable-grid.component';
import { IRTranscriptsButtonActionModule } from '../irtranscripts-button-action';

const NbModules = [NbButtonModule, NbIconModule, NbCardModule, NbListModule, NbDialogModule.forChild()];
const OtherModules = [IRTranscriptsButtonActionModule];

@NgModule({
	imports: [...NbModules, ...OtherModules, TranslatePipe],
	declarations: [IRTranscriptsEditableGridComponent],
	exports: [IRTranscriptsEditableGridComponent]
})
export class IRTranscriptsEditableGridModule {}
