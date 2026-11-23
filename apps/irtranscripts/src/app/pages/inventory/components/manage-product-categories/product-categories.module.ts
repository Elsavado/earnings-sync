import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormsModule } from '@angular/forms';
import {
	NbCardModule,
	NbButtonModule,
	NbIconModule,
	NbSpinnerModule,
	NbInputModule,
	NbTooltipModule
} from '@nebular/theme';
import { NgxPermissionsModule } from 'ngx-permissions';
import { TranslatePipe } from '@ngx-translate/core';
import { ProductCategoryService } from '@irtranscripts/ui-core/core';
import { SmartDataViewLayoutModule, CardGridModule, ProductMutationModule } from '@irtranscripts/ui-core/shared';
import { SharedModule } from '@irtranscripts/ui-core/shared';
import { ProductCategoriesComponent } from './product-categories.component';
import { ProductCategoriesRoutingModule } from './product-categories-routing.module';

@NgModule({
	declarations: [ProductCategoriesComponent],
	imports: [
		CommonModule,
		FormsModule,
		ReactiveFormsModule,
		NbCardModule,
		NbButtonModule,
		NbIconModule,
		NbSpinnerModule,
		NbInputModule,
		NbTooltipModule,
		NgxPermissionsModule.forChild(),
		TranslatePipe,
		SharedModule,
		ProductCategoriesRoutingModule,
		ProductMutationModule,
		CardGridModule,
		SmartDataViewLayoutModule
	],
	providers: [ProductCategoryService]
})
export class ProductCategoriesModule {}
