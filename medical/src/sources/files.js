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
      // An entry can name its file outright, e.g. "Chromosome 1 - genotypes of 2,504 people.vcf.gz".
      fileName: f.fileName,
      keepName: Boolean(f.fileName),
      url: f.url,
      unzip: /\.zip$/i.test(f.url),
      license: f.license,
      attribution: f.attribution,
      landing: f.landing || f.url
    };
  }
}
