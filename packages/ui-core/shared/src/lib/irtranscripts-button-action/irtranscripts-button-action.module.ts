import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { NbButtonModule, NbIconModule } from '@nebular/theme';
import { TranslatePipe } from '@ngx-translate/core';
import { IRTranscriptsButtonActionComponent } from './irtranscripts-button-action.component';
import { ComponentsModule } from '../components/components.module';

@NgModule({
	imports: [CommonModule, NbButtonModule, NbIconModule, TranslatePipe, ComponentsModule],
	declarations: [IRTranscriptsButtonActionComponent],
	exports: [IRTranscriptsButtonActionComponent]
})
export class IRTranscriptsButtonActionModule {}
