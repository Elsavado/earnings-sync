const fs = require('fs');
const path = require('path');

function findPackages(dir) {
	const results = [];
	try {
		const items = fs.readdirSync(dir, { withFileTypes: true });

		for (const item of items) {
			if (item.isDirectory()) {
				const pkgPath = path.join(dir, item.name, 'package.json');
				const projPath = path.join(dir, item.name, 'project.json');

				if (fs.existsSync(pkgPath) && fs.existsSync(projPath)) {
					results.push({ name: item.name, pkgPath, projPath, dir: path.join(dir, item.name) });
				}

				// Check subdirectories (for plugins)
				const subDir = path.join(dir, item.name);
				try {
					const subItems = fs.readdirSync(subDir, { withFileTypes: true });
					for (const subItem of subItems) {
						if (subItem.isDirectory()) {
							const subPkgPath = path.join(subDir, subItem.name, 'package.json');
							const subProjPath = path.join(subDir, subItem.name, 'project.json');
							if (fs.existsSync(subPkgPath) && fs.existsSync(subProjPath)) {
								results.push({
									name: subItem.name,
									pkgPath: subPkgPath,
									projPath: subProjPath,
									dir: path.join(subDir, subItem.name)
								});
							}
						}
					}
				} catch (e) {}
			}
		}
	} catch (e) {
		console.error('Error scanning directory:', e.message);
	}
	return results;
}

const packages = findPackages('packages');
console.log('Found', packages.length, 'packages\n');

const irtranscriptsPkgNameToNxName = {
	'@irtranscripts/constants': 'constants',
	'@irtranscripts/contracts': 'contracts',
	'@irtranscripts/common': 'common',
	'@irtranscripts/utils': 'utils',
	'@irtranscripts/config': 'config',
	'@irtranscripts/plugin': 'plugin',
	'@irtranscripts/auth': 'auth',
	'@irtranscripts/core': 'core',
	'@irtranscripts/ui-core': 'ui-core',
	'@irtranscripts/ui-config': 'ui-config',
	'@irtranscripts/ui-auth': 'ui-auth',
	'@irtranscripts/desktop-lib': 'desktop-lib',
	'@irtranscripts/desktop-ui-lib': 'desktop-ui-lib',
	'@irtranscripts/desktop-window': 'desktop-window',
	'@irtranscripts/desktop-core': 'desktop-core',
	'@irtranscripts/desktop-activity': 'desktop-activity',
	'@irtranscripts/mcp-server': 'mcp-server',
	'@irtranscripts/plugin-integration-ai': 'plugin-integration-ai',
	'@irtranscripts/plugin-integration-github': 'plugin-integration-github',
	'@irtranscripts/plugin-integration-hubstaff': 'plugin-integration-hubstaff',
	'@irtranscripts/plugin-integration-upwork': 'plugin-integration-upwork',
	'@irtranscripts/plugin-job-proposal': 'plugin-job-proposal',
	'@irtranscripts/plugin-job-search': 'plugin-job-search'
};

const issues = [];

for (const pkg of packages) {
	try {
		const pkgJson = JSON.parse(fs.readFileSync(pkg.pkgPath, 'utf8'));
		const projJson = JSON.parse(fs.readFileSync(pkg.projPath, 'utf8'));

		const deps = { ...pkgJson.dependencies, ...pkgJson.peerDependencies };
		const irtranscriptsDeps = Object.keys(deps).filter((d) => d.startsWith('@irtranscripts/'));

		const nxNames = irtranscriptsDeps.map((d) => irtranscriptsPkgNameToNxName[d]).filter(Boolean);
		const currentImplicit = projJson.implicitDependencies || [];

		const missing = nxNames.filter((n) => !currentImplicit.includes(n));

		if (missing.length > 0) {
			issues.push({
				name: pkg.name,
				path: pkg.projPath,
				current: currentImplicit,
				shouldHave: nxNames,
				missing: missing
			});
		}
	} catch (e) {
		console.error('Error processing', pkg.name, ':', e.message);
	}
}

if (issues.length === 0) {
	console.log('All packages have correct implicitDependencies!');
} else {
	console.log('Packages with missing implicitDependencies:', issues.length);
	for (const issue of issues) {
		console.log('\n' + issue.name + ':');
		console.log('  Path:', issue.path);
		console.log('  Current:', issue.current.join(', '));
		console.log('  Should have:', issue.shouldHave.join(', '));
		console.log('  Missing:', issue.missing.join(', '));
	}
}
