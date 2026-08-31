import React from "react";

let _hlCounter = 0;

const NOTE_CHORD_RE = /\b(?:DO|RE|MI|FA|SOL|LA|SI)(?:[#b]|[-/][A-Z0-9#b]+|\d+|maj|min|m|dim|aug|sus|add|7|9|11|13)*\b/gi;
const CHORD_RE = /(?<![A-Za-zÀ-ÿ])(?:[A-G](?:#|b)?(?:maj|min|m|dim|aug|sus|add)?\d*(?:\/[A-G](?:#|b)?\d*)?)(?![A-Za-zÀ-ÿ])/gi;
const APOSTROPHE_RE = /[’‘`]/g;
const DECORATIVE_NUMBER_RE = /~\s*\d+\s*~/g;
const NEWLINE_MARKER_RE = /\u23CE/g;  // ⏎ marker from backend

export function sanitizeSnippetText(value) {
  if (value == null) return "";
  let s = String(value);
  
  // 0. Rimuovi marker di ritorno a capo estratto dal PDF
  s = s.replace(NEWLINE_MARKER_RE, " ");
  
  // 1. normalizza spazi
  s = s.replace(/\s+/g, " ").trim();
  
  // 2. rimuovi accordi musicali (DO, RE, MI, FA#, etc)
  s = s.replace(NOTE_CHORD_RE, " ");
  s = s.replace(CHORD_RE, " ");
  
  // 3. comprime sequenze rumorose di punteggiatura OCR (., ., ., -> , )
  s = s.replace(/(?:[.,]\s*){2,}/g, ", ");
  
  // 4. pulizia base di ", , ,"
  s = s.replace(/(?:,\s*){2,}/g, ", ");
  
  // 5. normalizza spazi multipli di nuovo dopo tutte le pulizie
  s = s.replace(/\s+/g, " ").trim();
  
  return s;
}

export function sanitizeSearchText(value) {
  if (value == null) return "";

  let text = String(value)
    .replace(APOSTROPHE_RE, "'")
    .replace(/\u00a0/g, " ")
    .replace(/\r/g, " ")
    .replace(/\n/g, " ");

  text = text.replace(DECORATIVE_NUMBER_RE, " ");
  text = text.replace(/[œŒ˙…]+/g, " ");
  text = text.replace(NOTE_CHORD_RE, " ");
  text = text.replace(CHORD_RE, " ");
  text = text.replace(/(?<=[A-Za-zÀ-ÿ])\s*[-–—]\s*(?=[A-Za-zÀ-ÿ])/g, "");
  text = text.replace(/[^A-Za-z0-9À-ÿ\s'.]+/g, " ");
  text = text.replace(/(?<=[a-zà-ÿ])(?=[A-ZÀ-Ý][a-zà-ÿ])/g, " ");
  text = text.replace(/\s+/g, " ");
  return text.trim();
}

// Remove chord/note tokens but otherwise preserve the original text content
export function stripChords(value) {
  if (value == null) return "";
  let text = String(value)
    .replace(APOSTROPHE_RE, "'")
    .replace(/\u00a0/g, " ")
    .replace(/\r/g, " ")
    .replace(/\n/g, " ");
  text = text.replace(NOTE_CHORD_RE, " ");
  text = text.replace(CHORD_RE, " ");
  text = text.replace(/\s+/g, " ");
  return text.trim();
}

/**
 * Normalizza query di ricerca per essere "fuzzy-proof":
 * - Capitalizza prima lettera
 * - Normalizza apostrofi
 * - Tollerante a punteggiatura mancante
 * Esempio: "padre se nei pensieri miei" -> "Padre se nei pensieri miei"
 */
export function normalizeSearchQuery(value) {
  if (value == null) return "";
  let q = String(value).trim();
  if (!q) return "";
  
  // Normalizza apostrofi
  q = q.replace(APOSTROPHE_RE, "'");
  
  // Capitalizza prima lettera (per matching case-insensitive nel backend)
  q = q.charAt(0).toUpperCase() + q.slice(1);
  
  // Rimuovi punteggiatura errata a inizio/fine
  q = q.replace(/^[^\w\s]+/, "").replace(/[^\w\s]+$/, "");
  
  // Normalizza spazi multipli
  q = q.replace(/\s+/g, " ");
  
  return q.trim();
}

// CLIENT-SIDE: normalizzazione usata per inviare query al backend e per highlight
export function normalizeForMatching(value) {
  if (value == null) return "";
  let s = String(value).trim();
  if (!s) return "";

  // Normalize various apostrophes to standard '
  s = s.replace(APOSTROPHE_RE, "'");
  // Replace non-breaking and weird spaces
  s = s.replace(/\u00a0/g, " ").replace(/\r/g, " ").replace(/\n/g, " ");
  // Unicode normalization and strip combining diacritics (é -> e)
  s = s.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  // Hyphens/dashes/underscores -> space
  s = s.replace(/[-–—_]+/g, " ");
  // Remove other punctuation but keep apostrophe and alnum
  s = s.replace(/[^A-Za-z0-9\s']/g, " ");
  // collapse spaces and lowercase
  s = s.replace(/\s+/g, " ").trim().toLowerCase();
  return s;
}

// Build normalized char sequence and a map from normalized index -> original index
function _buildNormalizedMap(text) {
  const normChars = [];
  const mapNormToOrig = [];
  for (let i = 0; i < text.length; i++) {
    let ch = text[i];
    // normalize char
    let norm = ch.normalize ? ch.normalize("NFKD") : ch;
    norm = norm.replace(/[\u0300-\u036f]/g, "");
    if (APOSTROPHE_RE.test(norm)) norm = "'";
    // keep letters, numbers, apostrophe or space as-is; else convert to space
    if (/^[A-Za-z0-9']$/.test(norm)) {
      normChars.push(norm.toLowerCase());
      mapNormToOrig.push(i);
    } else if (/^\s$/.test(norm)) {
      // preserve single space
      // avoid pushing multiple consecutive spaces here; we'll collapse later
      const last = normChars.length ? normChars[normChars.length - 1] : null;
      if (last !== ' ') {
        normChars.push(' ');
        mapNormToOrig.push(i);
      }
    } else {
      // other chars -> treat as separator (space)
      const last = normChars.length ? normChars[normChars.length - 1] : null;
      if (last !== ' ') {
        normChars.push(' ');
        mapNormToOrig.push(i);
      }
    }
  }
  // collapse leading/trailing spaces
  // But keep mapping aligned by trimming both arrays
  // trim start
  while (normChars.length && normChars[0] === ' ') { normChars.shift(); mapNormToOrig.shift(); }
  // trim end
  while (normChars.length && normChars[normChars.length - 1] === ' ') { normChars.pop(); mapNormToOrig.pop(); }
  const normalized = normChars.join('').replace(/\s+/g, ' ');
  return { normalized, mapNormToOrig };
}

function _escapeRegExp(s) { return s.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&"); }

function _buildApostropheTolerantRegex(s) {
  if (!s) return null;
  // split on runs of apostrophes/spaces and rejoin with tolerant group
  const parts = s.split(/[\s']+/).filter(Boolean);
  if (!parts.length) return null;
  const escaped = parts.map(p => _escapeRegExp(p));
  const joined = escaped.join("(?:\\s*'\\s*|\\s+)");
  return new RegExp(joined, "i");
}

/**
 * Highlighting utility that mirrors backend normalization: finds a match in the
 * original text using accent/apostrophe-insensitive search and returns React
 * nodes (array) with the matched segment wrapped in <mark> (className options).
 *
 * Usage: highlightText(text, q, { defaultMarkClass, chordMarkClass })
 */
export function highlightText(text, q, options = {}) {
  if (!text || !q) return text;
  const { defaultMarkClass = 'hl', chordMarkClass = null } = options;

  // special-case chord notation like [Cmaj]
  const chordMatch = String(q).match(/^\[(.+)\]$/);
  const rawNeedle = chordMatch ? chordMatch[1] : String(q);

  const needleNorm = normalizeForMatching(rawNeedle);
  if (!needleNorm) return text;

  // try normalized search with mapping
  const { normalized: txtNorm, mapNormToOrig } = _buildNormalizedMap(text);
  const idx = txtNorm.indexOf(needleNorm);
  if (idx >= 0) {
    // map normalized idx range back to original indices
    const startOrig = mapNormToOrig[idx] || 0;
    const endNormIdx = idx + needleNorm.length - 1;
    const endOrig = (mapNormToOrig[endNormIdx] !== undefined) ? (mapNormToOrig[endNormIdx] + 1) : (startOrig + needleNorm.length);
    const before = text.slice(0, startOrig);
    const match = text.slice(startOrig, endOrig);
    const after = text.slice(endOrig);
    const markCls = chordMatch && chordMarkClass ? chordMarkClass : defaultMarkClass;
    return [<span key={'b-'+(_hlCounter++)}>{before}</span>, <mark key={'m-'+(_hlCounter++)} className={markCls}>{match}</mark>, <span key={'a-'+(_hlCounter++)}>{after}</span>];
  }

  // Try apostrophe-agnostic matching: remove apostrophes from normalized text and needle
  try {
    const txtNormNoApos = txtNorm.replace(/'/g, '');
    const needleNoApos = needleNorm.replace(/'/g, '');
    if (needleNoApos && txtNormNoApos.indexOf(needleNoApos) >= 0) {
      const idxNo = txtNormNoApos.indexOf(needleNoApos);
      // build mapping from noApos index -> original txtNorm index
      const mapNoAposToNorm = [];
      for (let i = 0; i < txtNorm.length; i++) {
        if (txtNorm[i] !== "'") mapNoAposToNorm.push(i);
      }
      const normStartIdx = mapNoAposToNorm[idxNo];
      const normEndIdx = mapNoAposToNorm[idxNo + needleNoApos.length - 1];
      const startOrig = mapNormToOrig[normStartIdx] || 0;
      const endOrig = (mapNormToOrig[normEndIdx] !== undefined) ? (mapNormToOrig[normEndIdx] + 1) : (startOrig + needleNoApos.length);
      const before = text.slice(0, startOrig);
      const match = text.slice(startOrig, endOrig);
      const after = text.slice(endOrig);
      const markCls = chordMatch && chordMarkClass ? chordMarkClass : defaultMarkClass;
      return [<span key={'b3-'+(_hlCounter++)}>{before}</span>, <mark key={'m3-'+(_hlCounter++)} className={markCls}>{match}</mark>, <span key={'a3-'+(_hlCounter++)}>{after}</span>];
    }
  } catch (err) {
    // fall through to regex fallback
  }

  // fallback: try apostrophe-tolerant regex on original text
  const tolerant = _buildApostropheTolerantRegex(rawNeedle);
  if (tolerant) {
    const m = text.match(tolerant);
    if (m && m.index !== undefined) {
      const s = m.index;
      const e = s + m[0].length;
      const before = text.slice(0, s);
      const match = text.slice(s, e);
      const after = text.slice(e);
      const markCls = chordMatch && chordMarkClass ? chordMarkClass : defaultMarkClass;
      return [<span key={'b2-'+(_hlCounter++)}>{before}</span>, <mark key={'m2-'+(_hlCounter++)} className={markCls}>{match}</mark>, <span key={'a2-'+(_hlCounter++)}>{after}</span>];
    }
  }

  // no match: return original text
  return text;
}
