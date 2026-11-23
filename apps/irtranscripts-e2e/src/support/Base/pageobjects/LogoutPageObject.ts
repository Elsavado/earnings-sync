export const LogoutPage = {
	// Sign out lives in the account panel (`irtranscripts-user-menu`, opened by clicking the sidebar's
	// `irtranscripts-user` / DashboardPage.userNameCss). Since #10044 (01171bba2e, "professional panel UI") it is
	// `<a class="panel-row" routerLink="/auth/logout">` (user-menu.component.html) — it used to be a
	// `<p routerLink>`, which is what the old `p[routerlink="/auth/logout"]` matched. Static routerLink is
	// rendered lowercase in the DOM (`routerlink="/auth/logout"`, href="#/auth/logout"). Scoped to the
	// panel host so nothing else on the page can match first.
	logoutButtonCss: 'irtranscripts-user-menu a[routerlink="/auth/logout"]'
};
