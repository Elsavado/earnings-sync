// Sorts collected data into the sub-types the collection is organised by. Folder names say
// what a file really is: The Cancer Genome Atlas slides are mostly surgical resections, so a
// prostate slide goes under "Prostate", not under "Prostate core biopsies".

// --- DICOM / Imaging: <specialty>/<CT | MRI | X-ray | Ultrasound> ---

const MODALITY = { CT: 'CT', MR: 'MRI', CR: 'X-ray', DX: 'X-ray', DR: 'X-ray', MG: 'X-ray', RF: 'X-ray', XA: 'X-ray', US: 'Ultrasound' };

export function imagingModality(code) {
  return MODALITY[String(code || '').toUpperCase()] || null;
}

const BODY_PART_SPECIALTY = [
  [/HEART|CARDIAC|CORONARY|AORTA/, 'Cardiology'],
  [/CHEST|LUNG|THORAX|PULMON/, 'Pulmonology'],
  [/BRAIN|HEAD(?!NECK)|SPINE|NEURO|SKULL/, 'Neurology'],
  [/KIDNEY|RENAL/, 'Nephrology'],
  [/THYROID|ADRENAL|PITUITARY|PANCREAS_ENDO/, 'Endocrinology'],
  [/ABDOMEN|LIVER|PANCREAS|COLON|STOMACH|ESOPHAGUS|RECTUM|BOWEL|GI\b/, 'Gastroenterology']
];

// Children's Oncology Group trials (ACNS0332, AREN0534, ...) and named paediatric collections.
const PEDIATRIC_COLLECTION = /^A[A-Z]{2,4}\d{3,4}$|PEDIATRIC|PAEDIATRIC|CHILD|CMB-PCA/i;
const EMERGENCY_COLLECTION = /TRAUMA|EMERGENCY|COVID|RICORD|MIDRC/i;

export function imagingSpecialty(collection, bodyPart) {
  if (PEDIATRIC_COLLECTION.test(collection)) return 'Pediatrics';
  if (EMERGENCY_COLLECTION.test(collection)) return 'Emergency Medicine';
  const part = String(bodyPart || '').toUpperCase();
  for (const [re, specialty] of BODY_PART_SPECIALTY) if (re.test(part)) return specialty;
  // The archive is mainly cancer imaging; anything not placed above is oncology.
  return 'Oncology';
}

// --- Pathology: <whole-slide images | reports>/<site group> ---

const PATHOLOGY_SITES = [
  [/skin/i, 'Dermatology (skin)'],
  [/colon|rect|stomach|esophag|small intestine|anus|digestive/i, 'GI (colon, rectum, gastric, esophageal)'],
  [/cervix|corpus uteri|uterus|endometri/i, 'Cervical & endometrial'],
  [/prostate/i, 'Prostate'],
  [/breast/i, 'Breast'],
  [/hematopoietic|bone marrow|blood|lymph/i, 'Hematopathology (blood, bone marrow, lymph node)'],
  [/thyroid/i, 'Thyroid']
];

export function pathologySite(primarySite) {
  for (const [re, name] of PATHOLOGY_SITES) if (re.test(String(primarySite || ''))) return name;
  return 'Other surgical resection specimens';
}

// --- Genomics: by assay ---

export function genomicsFolder(dataType, strategy) {
  const s = String(strategy || '');
  if (dataType === 'Protein Expression Quantification') return 'Signaling & pathway data (protein expression, RPPA)';
  if (dataType === 'Masked Somatic Mutation') {
    if (s === 'WXS') return 'WES - somatic mutations';
    if (s === 'WGS') return 'WGS - somatic mutations';
    if (s === 'Targeted Sequencing') return 'Gene panels - somatic mutations';
    return 'Somatic mutations';
  }
  if (s === 'WGS') return 'WGS - copy number';
  if (s === 'Targeted Sequencing') return 'Gene panels';
  if (dataType === 'Gene Expression Quantification') return 'Lab molecular data - gene expression (RNA-seq)';
  if (dataType === 'Methylation Beta Value') return 'Lab molecular data - DNA methylation';
  if (/Copy Number/.test(dataType)) return 'Lab molecular data - copy number';
  return `Lab molecular data - ${dataType}`;
}

// GDC is a cancer archive; disease panels are oncology unless the site says otherwise.
export function diseaseArea(primarySite) {
  const site = String(primarySite || '');
  if (/heart|cardiac/i.test(site)) return 'Cardio';
  if (/brain|nervous|spinal/i.test(site)) return 'Neuro';
  return `Onco - ${site || 'unspecified site'}`;
}
