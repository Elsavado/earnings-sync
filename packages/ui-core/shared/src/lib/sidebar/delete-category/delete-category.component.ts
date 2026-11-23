import { IHelpCenter } from '@irtranscripts/contracts';
import { Component, OnDestroy, Input, ErrorHandler, ChangeDetectionStrategy } from '@angular/core';
import { NbDialogRef } from '@nebular/theme';
import { TranslateService } from '@ngx-translate/core';
import { TranslationBaseComponent } from '@irtranscripts/ui-core/i18n';
import { HelpCenterService } from '@irtranscripts/ui-core/core';

@Component({
    selector: 'ga-delete-category',
    templateUrl: 'delete-category.component.html',
    styleUrls: ['delete-category.component.scss'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class DeleteCategoryComponent extends TranslationBaseComponent implements OnDestroy {
	@Input() category: IHelpCenter;

	constructor(
		protected readonly dialogRef: NbDialogRef<DeleteCategoryComponent>,
		public readonly translateService: TranslateService,
		private readonly helpCenterService: HelpCenterService,
		private readonly errorHandler: ErrorHandler
	) {
		super(translateService);
	}

	closeDialog() {
		this.dialogRef.close();
	}

	async deleteCategory() {
		try {
			await this.helpCenterService.delete(this.category.id);
		} catch (error) {
			this.errorHandler.handleError(error);
		}
		this.dialogRef.close(this.category);
	}

	ngOnDestroy() {}
}
