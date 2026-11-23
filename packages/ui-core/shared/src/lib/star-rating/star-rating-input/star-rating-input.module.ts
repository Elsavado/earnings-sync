import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { NbIconModule } from '@nebular/theme';
import { OrganizationsService } from '@irtranscripts/ui-core/core';
import { RoleService } from '@irtranscripts/ui-core/core';
import { StarRatingInputComponent } from './star-rating-input.component';

@NgModule({
	imports: [CommonModule, NbIconModule],
	exports: [StarRatingInputComponent],
	declarations: [StarRatingInputComponent],
	providers: [OrganizationsService, RoleService]
})
export class StarRatingInputModule {}
