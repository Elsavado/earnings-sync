import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { IOrganizationCreateInput, ITenantCreateInput, IUserRegistrationInput } from '@irtranscripts/contracts';
import { API_PREFIX } from '@irtranscripts/ui-core/common';

@Injectable({
	providedIn: 'root'
})
export class IRTranscriptsCloudService {
	constructor(private readonly _http: HttpClient) {}

	migrateIntoCloud(payload: IUserRegistrationInput) {
		return this._http.post(`${API_PREFIX}/cloud/migrate`, payload);
	}

	migrateTenant(payload: ITenantCreateInput, token: string) {
		return this._http.post(`${API_PREFIX}/cloud/migrate/tenant/${token}`, {
			...payload
		});
	}

	migrateOrganization(payload: IOrganizationCreateInput, token: string) {
		return this._http.post(`${API_PREFIX}/cloud/migrate/organization/${token}`, {
			...payload
		});
	}
}
