// Fixed downloads listed in the config, e.g. "EHR" (Synthea synthetic patient records) and
// "Claims" (CMS DE-SynPUF synthetic Medicare claims). Each entry names its own licence;
// zip archives are unpacked into a folder.
export async function* fileListItems(settings) {
  for (const f of settings.files.items) {
    yield {
      source: 'files',
      id: f.url,
      category: f.category,
      path: f.folder,
      prefix: f.prefix,
      title: f.title,
      url: f.url,
      unzip: /\.zip$/i.test(f.url),
      license: f.license,
      attribution: f.attribution,
      landing: f.landing || f.url
    };
  }
}
