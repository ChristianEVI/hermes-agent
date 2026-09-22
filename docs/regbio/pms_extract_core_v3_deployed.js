// ---- PMS $everything -> Referenzfelder (core, shared between local test and n8n node) ----
// Einheiten-Codes (SPOR-Liste 100000110633 + UCUM-Varianten). Familien: mass (mg/g/mcg -> mg) und units (IU/U/MIU/MU, Label bleibt erhalten)
const UNIT = { '100000110655':'mg','MG':'mg','MILLIGRAM':'mg','100000110662':'ml','ML':'ml','MILLILITRE':'ml',
  '100000110633':'mg','IU':'IU','100000110671':'IU','100000110648':'IU','INTERNATIONAL UNIT':'IU','1[IU]':'IU','[IU]':'IU','MA[IU]':'MIU','MIU':'MIU',
  '100000110756':'U','U':'U','UNIT':'U','UNITS':'U','[U]':'U','MA[U]':'MU','MU':'MU',
  'MCG':'mcg','UG':'mcg','MICROGRAM':'mcg','100000110656':'mcg','100000110660':'mcg','G':'g','GRAM':'g','100000110654':'g',
  '100000110665':'MBq','MABQ':'MBq',
  '200000002150':'pre-filled syringe','200000002158':'vial','200000002151':'pre-filled pen','200000002135':'pen','200000002114':'cartridge','200000002121':'cartridge','200000002164':'pre-filled pen' };
const WORDNUM = { one:1, two:2, three:3, four:4, five:5, six:6, seven:7, eight:8, nine:9, ten:10, twelve:12, twenty:20 };
const MASS = { mg: 1, g: 1000, mcg: 0.001 };                 // Faktor -> mg
const UNITS = { IU: 1, U: 1, MIU: 1000000, MU: 1000000 };     // Faktor -> Einzel-Einheit (nur fuer Umrechnung zwischen Labels)
const familyOf = u => MASS[u] != null ? 'mass' : (UNITS[u] != null ? 'units' : null);
const AMOUNT_UNITS = ['mg','IU','mcg','g','U','MU','MIU'];
const NAMEPART = { '220000000002':'brand','220000000004':'strength_text','220000000005':'dose_form_text' };
const unitOf = c => (c && UNIT[c]) ? UNIT[c] : (c || null);
const num = x => (x == null || x === '') ? null : Number(x);
// Text-Einheit (description / Staerke-Text) -> kanonisches Label
const TEXTUNIT = [[/^(mg|milligrams?)$/, 'mg'], [/^(µg|μg|ug|mcg|micrograms?)$/, 'mcg'], [/^(g|grams?)$/, 'g'],
  [/^(million iu|miu|mio\.? iu|m iu)$/, 'MIU'], [/^(million units?|mu|mio\.? u|m u)$/, 'MU'], [/^(iu|i\.u\.|international units?)$/, 'IU'], [/^(u|units?)$/, 'U']];
const textUnit = t => { const s = String(t || '').trim().toLowerCase(); for (const p of TEXTUNIT) { if (p[0].test(s)) return p[1]; } return null; };
const UNITRX = '(mg|milligrams?|µg|μg|ug|mcg|micrograms?|million iu|million units?|m iu|m u|miu|mu|iu|i\\.u\\.|international units?|units?|u|g)';
// Wert+Einheit in das Primaerlabel umrechnen (mg | IU | U | MU | MIU); null wenn die Familie nicht passt
function convTo(value, unit, label) {
  if (value == null || !unit || !label) return null;
  if (label === 'mg') return MASS[unit] != null ? +(value * MASS[unit]).toFixed(6) : null;
  if (UNITS[unit] == null || UNITS[label] == null) return null;
  return +(value * UNITS[unit] / UNITS[label]).toFixed(6);
}
const parseNum = t => num(String(t).replace(',', '.'));

function parseDescription(d) {
  const out = { units_per_pack: null, fill_volume_ml: null, solvent_ml: null, amount: null, conc: null };
  if (!d) return out;
  const s = String(d).replace(/\s+/g, ' ').trim();
  const lower = s.toLowerCase();
  const toN = t => { const w = String(t).toLowerCase(); return WORDNUM[w] != null ? WORDNUM[w] : num(w); };
  const CONT = '(?:pre-filled|prefilled|vial|pen|cartridge|syringe|bottle|ampoule|bag|kit)';
  let m;
  if ((m = lower.match(/package_size:\s*(\d+)/))) out.units_per_pack = num(m[1]);
  else if ((m = lower.match(/pack size of (\d+)/))) out.units_per_pack = num(m[1]);
  else if ((m = lower.match(/pack of (\d+)/))) out.units_per_pack = num(m[1]);
  else if ((m = lower.match(new RegExp('^(\\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty)\\s+' + CONT)))) out.units_per_pack = toN(m[1]);
  else if ((m = lower.match(new RegExp('containing\\s+(\\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|twenty)\\s+' + CONT)))) out.units_per_pack = toN(m[1]);
  else if ((m = lower.match(/(\d+)\s*x\s*(\d+(?:[.,]\d+)?)\s*ml/))) out.units_per_pack = num(m[1]);
  else if (/\bin a (vial|syringe|pen|cartridge|bottle)\b/.test(lower) || /^vial\b/.test(lower) || /^(a |1 )?(pre-filled )?(vial|syringe|pen|cartridge)\b/.test(lower)) out.units_per_pack = 1;
  // Loesungsmittel (Pulver): "solvent: 1 ml", "solvent 2 ml", "solvent: 1.0 ml (1000 IU/ml)"
  if ((m = lower.match(/solvent:?\s*([\d.,]+)\s*ml/))) out.solvent_ml = parseNum(m[1]);
  // Fuellvolumen (Loesung); "content:solvent: 1 ml" greift hier bewusst nicht
  if ((m = lower.match(/(\d+)\s*x\s*([\d.,]+)\s*ml/))) out.fill_volume_ml = parseNum(m[2]);
  else {
    const vol = [
      /content:\s*([\d.,]+)\s*ml/, /contains\s*([\d.,]+)\s*ml/, /containing\s*([\d.,]+)\s*ml/, /\bof\s*([\d.,]+)\s*ml/,
      /([\d.,]+)\s*ml\s*per\s*(?:pen|vial|syringe|cartridge)/, /^\s*([\d.,]+)\s*ml\b/, /([\d.,]+)\s*ml\s*(?:solution|suspension|concentrate|emulsion)/
    ];
    for (const rx of vol) { if ((m = lower.match(rx))) { out.fill_volume_ml = parseNum(m[1]); break; } }
  }
  // Menge aus Text: "containing 25 mg", "powder: 25 mg", "content: 150 mg" (nicht "content:500 U/ml")
  if ((m = lower.match(new RegExp('(?:containing|powder:?|content:?)\\s*([\\d.,]+)\\s*' + UNITRX + '\\b(?!\\s*/)')))) out.amount = { value: parseNum(m[1]), unit: textUnit(m[2]) };
  // Konzentration in Klammern: "(3.5 mg/ml)", "(10000 IU/ml)", "(24 million IU/ml)", "(40 µg/ml)"
  if ((m = lower.match(new RegExp('\\(\\s*([\\d.,]+)\\s*' + UNITRX + '\\s*/\\s*ml\\s*\\)')))) out.conc = { value: parseNum(m[1]), unit: textUnit(m[2]) };
  return out;
}
// Konzentration aus dem Staerke-Text des Produktnamens ("100 UNITS/ML", "10 MG/ML")
function parseConcText(t) {
  const m = String(t || '').toLowerCase().match(new RegExp('([\\d.,]+)\\s*' + UNITRX + '\\s*/\\s*ml'));
  return m ? { value: parseNum(m[1]), unit: textUnit(m[2]) } : null;
}

function extractBundle(b, meta) {
  meta = meta || {};
  if (!b || !b.entry) return { label: meta.label, pms_id: meta.pms_id, ok: false, error: (b && b.error && b.error.message) || (b && b.error) || 'kein Bundle' };
  const entries = b.entry.map(e => e.resource || {});
  const byType = t => entries.filter(r => r.resourceType === t);
  const counts = {}; for (const r of entries) counts[r.resourceType] = (counts[r.resourceType] || 0) + 1;

  const mpd = byType('MedicinalProductDefinition')[0] || {};
  const nameObj = (mpd.name || [])[0] || {};
  const parts = {};
  for (const p of (nameObj.part || [])) { const code = (((p.type || {}).coding || [])[0] || {}).code; if (NAMEPART[code]) parts[NAMEPART[code]] = p.part; }

  const regs = byType('RegulatedAuthorization');
  const maOf = r => (r.identifier || []).filter(x => /MarketingAuthorizationNumber/.test(x.system || '')).map(x => x.value);
  const holderReg = regs.find(r => r.holder) || {};
  const mpdRegs = regs.filter(r => (r.subject || []).some(s => /^MedicinalProductDefinition\//.test(s.reference || '')));
  const baseReg = mpdRegs.find(r => maOf(r).some(v => /^EU\/1\//.test(v))) || mpdRegs[0] || {};
  // Verfahrensnummer normalisieren: Whitespace, Grossschreibung, Variations-Suffix "/0000" (z. B. EMEA/H/C/006152/0000)
  const normProc = v => v ? String(v).trim().toUpperCase().replace(/\/[0-9]{4}$/, '') : null;
  const dose_form = parts.dose_form_text || '';
  const is_powder = /powder/i.test(dose_form);
  const is_oral_solid = /tablet|capsule/i.test(dose_form);

  // Ingredients: strength sits under substance.strength (FHIR R5); alle Strength-Eintraege, je mit Ziel-Ressource (MID/APD)
  const ingredients = [];
  for (const ing of byType('Ingredient')) {
    const forRefs = (ing.for || []).map(f => f.reference || '').filter(Boolean);
    const strengths = (ing.substance && ing.substance.strength) || ing.strength || [];
    const substance_code = ((((((ing.substance || {}).code || {}).concept || {}).coding || [])[0]) || {}).code || null;
    for (const s of (strengths.length ? strengths : [{}])) {
      const kind = s.presentationRatio ? 'presentationRatio' : (s.concentrationRatio ? 'concentrationRatio' : 'none');
      const r = s.presentationRatio || s.concentrationRatio || {};
      for (const ref of (forRefs.length ? forRefs : [''])) {
        ingredients.push({
          for: ref.split('/')[0] || null, for_id: ref.split('/')[1] || null, substance_code, strength_kind: kind,
          numerator_value: num((r.numerator || {}).value), numerator_unit: unitOf((r.numerator || {}).code),
          denominator_value: num((r.denominator || {}).value), denominator_unit: unitOf((r.denominator || {}).code),
          text: s.textPresentation || null
        });
      }
    }
  }
  // Primaerfamilie je Produkt: units (IU/U) wenn irgendein Verhaeltnis Einheiten liefert, sonst mass (mg/mcg/g -> mg). Keine Familien mischen.
  const anyUnits = ingredients.some(i => familyOf(i.numerator_unit) === 'units');
  const primaryFamily = anyUnits ? 'units' : (ingredients.some(i => familyOf(i.numerator_unit) === 'mass') ? 'mass' : null);
  const inPrimary = i => primaryFamily != null && familyOf(i.numerator_unit) === primaryFamily && i.numerator_value != null;
  const mids = ingredients.filter(i => i.for === 'ManufacturedItemDefinition' && inPrimary(i));
  const apds = ingredients.filter(i => i.for === 'AdministrableProductDefinition' && inPrimary(i));
  // Label: mg fuer Masse; bei Einheiten das Label der Fertigeinheit (U/IU/MU/MIU), sonst des APD, sonst IU
  const primaryLabel = primaryFamily === 'mass' ? 'mg' : (primaryFamily === 'units' ? (mids[0] ? mids[0].numerator_unit : (apds[0] ? apds[0].numerator_unit : 'IU')) : null);
  const normVal = i => convTo(i.numerator_value, i.numerator_unit, primaryLabel);
  const mixedUnitLabels = primaryFamily === 'units' && ingredients.some(i => inPrimary(i) && i.numerator_unit !== primaryLabel);
  // Fertigeinheiten aufloesen: 1 Eintrag -> Wert; verschiedene Wirkstoffe -> Summe (Kombination, pruefen);
  // gleicher Wirkstoff mit gleichen Werten -> Wert; gleicher Wirkstoff mit verschiedenen Werten -> Groessenvarianten, unklar
  function resolveMid(list) {
    if (!list.length) return { value: null, note: null };
    if (list.length === 1) return { value: normVal(list[0]), note: null };
    const subs = new Set(list.map(i => i.substance_code));
    const vals = list.map(normVal);
    if (subs.size === list.length) return { value: +(vals.reduce((a, v) => a + v, 0).toFixed(6)), note: 'Kombination: ' + list.length + ' Komponenten summiert, pruefen' };
    if (vals.every(v => v === vals[0])) return { value: vals[0], note: null };
    return { value: null, note: 'mehrere Staerken je Fertigeinheit (' + vals.join('/') + ' ' + primaryLabel + '), Zuordnung unklar' };
  }
  const midAll = resolveMid(mids);
  const apdSum = apds.length ? +(apds.reduce((a, i) => a + normVal(i), 0).toFixed(6)) : null;
  const apd = apds.length && apds.every(i => i.denominator_unit === apds[0].denominator_unit && i.denominator_value === apds[0].denominator_value) ? { numerator_value: apdSum, denominator_unit: apds[0].denominator_unit, denominator_value: apds[0].denominator_value } : (apds[0] ? { numerator_value: normVal(apds[0]), denominator_unit: apds[0].denominator_unit, denominator_value: apds[0].denominator_value } : null);
  const amount_unit = primaryLabel;
  let amount_mg = null, volume_ml = null, conc_mg_ml = null, strength_pattern = 'none';
  if (apd && apd.denominator_unit === 'ml') {
    const av = apd.numerator_value;
    if (apd.denominator_value === 1 && !(midAll.value != null && midAll.value === av)) { conc_mg_ml = av; strength_pattern = 'concentration_only'; }
    else { amount_mg = av; volume_ml = apd.denominator_value; conc_mg_ml = (volume_ml ? +(amount_mg / volume_ml).toFixed(4) : null); strength_pattern = 'amount_and_volume'; }
  }
  if (midAll.value != null && amount_mg == null) { amount_mg = midAll.value; strength_pattern = is_powder ? 'powder_amount' : (strength_pattern === 'none' ? 'amount_per_unit' : strength_pattern); }
  if (is_powder && strength_pattern === 'amount_and_volume') strength_pattern = 'powder_amount';
  // Konzentration aus dem Staerke-Text als Rueckfall (z. B. "100 UNITS/ML" bei Insulinen ohne Packungstext)
  const tc = parseConcText(parts.strength_text);
  const conc_text = tc ? convTo(tc.value, tc.unit, primaryLabel) : null;
  const secondary = ingredients.filter(i => !inPrimary(i) && AMOUNT_UNITS.includes(i.numerator_unit)).map(i => ({ for: i.for, value: i.numerator_value, unit: i.numerator_unit, per: i.denominator_value, per_unit: i.denominator_unit }));

  const containedMids = p => { const refs = []; (function walk(pk) { if (!pk) return; for (const ci of (pk.containedItem || [])) refs.push(String((((ci.item || {}).reference || {}).reference) || '')); for (const sub of (pk.packaging || [])) walk(sub); })(p.packaging); return refs.filter(x => /^ManufacturedItemDefinition\//.test(x)).map(x => x.split('/')[1]); };

  const packages = byType('PackagedProductDefinition').map(p => {
    const pk = p.packaging || null;
    const ciq = (p.containedItemQuantity || [])[0] || null;
    const pkRegs = regs.filter(r => (r.subject || []).some(s => (s.reference || '') === 'PackagedProductDefinition/' + p.id));
    const desc = parseDescription(p.description);
    const hard = [], soft = [];
    // Textangaben nur uebernehmen, wenn sie zur Primaerfamilie passen (mg-Angabe bei Insulin in Einheiten wird ignoriert)
    const dAmt = desc.amount ? convTo(desc.amount.value, desc.amount.unit, primaryLabel) : null;
    const dConc = desc.conc ? convTo(desc.conc.value, desc.conc.unit, primaryLabel) : null;
    const ciqVal = ciq ? num(ciq.value) : null;
    const units = (ciqVal != null && ciqVal > 0) ? ciqVal : desc.units_per_pack;
    const conc = dConc != null ? dConc : (conc_mg_ml != null ? conc_mg_ml : conc_text);
    const conc_src = dConc != null ? 'pms.description' : (conc_mg_ml != null ? 'pms.ingredient.administrable' : (conc_text != null ? 'pms.name.strength' : null));
    // Fertigeinheiten dieser Packung (ueber containedItem), sonst alle
    const ids = containedMids(p);
    const pm = ids.length ? mids.filter(i => ids.includes(i.for_id)) : mids;
    const midPkg = (ids.length && pm.length) ? resolveMid(pm) : midAll;
    // Fuellvolumen (Loesungen): Packungstext > APD-Verhaeltnis
    let fill = null, fill_src = null, recon = null, recon_src = null;
    if (!is_powder && !is_oral_solid) {
      if (desc.fill_volume_ml != null) { fill = desc.fill_volume_ml; fill_src = 'pms.description'; }
      else if (volume_ml != null) { fill = volume_ml; fill_src = 'pms.ingredient.administrable'; }
    }
    // Menge je Einheit: Packungstext > Volumen x Konzentration > Fertigeinheit > APD
    let amt = null, amt_src = null;
    if (dAmt != null) { amt = dAmt; amt_src = 'pms.description'; }
    else if (!is_powder && fill != null && conc != null) { amt = +(fill * conc).toFixed(4); amt_src = 'derived.volume*concentration'; }
    else if (midPkg.value != null) { amt = midPkg.value; amt_src = 'pms.ingredient.manufactured'; if (midPkg.note) hard.push(midPkg.note); }
    else if (amount_mg != null) { amt = amount_mg; amt_src = 'pms.ingredient.administrable'; }
    else if (midPkg.note) hard.push(midPkg.note);
    // Fuellvolumen aus Menge/Konzentration ableiten (Loesungen ohne Packungstext)
    if (!is_powder && !is_oral_solid && fill == null && amt != null && conc) { fill = +(amt / conc).toFixed(4); fill_src = 'derived.amount/concentration'; soft.push('Fuellvolumen aus Menge/Konzentration abgeleitet, SmPC pruefen'); }
    if (is_powder) {
      // Rekonstitution: Loesungsmittel der Packung > Volumenangabe im Text > APD-Verhaeltnis > Menge/Konzentration
      if (desc.solvent_ml != null) { recon = desc.solvent_ml; recon_src = 'pms.description.solvent'; }
      else if (desc.fill_volume_ml != null) { recon = desc.fill_volume_ml; recon_src = 'pms.description'; }
      else if (volume_ml != null) { recon = volume_ml; recon_src = 'pms.ingredient.administrable'; }
      else if (amt != null && conc) { recon = +(amt / conc).toFixed(4); recon_src = 'derived.amount/concentration'; }
      if (amt == null && recon != null && conc != null) { amt = +(recon * conc).toFixed(4); amt_src = 'derived.volume*concentration'; }
      if (recon != null) soft.push(recon_src === 'pms.description.solvent' ? 'Rekonstitutionsvolumen = Loesungsmittel der Packung, SmPC pruefen' : 'Rekonstitutionsvolumen abgeleitet, SmPC pruefen');
    }
    if (units == null) hard.push('units_per_pack unbekannt');
    if (amt == null) hard.push('Menge/Unit unbekannt');
    if (!is_oral_solid && fill == null && recon == null) hard.push('Volumen unbekannt');
    if (!amount_unit) hard.push('keine Mengeneinheit (mg/IU/U) erkannt');
    if (mixedUnitLabels) hard.push('U/IU/MU gemischt, pruefen');
    if (amount_unit === 'mg' && amt != null && amt > 5000) hard.push('Menge unplausibel (>5 g je Einheit), PMS-Einheit pruefen');
    const vol = fill != null ? fill : recon;
    const basis = fill != null ? (fill_src === 'derived.amount/concentration' ? 'fill_derived' : 'fill')
      : (recon != null ? ({ 'pms.description.solvent': 'reconstituted_solvent', 'pms.description': 'reconstituted_text', 'pms.ingredient.administrable': 'reconstituted_apd' }[recon_src] || 'reconstituted_derived')
      : (is_oral_solid ? 'not_applicable' : null));
    return {
      package_id: p.id,
      ma_numbers: [...new Set(pkRegs.flatMap(maOf))],
      description: p.description || null,
      units_per_pack: units, unit_type: ciq ? unitOf(ciq.code) : null,
      units_source: (ciqVal != null && ciqVal > 0) ? 'containedItemQuantity' : (desc.units_per_pack != null ? 'description' : null),
      amount_per_unit_value: amt, amount_per_unit_unit: amount_unit, fill_volume_per_unit_ml: fill,
      volume_source: fill != null ? fill_src : recon_src,
      reconstituted_volume_per_unit_ml: recon,
      total_amount_value: (units != null && amt != null) ? +(units * amt).toFixed(4) : null,
      total_volume_ml: (units != null && vol != null) ? +(units * vol).toFixed(4) : null,
      total_volume_basis: basis,
      concentration_value: conc != null ? conc : (amt != null && fill ? +(amt / fill).toFixed(4) : null),
      has_structured_packaging: !!pk,
      needs_review: hard.length > 0,
      review_note: hard.concat(soft).join('; ') || null,
      field_sources: { units: (ciqVal != null && ciqVal > 0) ? 'pms.containedItemQuantity' : (desc.units_per_pack != null ? 'pms.description' : null),
                       amount: amt_src, volume: fill != null ? fill_src : recon_src, concentration: conc_src }
    };
  });

  return {
    label: meta.label, pms_id: meta.pms_id, ok: true,
    product_name: nameObj.productName || null, brand: parts.brand || null,
    strength_text: parts.strength_text || null, dose_form_text: parts.dose_form_text || null,
    is_powder: is_powder,
    mah: (holderReg.holder || {}).display || null,
    ma_base_number: (maOf(baseReg)[0]) || null,
    procedure_number: normProc((mpdRegs.concat(regs).map(r => (((r.case || {}).identifier) || {}).value).find(v => v)) || null),
    strength_pattern, amount_unit: amount_unit, amount_per_unit_value: amount_mg, fill_volume_per_unit_ml: volume_ml, concentration_value: conc_mg_ml, secondary_strengths: secondary,
    route_text: (function(){ const a = byType('AdministrableProductDefinition')[0] || {}; const r = ((a.routeOfAdministration||[])[0]||{}).code; return r ? (((r.coding||[])[0]||{}).code || null) : null; })(),
    packages, ingredients, resource_counts: counts
  };
}
module.exports = { extractBundle };
