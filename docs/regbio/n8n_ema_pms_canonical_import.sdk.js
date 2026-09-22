import { workflow, node, trigger, sticky, expr } from '@n8n/workflow-sdk';

const SUPA = 'https://tibfpnoeerzonkkxecmb.supabase.co/rest/v1/rpc/';
const PMS = 'https://api.pms.ema.europa.eu/public/v1/';

const startTrigger = trigger({
  type: 'n8n-nodes-base.manualTrigger',
  version: 1,
  config: { name: 'Manual Trigger', position: [0, 300] },
  output: [{}]
});

const params = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Parameter',
    parameters: {
      mode: 'runOnceForAllItems',
      jsCode: "// Selbst-fortsetzender Batch: je Lauf die naechsten `limit` Kandidaten, die im run_id noch nicht importiert sind.\n// Flow so oft starten, bis Summary.candidates == 0 (oder nur noch Dauer-Nichttreffer).\nconst today = new Date().toISOString().slice(0, 10);\nconst RUN_SUFFIX = '-v2'; // leer lassen fuer den normalen Tageslauf; Suffix setzen, um alle Kandidaten neu abzuziehen\nconst run_id = 'pms-import-' + today + RUN_SUFFIX;\nreturn [{ json: { run_id, limit: 100, offset: 0, only_missing: false, exclude_run_id: run_id } }];\n"
    },
    position: [220, 300]
  },
  output: [{ run_id: 'pms-import-2026-09-22-v2', limit: 100, offset: 0, only_missing: false, exclude_run_id: 'pms-import-2026-09-22-v2' }]
});

const candidates = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.4,
  config: {
    name: 'Kandidaten (Supabase)',
    parameters: {
      method: 'POST',
      url: SUPA + 'pms_import_candidates',
      authentication: 'predefinedCredentialType',
      nodeCredentialType: 'supabaseApi',
      sendHeaders: true,
      headerParameters: { parameters: [{ name: 'Content-Type', value: 'application/json' }] },
      sendBody: true,
      specifyBody: 'json',
      jsonBody: expr('{{ JSON.stringify({ p_limit: $json.limit, p_offset: $json.offset, p_only_missing: $json.only_missing, p_exclude_run_id: $json.exclude_run_id }) }}'),
      options: { response: { response: { responseFormat: 'json' } } }
    },
    position: [440, 300]
  },
  output: [{ reg_product_id: 'x', product_name: 'Mvasi', procedure_number: 'EMEA/H/C/004728', is_biosimilar: true, mah: 'Amgen' }]
});

const searchNameClean = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Suchname',
    parameters: {
      mode: 'runOnceForEachItem',
      jsCode: "// Klammerzusaetze wie '(previously Abasria)' entfernen, Whitespace normalisieren\nconst n = String($json.product_name || '');\nlet clean = n;\nconst i = n.indexOf('(');\nif (i > 0) clean = n.slice(0, i);\nclean = clean.split(' ').filter(Boolean).join(' ').trim();\nreturn { json: Object.assign({}, $json, { search_name: clean || n }) };\n"
    },
    position: [640, 300]
  },
  output: [{ reg_product_id: 'x', product_name: 'Abasaglar (previously Abasria)', search_name: 'Abasaglar', procedure_number: 'EMEA/H/C/002835' }]
});

const searchName = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.4,
  config: {
    name: 'PMS Suche Name',
    parameters: {
      method: 'GET',
      url: expr('{{ "' + PMS + 'MedicinalProductDefinition?name=" + encodeURIComponent($json.search_name) + "&_count=100" }}'),
      authentication: 'genericCredentialType',
      genericAuthType: 'oAuth2Api',
      sendHeaders: true,
      headerParameters: { parameters: [{ name: 'Accept', value: 'application/fhir+json' }] },
      options: { response: { response: { responseFormat: 'json' } }, timeout: 60000, batching: { batch: { batchSize: 8, batchInterval: 1300 } } }
    },
    onError: 'continueRegularOutput',
    position: [840, 300]
  },
  output: [{ resourceType: 'Bundle', total: 1, entry: [] }]
});

const filterIds = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'MPD-IDs filtern',
    parameters: {
      mode: 'runOnceForAllItems',
      jsCode: "function unwrap(x){ let b = x; if (b && typeof b.data !== 'undefined' && !b.resourceType) b = b.data; if (typeof b === 'string') { try { b = JSON.parse(b); } catch (e) {} } return b; }\nconst cands = $('Suchname').all().map(x => x.json);\nconst out = [];\n$input.all().forEach((item, i) => {\n  const c = cands[i] || {};\n  const b = unwrap(item.json || {});\n  const entries = ((b && b.entry) || []).map(e => e.resource || {}).filter(r => r.resourceType === 'MedicinalProductDefinition');\n  const nm = String(c.search_name || c.product_name || '').toLowerCase().trim();\n  const nameOf = r => { const n = (r.name || [])[0] || {}; const bp = (n.part || []).find(p => ((((p.type || {}).coding || [])[0] || {}).code) === '220000000002'); return String((bp && bp.part) || n.productName || '').toLowerCase().trim(); };\n  let hits = entries.filter(r => { const n = nameOf(r); return n === nm || n.indexOf(nm + ' ') === 0; });\n  if (!hits.length) hits = entries.filter(r => nameOf(r).indexOf(nm) === 0);\n  if (!hits.length) hits = entries.filter(r => nameOf(r).indexOf(nm) >= 0);\n  const eu = hits.filter(r => String(r.id).indexOf('6000') === 0);\n  const chosen = eu.length ? eu : hits;\n  for (const r of chosen) {\n    out.push({ json: { reg_product_id: c.reg_product_id, product_name: c.product_name, search_name: c.search_name, procedure_number: c.procedure_number, is_biosimilar: c.is_biosimilar, mah: c.mah,\n      mpd_id: String(r.id), pms_product_name: (((r.name || [])[0] || {}).productName) || null,\n      search_total: (b && b.total != null) ? b.total : entries.length, kept: chosen.length, eu_level: eu.length > 0 } });\n  }\n});\nreturn out;\n"
    },
    position: [1040, 300]
  },
  output: [{ reg_product_id: 'x', product_name: 'Mvasi', procedure_number: 'EMEA/H/C/004728', mpd_id: '600001873862' }]
});

const fetchEverything = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.4,
  config: {
    name: 'PMS $everything',
    parameters: {
      method: 'GET',
      url: expr('{{ "' + PMS + 'MedicinalProductDefinition/" + $json.mpd_id + "/$everything" }}'),
      authentication: 'genericCredentialType',
      genericAuthType: 'oAuth2Api',
      sendHeaders: true,
      headerParameters: { parameters: [{ name: 'Accept', value: 'application/fhir+json' }] },
      options: { response: { response: { responseFormat: 'json' } }, timeout: 60000, batching: { batch: { batchSize: 8, batchInterval: 1300 } } }
    },
    onError: 'continueRegularOutput',
    position: [1240, 300]
  },
  output: [{ resourceType: 'Bundle', entry: [] }]
});

const extract = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Extract Referenzfelder',
    parameters: {
      mode: 'runOnceForAllItems',
      jsCode: "// ---- PMS $everything -> Referenzfelder (core, shared between local test and n8n node) ----\n// Einheiten-Codes (SPOR-Liste 100000110633 + UCUM-Varianten). Familien: mass (mg/g/mcg -> mg) und units (IU/U/MIU/MU, Label bleibt erhalten)\nconst UNIT = { '100000110655':'mg','MG':'mg','MILLIGRAM':'mg','100000110662':'ml','ML':'ml','MILLILITRE':'ml',\n  '100000110633':'mg','IU':'IU','100000110671':'IU','100000110648':'IU','INTERNATIONAL UNIT':'IU','1[IU]':'IU','[IU]':'IU','MA[IU]':'MIU','MIU':'MIU',\n  '100000110756':'U','U':'U','UNIT':'U','UNITS':'U','[U]':'U','MA[U]':'MU','MU':'MU',\n  'MCG':'mcg','UG':'mcg','MICROGRAM':'mcg','100000110656':'mcg','100000110660':'mcg','G':'g','GRAM':'g','100000110654':'g',\n  '100000110665':'MBq','MABQ':'MBq',\n  '200000002150':'pre-filled syringe','200000002158':'vial','200000002151':'pre-filled pen','200000002135':'pen','200000002114':'cartridge','200000002121':'cartridge','200000002164':'pre-filled pen' };\nconst WORDNUM = { one:1, two:2, three:3, four:4, five:5, six:6, seven:7, eight:8, nine:9, ten:10, twelve:12, twenty:20 };\nconst MASS = { mg: 1, g: 1000, mcg: 0.001 };                 // Faktor -> mg\nconst UNITS = { IU: 1, U: 1, MIU: 1000000, MU: 1000000 };     // Faktor -> Einzel-Einheit (nur fuer Umrechnung zwischen Labels)\nconst familyOf = u => MASS[u] != null ? 'mass' : (UNITS[u] != null ? 'units' : null);\nconst AMOUNT_UNITS = ['mg','IU','mcg','g','U','MU','MIU'];\nconst NAMEPART = { '220000000002':'brand','220000000004':'strength_text','220000000005':'dose_form_text' };\nconst unitOf = c => (c && UNIT[c]) ? UNIT[c] : (c || null);\nconst num = x => (x == null || x === '') ? null : Number(x);\n// Text-Einheit (description / Staerke-Text) -> kanonisches Label\nconst TEXTUNIT = [[/^(mg|milligrams?)$/, 'mg'], [/^(µg|μg|ug|mcg|micrograms?)$/, 'mcg'], [/^(g|grams?)$/, 'g'],\n  [/^(million iu|miu|mio\\.? iu|m iu)$/, 'MIU'], [/^(million units?|mu|mio\\.? u|m u)$/, 'MU'], [/^(iu|i\\.u\\.|international units?)$/, 'IU'], [/^(u|units?)$/, 'U']];\nconst textUnit = t => { const s = String(t || '').trim().toLowerCase(); for (const p of TEXTUNIT) { if (p[0].test(s)) return p[1]; } return null; };\nconst UNITRX = '(mg|milligrams?|µg|μg|ug|mcg|micrograms?|million iu|million units?|m iu|m u|miu|mu|iu|i\\\\.u\\\\.|international units?|units?|u|g)';\n// Wert+Einheit in das Primaerlabel umrechnen (mg | IU | U | MU | MIU); null wenn die Familie nicht passt\nfunction convTo(value, unit, label) {\n  if (value == null || !unit || !label) return null;\n  if (label === 'mg') return MASS[unit] != null ? +(value * MASS[unit]).toFixed(6) : null;\n  if (UNITS[unit] == null || UNITS[label] == null) return null;\n  return +(value * UNITS[unit] / UNITS[label]).toFixed(6);\n}\nconst parseNum = t => num(String(t).replace(',', '.'));\n\nfunction parseDescription(d) {\n  const out = { units_per_pack: null, fill_volume_ml: null, solvent_ml: null, amount: null, conc: null };\n  if (!d) return out;\n  const s = String(d).replace(/\\s+/g, ' ').trim();\n  const lower = s.toLowerCase();\n  const toN = t => { const w = String(t).toLowerCase(); return WORDNUM[w] != null ? WORDNUM[w] : num(w); };\n  const CONT = '(?:pre-filled|prefilled|vial|pen|cartridge|syringe|bottle|ampoule|bag|kit)';\n  let m;\n  if ((m = lower.match(/package_size:\\s*(\\d+)/))) out.units_per_pack = num(m[1]);\n  else if ((m = lower.match(/pack size of (\\d+)/))) out.units_per_pack = num(m[1]);\n  else if ((m = lower.match(/pack of (\\d+)/))) out.units_per_pack = num(m[1]);\n  else if ((m = lower.match(new RegExp('^(\\\\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty)\\\\s+' + CONT)))) out.units_per_pack = toN(m[1]);\n  else if ((m = lower.match(new RegExp('containing\\\\s+(\\\\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty)\\\\s+' + CONT)))) out.units_per_pack = toN(m[1]);\n  else if ((m = lower.match(/(\\d+)\\s*x\\s*(\\d+(?:[.,]\\d+)?)\\s*ml/))) out.units_per_pack = num(m[1]);\n  else if (/\\bin a (vial|syringe|pen|cartridge|bottle)\\b/.test(lower) || /^vial\\b/.test(lower) || /^(a |1 )?(pre-filled )?(vial|syringe|pen|cartridge)\\b/.test(lower)) out.units_per_pack = 1;\n  // Loesungsmittel (Pulver): \"solvent: 1 ml\", \"solvent 2 ml\", \"solvent: 1.0 ml (1000 IU/ml)\"\n  if ((m = lower.match(/solvent:?\\s*([\\d.,]+)\\s*ml/))) out.solvent_ml = parseNum(m[1]);\n  // Fuellvolumen (Loesung); \"content:solvent: 1 ml\" greift hier bewusst nicht\n  if ((m = lower.match(/(\\d+)\\s*x\\s*([\\d.,]+)\\s*ml/))) out.fill_volume_ml = parseNum(m[2]);\n  else {\n    const vol = [\n      /content:\\s*([\\d.,]+)\\s*ml/, /contains\\s*([\\d.,]+)\\s*ml/, /containing\\s*([\\d.,]+)\\s*ml/, /\\bof\\s*([\\d.,]+)\\s*ml/,\n      /([\\d.,]+)\\s*ml\\s*per\\s*(?:pen|vial|syringe|cartridge)/, /^\\s*([\\d.,]+)\\s*ml\\b/, /([\\d.,]+)\\s*ml\\s*(?:solution|suspension|concentrate|emulsion)/\n    ];\n    for (const rx of vol) { if ((m = lower.match(rx))) { out.fill_volume_ml = parseNum(m[1]); break; } }\n  }\n  // Menge aus Text: \"containing 25 mg\", \"powder: 25 mg\", \"content: 150 mg\" (nicht \"content:500 U/ml\")\n  if ((m = lower.match(new RegExp('(?:containing|powder:?|content:?)\\\\s*([\\\\d.,]+)\\\\s*' + UNITRX + '\\\\b(?!\\\\s*/)')))) out.amount = { value: parseNum(m[1]), unit: textUnit(m[2]) };\n  // Konzentration in Klammern: \"(3.5 mg/ml)\", \"(10000 IU/ml)\", \"(24 million IU/ml)\", \"(40 µg/ml)\"\n  if ((m = lower.match(new RegExp('\\\\(\\\\s*([\\\\d.,]+)\\\\s*' + UNITRX + '\\\\s*/\\\\s*ml\\\\s*\\\\)')))) out.conc = { value: parseNum(m[1]), unit: textUnit(m[2]) };\n  return out;\n}\n// Konzentration aus dem Staerke-Text des Produktnamens (\"100 UNITS/ML\", \"10 MG/ML\")\nfunction parseConcText(t) {\n  const m = String(t || '').toLowerCase().match(new RegExp('([\\\\d.,]+)\\\\s*' + UNITRX + '\\\\s*/\\\\s*ml'));\n  return m ? { value: parseNum(m[1]), unit: textUnit(m[2]) } : null;\n}\n\nfunction extractBundle(b, meta) {\n  meta = meta || {};\n  if (!b || !b.entry) return { label: meta.label, pms_id: meta.pms_id, ok: false, error: (b && b.error && b.error.message) || (b && b.error) || 'kein Bundle' };\n  const entries = b.entry.map(e => e.resource || {});\n  const byType = t => entries.filter(r => r.resourceType === t);\n  const counts = {}; for (const r of entries) counts[r.resourceType] = (counts[r.resourceType] || 0) + 1;\n\n  const mpd = byType('MedicinalProductDefinition')[0] || {};\n  const nameObj = (mpd.name || [])[0] || {};\n  const parts = {};\n  for (const p of (nameObj.part || [])) { const code = (((p.type || {}).coding || [])[0] || {}).code; if (NAMEPART[code]) parts[NAMEPART[code]] = p.part; }\n\n  const regs = byType('RegulatedAuthorization');\n  const maOf = r => (r.identifier || []).filter(x => /MarketingAuthorizationNumber/.test(x.system || '')).map(x => x.value);\n  const holderReg = regs.find(r => r.holder) || {};\n  const mpdRegs = regs.filter(r => (r.subject || []).some(s => /^MedicinalProductDefinition\\//.test(s.reference || '')));\n  const baseReg = mpdRegs.find(r => maOf(r).some(v => /^EU\\/1\\//.test(v))) || mpdRegs[0] || {};\n  // Verfahrensnummer normalisieren: Whitespace, Grossschreibung, Variations-Suffix \"/0000\" (z. B. EMEA/H/C/006152/0000)\n  const normProc = v => v ? String(v).trim().toUpperCase().replace(/\\/[0-9]{4}$/, '') : null;\n  const dose_form = parts.dose_form_text || '';\n  const is_powder = /powder/i.test(dose_form);\n  const is_oral_solid = /tablet|capsule/i.test(dose_form);\n\n  // Ingredients: strength sits under substance.strength (FHIR R5); alle Strength-Eintraege, je mit Ziel-Ressource (MID/APD)\n  const ingredients = [];\n  for (const ing of byType('Ingredient')) {\n    const forRefs = (ing.for || []).map(f => f.reference || '').filter(Boolean);\n    const strengths = (ing.substance && ing.substance.strength) || ing.strength || [];\n    const substance_code = ((((((ing.substance || {}).code || {}).concept || {}).coding || [])[0]) || {}).code || null;\n    for (const s of (strengths.length ? strengths : [{}])) {\n      const kind = s.presentationRatio ? 'presentationRatio' : (s.concentrationRatio ? 'concentrationRatio' : 'none');\n      const r = s.presentationRatio || s.concentrationRatio || {};\n      for (const ref of (forRefs.length ? forRefs : [''])) {\n        ingredients.push({\n          for: ref.split('/')[0] || null, for_id: ref.split('/')[1] || null, substance_code, strength_kind: kind,\n          numerator_value: num((r.numerator || {}).value), numerator_unit: unitOf((r.numerator || {}).code),\n          denominator_value: num((r.denominator || {}).value), denominator_unit: unitOf((r.denominator || {}).code),\n          text: s.textPresentation || null\n        });\n      }\n    }\n  }\n  // Primaerfamilie je Produkt: units (IU/U) wenn irgendein Verhaeltnis Einheiten liefert, sonst mass (mg/mcg/g -> mg). Keine Familien mischen.\n  const anyUnits = ingredients.some(i => familyOf(i.numerator_unit) === 'units');\n  const primaryFamily = anyUnits ? 'units' : (ingredients.some(i => familyOf(i.numerator_unit) === 'mass') ? 'mass' : null);\n  const inPrimary = i => primaryFamily != null && familyOf(i.numerator_unit) === primaryFamily && i.numerator_value != null;\n  const mids = ingredients.filter(i => i.for === 'ManufacturedItemDefinition' && inPrimary(i));\n  const apds = ingredients.filter(i => i.for === 'AdministrableProductDefinition' && inPrimary(i));\n  // Label: mg fuer Masse; bei Einheiten das Label der Fertigeinheit (U/IU/MU/MIU), sonst des APD, sonst IU\n  const primaryLabel = primaryFamily === 'mass' ? 'mg' : (primaryFamily === 'units' ? (mids[0] ? mids[0].numerator_unit : (apds[0] ? apds[0].numerator_unit : 'IU')) : null);\n  const normVal = i => convTo(i.numerator_value, i.numerator_unit, primaryLabel);\n  const mixedUnitLabels = primaryFamily === 'units' && ingredients.some(i => inPrimary(i) && i.numerator_unit !== primaryLabel);\n  // Fertigeinheiten aufloesen: 1 Eintrag -> Wert; verschiedene Wirkstoffe -> Summe (Kombination, pruefen);\n  // gleicher Wirkstoff mit gleichen Werten -> Wert; gleicher Wirkstoff mit verschiedenen Werten -> Groessenvarianten, unklar\n  function resolveMid(list) {\n    if (!list.length) return { value: null, note: null };\n    if (list.length === 1) return { value: normVal(list[0]), note: null };\n    const subs = new Set(list.map(i => i.substance_code));\n    const vals = list.map(normVal);\n    if (subs.size === list.length) return { value: +(vals.reduce((a, v) => a + v, 0).toFixed(6)), note: 'Kombination: ' + list.length + ' Komponenten summiert, pruefen' };\n    if (vals.every(v => v === vals[0])) return { value: vals[0], note: null };\n    return { value: null, note: 'mehrere Staerken je Fertigeinheit (' + vals.join('/') + ' ' + primaryLabel + '), Zuordnung unklar' };\n  }\n  const midAll = resolveMid(mids);\n  const apdSum = apds.length ? +(apds.reduce((a, i) => a + normVal(i), 0).toFixed(6)) : null;\n  const apd = apds.length && apds.every(i => i.denominator_unit === apds[0].denominator_unit && i.denominator_value === apds[0].denominator_value) ? { numerator_value: apdSum, denominator_unit: apds[0].denominator_unit, denominator_value: apds[0].denominator_value } : (apds[0] ? { numerator_value: normVal(apds[0]), denominator_unit: apds[0].denominator_unit, denominator_value: apds[0].denominator_value } : null);\n  const amount_unit = primaryLabel;\n  let amount_mg = null, volume_ml = null, conc_mg_ml = null, strength_pattern = 'none';\n  if (apd && apd.denominator_unit === 'ml') {\n    const av = apd.numerator_value;\n    if (apd.denominator_value === 1 && !(midAll.value != null && midAll.value === av)) { conc_mg_ml = av; strength_pattern = 'concentration_only'; }\n    else { amount_mg = av; volume_ml = apd.denominator_value; conc_mg_ml = (volume_ml ? +(amount_mg / volume_ml).toFixed(4) : null); strength_pattern = 'amount_and_volume'; }\n  }\n  if (midAll.value != null && amount_mg == null) { amount_mg = midAll.value; strength_pattern = is_powder ? 'powder_amount' : (strength_pattern === 'none' ? 'amount_per_unit' : strength_pattern); }\n  if (is_powder && strength_pattern === 'amount_and_volume') strength_pattern = 'powder_amount';\n  // Konzentration aus dem Staerke-Text als Rueckfall (z. B. \"100 UNITS/ML\" bei Insulinen ohne Packungstext)\n  const tc = parseConcText(parts.strength_text);\n  const conc_text = tc ? convTo(tc.value, tc.unit, primaryLabel) : null;\n  const secondary = ingredients.filter(i => !inPrimary(i) && AMOUNT_UNITS.includes(i.numerator_unit)).map(i => ({ for: i.for, value: i.numerator_value, unit: i.numerator_unit, per: i.denominator_value, per_unit: i.denominator_unit }));\n\n  const containedMids = p => { const refs = []; (function walk(pk) { if (!pk) return; for (const ci of (pk.containedItem || [])) refs.push(String((((ci.item || {}).reference || {}).reference) || '')); for (const sub of (pk.packaging || [])) walk(sub); })(p.packaging); return refs.filter(x => /^ManufacturedItemDefinition\\//.test(x)).map(x => x.split('/')[1]); };\n\n  const packages = byType('PackagedProductDefinition').map(p => {\n    const pk = p.packaging || null;\n    const ciq = (p.containedItemQuantity || [])[0] || null;\n    const pkRegs = regs.filter(r => (r.subject || []).some(s => (s.reference || '') === 'PackagedProductDefinition/' + p.id));\n    const desc = parseDescription(p.description);\n    const hard = [], soft = [];\n    // Textangaben nur uebernehmen, wenn sie zur Primaerfamilie passen (mg-Angabe bei Insulin in Einheiten wird ignoriert)\n    const dAmt = desc.amount ? convTo(desc.amount.value, desc.amount.unit, primaryLabel) : null;\n    const dConc = desc.conc ? convTo(desc.conc.value, desc.conc.unit, primaryLabel) : null;\n    const ciqVal = ciq ? num(ciq.value) : null;\n    const units = (ciqVal != null && ciqVal > 0) ? ciqVal : desc.units_per_pack;\n    const conc = dConc != null ? dConc : (conc_mg_ml != null ? conc_mg_ml : conc_text);\n    const conc_src = dConc != null ? 'pms.description' : (conc_mg_ml != null ? 'pms.ingredient.administrable' : (conc_text != null ? 'pms.name.strength' : null));\n    // Fertigeinheiten dieser Packung (ueber containedItem), sonst alle\n    const ids = containedMids(p);\n    const pm = ids.length ? mids.filter(i => ids.includes(i.for_id)) : mids;\n    const midPkg = (ids.length && pm.length) ? resolveMid(pm) : midAll;\n    // Fuellvolumen (Loesungen): Packungstext > APD-Verhaeltnis\n    let fill = null, fill_src = null, recon = null, recon_src = null;\n    if (!is_powder && !is_oral_solid) {\n      if (desc.fill_volume_ml != null) { fill = desc.fill_volume_ml; fill_src = 'pms.description'; }\n      else if (volume_ml != null) { fill = volume_ml; fill_src = 'pms.ingredient.administrable'; }\n    }\n    // Menge je Einheit: Packungstext > Volumen x Konzentration > Fertigeinheit > APD\n    let amt = null, amt_src = null;\n    if (dAmt != null) { amt = dAmt; amt_src = 'pms.description'; }\n    else if (!is_powder && fill != null && conc != null) { amt = +(fill * conc).toFixed(4); amt_src = 'derived.volume*concentration'; }\n    else if (midPkg.value != null) { amt = midPkg.value; amt_src = 'pms.ingredient.manufactured'; if (midPkg.note) hard.push(midPkg.note); }\n    else if (amount_mg != null) { amt = amount_mg; amt_src = 'pms.ingredient.administrable'; }\n    else if (midPkg.note) hard.push(midPkg.note);\n    // Fuellvolumen aus Menge/Konzentration ableiten (Loesungen ohne Packungstext)\n    if (!is_powder && !is_oral_solid && fill == null && amt != null && conc) { fill = +(amt / conc).toFixed(4); fill_src = 'derived.amount/concentration'; soft.push('Fuellvolumen aus Menge/Konzentration abgeleitet, SmPC pruefen'); }\n    if (is_powder) {\n      // Rekonstitution: Loesungsmittel der Packung > Volumenangabe im Text > APD-Verhaeltnis > Menge/Konzentration\n      if (desc.solvent_ml != null) { recon = desc.solvent_ml; recon_src = 'pms.description.solvent'; }\n      else if (desc.fill_volume_ml != null) { recon = desc.fill_volume_ml; recon_src = 'pms.description'; }\n      else if (volume_ml != null) { recon = volume_ml; recon_src = 'pms.ingredient.administrable'; }\n      else if (amt != null && conc) { recon = +(amt / conc).toFixed(4); recon_src = 'derived.amount/concentration'; }\n      if (amt == null && recon != null && conc != null) { amt = +(recon * conc).toFixed(4); amt_src = 'derived.volume*concentration'; }\n      if (recon != null) soft.push(recon_src === 'pms.description.solvent' ? 'Rekonstitutionsvolumen = Loesungsmittel der Packung, SmPC pruefen' : 'Rekonstitutionsvolumen abgeleitet, SmPC pruefen');\n    }\n    if (units == null) hard.push('units_per_pack unbekannt');\n    if (amt == null) hard.push('Menge/Unit unbekannt');\n    if (!is_oral_solid && fill == null && recon == null) hard.push('Volumen unbekannt');\n    if (!amount_unit) hard.push('keine Mengeneinheit (mg/IU/U) erkannt');\n    if (mixedUnitLabels) hard.push('U/IU/MU gemischt, pruefen');\n    if (amount_unit === 'mg' && amt != null && amt > 5000) hard.push('Menge unplausibel (>5 g je Einheit), PMS-Einheit pruefen');\n    const vol = fill != null ? fill : recon;\n    const basis = fill != null ? (fill_src === 'derived.amount/concentration' ? 'fill_derived' : 'fill')\n      : (recon != null ? ({ 'pms.description.solvent': 'reconstituted_solvent', 'pms.description': 'reconstituted_text', 'pms.ingredient.administrable': 'reconstituted_apd' }[recon_src] || 'reconstituted_derived')\n      : (is_oral_solid ? 'not_applicable' : null));\n    return {\n      package_id: p.id,\n      ma_numbers: [...new Set(pkRegs.flatMap(maOf))],\n      description: p.description || null,\n      units_per_pack: units, unit_type: ciq ? unitOf(ciq.code) : null,\n      units_source: (ciqVal != null && ciqVal > 0) ? 'containedItemQuantity' : (desc.units_per_pack != null ? 'description' : null),\n      amount_per_unit_value: amt, amount_per_unit_unit: amount_unit, fill_volume_per_unit_ml: fill,\n      volume_source: fill != null ? fill_src : recon_src,\n      reconstituted_volume_per_unit_ml: recon,\n      total_amount_value: (units != null && amt != null) ? +(units * amt).toFixed(4) : null,\n      total_volume_ml: (units != null && vol != null) ? +(units * vol).toFixed(4) : null,\n      total_volume_basis: basis,\n      concentration_value: conc != null ? conc : (amt != null && fill ? +(amt / fill).toFixed(4) : null),\n      has_structured_packaging: !!pk,\n      needs_review: hard.length > 0,\n      review_note: hard.concat(soft).join('; ') || null,\n      field_sources: { units: (ciqVal != null && ciqVal > 0) ? 'pms.containedItemQuantity' : (desc.units_per_pack != null ? 'pms.description' : null),\n                       amount: amt_src, volume: fill != null ? fill_src : recon_src, concentration: conc_src }\n    };\n  });\n\n  return {\n    label: meta.label, pms_id: meta.pms_id, ok: true,\n    product_name: nameObj.productName || null, brand: parts.brand || null,\n    strength_text: parts.strength_text || null, dose_form_text: parts.dose_form_text || null,\n    is_powder: is_powder,\n    mah: (holderReg.holder || {}).display || null,\n    ma_base_number: (maOf(baseReg)[0]) || null,\n    procedure_number: normProc((mpdRegs.concat(regs).map(r => (((r.case || {}).identifier) || {}).value).find(v => v)) || null),\n    strength_pattern, amount_unit: amount_unit, amount_per_unit_value: amount_mg, fill_volume_per_unit_ml: volume_ml, concentration_value: conc_mg_ml, secondary_strengths: secondary,\n    route_text: (function(){ const a = byType('AdministrableProductDefinition')[0] || {}; const r = ((a.routeOfAdministration||[])[0]||{}).code; return r ? (((r.coding||[])[0]||{}).code || null) : null; })(),\n    packages, ingredients, resource_counts: counts\n  };\n}\n\n\nfunction unwrap(x){ let b = x; if (b && typeof b.data !== 'undefined' && !b.resourceType) b = b.data; if (typeof b === 'string') { try { b = JSON.parse(b); } catch (e) {} } return b; }\nconst metas = $('MPD-IDs filtern').all();\nconst out = [];\n$input.all().forEach((item, i) => {\n  const meta = (metas[i] && metas[i].json) || {};\n  const b = unwrap(item.json || {});\n  const r = extractBundle(b, { label: meta.product_name, pms_id: meta.mpd_id });\n  r.candidate = { reg_product_id: meta.reg_product_id, product_name: meta.product_name, procedure_number: meta.procedure_number, is_biosimilar: meta.is_biosimilar, mah_reg: meta.mah };\n  const normProc = v => v ? String(v).trim().toUpperCase().replace(/\\/[0-9]{4}$/, '') : null;\n  r.procedure_match = !!(r.ok && r.procedure_number && meta.procedure_number && r.procedure_number === normProc(meta.procedure_number));\n  r.raw_bundle = r.ok ? b : null;\n  out.push({ json: r });\n});\nreturn out;\n"
    },
    position: [1460, 300]
  },
  output: [{ ok: true, procedure_match: true, pms_id: '600001873862', packages: [] }]
});

const stagePayload = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Stage-Payload',
    parameters: {
      mode: 'runOnceForEachItem',
      jsCode: "if (!$json.ok || !$json.raw_bundle) return null;\nreturn { json: { p_run_id: $('Parameter').first().json.run_id, p_pms_product_id: $json.pms_id, p_queried_key: $json.candidate.product_name, p_bundle: $json.raw_bundle, p_http_status: 200 } };\n"
    },
    position: [1680, 300]
  },
  output: [{ p_run_id: 'pms-import-2026-09-22', p_pms_product_id: '600001873862', p_queried_key: 'Mvasi', p_bundle: {}, p_http_status: 200 }]
});

const stageRpc = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.4,
  config: {
    name: 'Stage RPC (Supabase)',
    parameters: {
      method: 'POST',
      url: SUPA + 'pms_stage',
      authentication: 'predefinedCredentialType',
      nodeCredentialType: 'supabaseApi',
      sendHeaders: true,
      headerParameters: { parameters: [{ name: 'Content-Type', value: 'application/json' }] },
      sendBody: true,
      specifyBody: 'json',
      jsonBody: expr('{{ JSON.stringify($json) }}'),
      options: { response: { response: { responseFormat: 'json' } }, batching: { batch: { batchSize: 10, batchInterval: 300 } } }
    },
    onError: 'continueRegularOutput',
    position: [1900, 300]
  },
  output: [{ staged: true }]
});

const buildUpsert = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Upsert-Payload bauen',
    parameters: {
      mode: 'runOnceForAllItems',
      jsCode: "const ex = $('Extract Referenzfelder').all().map(x => x.json);\n// 1) alle Packungen einsammeln, 2) je MA-Nummer den vollstaendigsten Datensatz behalten, 3) nach Produkt gruppieren\nconst score = p => (p.units_per_pack != null ? 1 : 0) + (p.amount_per_unit_value != null ? 1 : 0) + ((p.fill_volume_per_unit_ml != null || p.reconstituted_volume_per_unit_ml != null) ? 1 : 0) + (p.has_structured_packaging ? 0.5 : 0) + (p.concentration_value != null ? 0.25 : 0);\nconst best = new Map(); let notok = 0, nomatch = 0, dupPk = 0;\nfor (const r of ex) {\n  if (!r.ok) { notok++; continue; }\n  if (!r.procedure_match) { nomatch++; continue; }\n  for (const p of (r.packages || [])) {\n    const mas = (p.ma_numbers || []).filter(m => String(m).indexOf('EU/1/') === 0);\n    for (const ma of mas) {\n      const cand = { ma, p, r, s: score(p) };\n      const cur = best.get(ma);\n      if (!cur) best.set(ma, cand); else { dupPk++; if (cand.s > cur.s) best.set(ma, cand); }\n    }\n  }\n}\nconst byProduct = new Map();\nfor (const [ma, c] of best) {\n  const key = c.r.pms_id;\n  if (!byProduct.has(key)) byProduct.set(key, { procedure_number: c.r.procedure_number, pms_product_id: c.r.pms_id, brand: c.r.brand, product_name: c.r.product_name, mah: c.r.mah, ma_base_number: c.r.ma_base_number,\n    is_powder: c.r.is_powder, strength_pattern: c.r.strength_pattern, dose_form_text: c.r.dose_form_text, route_text: c.r.route_text, strength_text: c.r.strength_text, packages: [] });\n  const p = c.p;\n  byProduct.get(key).packages.push({ ma_number: ma, pms_package_id: p.package_id, description: p.description, units_per_pack: p.units_per_pack, unit_type: p.unit_type,\n    amount_per_unit_value: p.amount_per_unit_value, amount_per_unit_unit: p.amount_per_unit_unit, fill_volume_per_unit_ml: p.fill_volume_per_unit_ml,\n    reconstituted_volume_per_unit_ml: p.reconstituted_volume_per_unit_ml, total_amount_value: p.total_amount_value, total_volume_ml: p.total_volume_ml,\n    total_volume_basis: p.total_volume_basis, concentration_value: p.concentration_value, needs_review: p.needs_review, review_note: p.review_note, field_sources: p.field_sources });\n}\nconst products = [...byProduct.values()];\nconst run_id = $('Parameter').first().json.run_id;\nreturn [{ json: { p_run_id: run_id, p_payload: { products }, stats: { extracted: ex.length, not_ok: notok, procedure_mismatch: nomatch, duplicate_packages_collapsed: dupPk, products: products.length, packages: best.size } } }];\n"
    },
    position: [2120, 300]
  },
  output: [{ p_run_id: 'pms-import-2026-09-22', p_payload: { products: [] }, stats: {} }]
});

const upsertRpc = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.4,
  config: {
    name: 'Upsert canonical (Supabase)',
    parameters: {
      method: 'POST',
      url: SUPA + 'canonical_upsert_pms_extract',
      authentication: 'predefinedCredentialType',
      nodeCredentialType: 'supabaseApi',
      sendHeaders: true,
      headerParameters: { parameters: [{ name: 'Content-Type', value: 'application/json' }] },
      sendBody: true,
      specifyBody: 'json',
      jsonBody: expr('{{ JSON.stringify({ p_run_id: $json.p_run_id, p_payload: $json.p_payload }) }}'),
      options: { response: { response: { responseFormat: 'json' } }, timeout: 600000 }
    },
    onError: 'continueRegularOutput',
    executeOnce: true,
    position: [2340, 300]
  },
  output: [{ products_matched: 0, presentations: 0 }]
});

const summary = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Summary',
    parameters: {
      mode: 'runOnceForAllItems',
      jsCode: "const cands = $('Suchname').all().map(x => x.json);\nconst filt = $('MPD-IDs filtern').all().map(x => x.json);\nconst ex = $('Extract Referenzfelder').all().map(x => x.json);\nconst payload = $('Upsert-Payload bauen').first().json;\nconst matchedIds = new Set(filt.map(f => f.reg_product_id));\nconst search_no_hit = cands.filter(c => !matchedIds.has(c.reg_product_id)).map(c => c.product_name);\nconst okIds = new Set(ex.filter(r => r.ok && r.procedure_match).map(r => r.candidate.reg_product_id));\nconst procedure_mismatch_products = cands.filter(c => matchedIds.has(c.reg_product_id) && !okIds.has(c.reg_product_id)).map(c => c.product_name);\nconst fetch_errors = ex.filter(r => !r.ok).map(r => ({ product: r.label, pms_id: r.pms_id, error: r.error }));\nconst review = []; const seen = new Set();\nfor (const pr of (payload.p_payload.products || [])) for (const p of pr.packages) { if (p.needs_review && !seen.has(p.ma_number)) { seen.add(p.ma_number); review.push({ product: pr.brand, ma: p.ma_number, note: p.review_note }); } }\nconst upsert = $input.first().json;\nreturn [{ json: { run_id: $('Parameter').first().json.run_id, candidates: cands.length, search_no_hit, fetched: ex.length, fetch_errors, procedure_mismatch_products, needs_review_count: review.length, needs_review: review.slice(0, 50), payload_stats: payload.stats, upsert_result: upsert } }];\n"
    },
    position: [2560, 300]
  },
  output: [{ run_id: 'pms-import-2026-09-22', candidates: 10 }]
});

const note = sticky(
  '## EMA PMS -> canonical Import (selbst-fortsetzend)\n\nJeder Lauf holt die naechsten 100 Kandidaten, die im heutigen run_id noch nicht importiert sind. Flow so oft starten, bis Summary.candidates == 0 (Dauer-Nichttreffer wie zurueckgezogene Antraege bleiben in search_no_hit).\n\n1. Kandidaten aus canonical.v_pms_import_candidates (Scope, nicht withdrawn, keine ATMP, nur Humanarzneimittel EMEA/H/..., Status AUTHORISED/OPINION) -> Suchname\n2. PMS Namenssuche -> 6000...-IDs + Markenname-Prefix\n3. $everything -> Extraktion (Primaereinheit IU/mg, Komponenten summiert, Units/Volumen aus containedItemQuantity + description)\n4. Staging (pms_stage) -> Dedupe je MA-Nummer -> Upsert nach canonical (Verfahrensnummer-Match, normalisiert ohne Suffix /0000; manual_locked: Luecken auffuellen, nie ueberschreiben)\n\nDauer-Nichttreffer: canonical.pms_import_skip. Credentials: EMA PMS Public API (OAuth2) an beiden PMS-Nodes; Supabase account FDA EMA an den drei Supabase-Nodes.',
  [params, candidates, searchNameClean, searchName, filterIds, fetchEverything, extract, stagePayload, stageRpc, buildUpsert, upsertRpc, summary],
  { color: 5 }
);

export default workflow('ema-pms-canonical-import', 'EMA PMS → canonical Import')
  .add(startTrigger)
  .to(params)
  .to(candidates)
  .to(searchNameClean)
  .to(searchName)
  .to(filterIds)
  .to(fetchEverything)
  .to(extract)
  .to(stagePayload)
  .to(stageRpc)
  .to(buildUpsert)
  .to(upsertRpc)
  .to(summary)
  .add(note);
