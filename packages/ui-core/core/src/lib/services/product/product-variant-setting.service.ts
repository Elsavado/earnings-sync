import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { IProductVariantSetting } from '@irtranscripts/contracts';
import { firstValueFrom } from 'rxjs';
import { API_PREFIX } from '@irtranscripts/ui-core/common';

@Injectable()
export class ProductVariantSettingService {
	PRODUCT_VARIANT_SETTINGS_URL = `${API_PREFIX}/product-variant-settings`;

	constructor(private readonly http: HttpClient) {}

	updateProductVariantSetting(productVariantSetting: IProductVariantSetting): Promise<IProductVariantSetting> {
		return firstValueFrom(
			this.http.put<IProductVariantSetting>(
				`${this.PRODUCT_VARIANT_SETTINGS_URL}/${productVariantSetting.id}`,
				productVariantSetting
			)
		);
	}

	getProductVariantSettings(): Promise<IProductVariantSetting[]> {
		return firstValueFrom(this.http.get<IProductVariantSetting[]>(this.PRODUCT_VARIANT_SETTINGS_URL));
	}
}
