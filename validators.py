/*************************************************************************************
 * PUMA LISTING GENERATION SCRIPT — CORRECTED VERSION
 * -----------------------------------------------------------------------------------
 * Structure (per requirement #6):
 *   SECTION A: INPUT PROCESSING
 *     - populateSizeData()
 *     - populateColorDataFromColorExport()
 *     - populateStyleDataFromStyleExport()
 *     - validateInputSheet()               [NEW]
 *     - resolveTitleAndDescription()       [NEW - req #1]
 *     - resolveSizeAndSkipFlags()          [NEW - req #2 & #3]
 *     - resolveImageURL()                  [NEW - req #4]
 *
 *   SECTION B: OUTPUT GENERATION
 *     - runInputProcessing()   -> entry point for Section A
 *     - runOutputGeneration()  -> entry point for Section B (old myFunction logic)
 *     - main()                 -> orchestrates both, in order
 *
 * Each requirement below is tagged with a comment block referencing the request item.
 *************************************************************************************/

/* =====================================================================================
 * ENTRY POINT
 * ===================================================================================== */
function main() {
  runInputProcessing();
  runOutputGeneration();
}

/* =====================================================================================
 * SECTION A: INPUT PROCESSING
 * =====================================================================================
 * Everything that prepares/cleans the "Input" sheet lives here. Output generation
 * (Section B) should never need to re-derive raw export data — it only reads the
 * already-resolved columns this section writes.
 * ===================================================================================== */

function runInputProcessing() {
  populateSizeData();
  populateColorDataFromColorExport();
  populateStyleDataFromStyleExport();
  validateInputSheet();                 // NEW: basic sanity checks before proceeding
  resolveTitleAndDescriptionForSheet();  // NEW: requirement #1
  resolveSizeAndSkipFlagsForSheet();     // NEW: requirement #2 / #3
  resolveImageURLsForSheet();            // NEW: requirement #4 (moved off Output, now Input-side)
}

/* -------------------------------------------------------------------------------------
 * REQUIREMENT #1 — Title & Description fallback: English -> English (UK)
 * -------------------------------------------------------------------------------------
 * Assumes the "Style Export" sheet contains BOTH:
 *   "Regional Display Name (English)"      / "Regional Display Name (English (UK))"
 *   "Long Description (English)"           / "Long Description (English (UK))"
 *   "Short Description (English)"          / "Short Description (English (UK))"
 * If your export uses different header text, update the STYLE_COL_PAIRS map below.
 * ------------------------------------------------------------------------------------- */

// Columns in the "Input" sheet that hold the RESOLVED (fallback-applied) values.
// (Re-uses the same input columns the rest of the script already expects:
//  2 = Regional Display Name, 24 = Short Description, 25 = Long Description)
const RESOLVED_TITLE_COL = 2;
const RESOLVED_SHORT_DESC_COL = 24;
const RESOLVED_LONG_DESC_COL = 25;

// Pairs of (English column header, English UK column header) to pull from "Style Export".
const STYLE_COL_PAIRS = [
  { primary: "Regional Display Name (English)", fallback: "Regional Display Name (English (UK))", inputCol: RESOLVED_TITLE_COL },
  { primary: "Short Description (English)",      fallback: "Short Description (English (UK))",      inputCol: RESOLVED_SHORT_DESC_COL },
  { primary: "Long Description (English)",       fallback: "Long Description (English (UK))",        inputCol: RESOLVED_LONG_DESC_COL }
];

function resolveTitleAndDescriptionForSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const inputSheet = ss.getSheetByName("Input");
  const styleSheet = ss.getSheetByName("Style Export");
  if (!inputSheet || !styleSheet) {
    throw new Error("Input sheet or Style Export sheet not found (resolveTitleAndDescriptionForSheet)");
  }

  const norm = v => (v ? v.toString().trim().toLowerCase() : "");
  const findIndex = (header, name) => header.findIndex(h => norm(h) === norm(name));

  const inputData = inputSheet.getDataRange().getValues();
  const inputHeader = inputData[0];
  const styleNoIdx = findIndex(inputHeader, "Style no.");
  if (styleNoIdx === -1) throw new Error("Style no. column not found in Input sheet");

  const styleData = styleSheet.getDataRange().getValues();
  const styleHeader = styleData.shift();
  const styleExportStyleNoIdx = findIndex(styleHeader, "Style no.");
  if (styleExportStyleNoIdx === -1) throw new Error("Style no. column not found in Style Export sheet");

  // Resolve column indices for each primary/fallback pair. Missing fallback columns
  // are tolerated (fallback logic simply won't trigger for that field).
  STYLE_COL_PAIRS.forEach(pair => {
    pair.primaryIdx = findIndex(styleHeader, pair.primary);
    pair.fallbackIdx = findIndex(styleHeader, pair.fallback);
  });

  const styleMap = {};
  styleData.forEach(row => {
    const key = norm(row[styleExportStyleNoIdx]);
    if (key) styleMap[key] = row;
  });

  for (let r = 1; r < inputData.length; r++) {
    const rawStyleNo = inputData[r][styleNoIdx];
    if (!rawStyleNo) continue;
    const lookupKey = norm(rawStyleNo.toString());
    const styleRow = styleMap[lookupKey];
    if (!styleRow) continue;

    STYLE_COL_PAIRS.forEach(pair => {
      let value = pair.primaryIdx !== -1 ? styleRow[pair.primaryIdx] : "";
      if ((value === "" || value === undefined || value === null) && pair.fallbackIdx !== -1) {
        value = styleRow[pair.fallbackIdx]; // fallback to English (UK)
      }
      inputData[r][pair.inputCol - 1] = value || "";
    });
  }

  inputSheet.getRange(1, 1, inputData.length, inputData[0].length).setValues(inputData);
  SpreadsheetApp.flush();
}

/* -------------------------------------------------------------------------------------
 * REQUIREMENT #2 & #3 — Size handling: dual-size skip, JPN fallback, no size-format crashes
 * -------------------------------------------------------------------------------------
 * Adds a "JPN Size" column to Input, and a "Skip Row" flag column used by output
 * generation to silently exclude rows instead of throwing errors.
 *
 * Rules implemented:
 *  - A SKU is "dual-size" if its resolved size string contains a slash format that is
 *    NOT one of the recognized combined sizes (S/M, M/L, L/XL) — e.g. "38/39" style
 *    dual-shoe sizing. Those rows are flagged to be skipped.
 *  - JPN size column is populated from the Size Export sheet if present.
 *  - For a given article (Style no.), if UK size is blank across all its child rows,
 *    JPN size is used as the fallback size instead, so the article isn't skipped
 *    entirely for lacking UK data.
 * ------------------------------------------------------------------------------------- */

const JPN_SIZE_COL = 37;      // New column in Input sheet dedicated to JPN size
const SKIP_ROW_COL = 38;      // New column: "1" = skip this row during output generation
const RESOLVED_SIZE_SOURCE_COL = 39; // New column: which source was used ("UK"/"JPN"/etc.) for traceability

function resolveSizeAndSkipFlagsForSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const inputSheet = ss.getSheetByName("Input");
  const sizeSheet = ss.getSheetByName("Size Export");
  if (!inputSheet) throw new Error("Input sheet not found (resolveSizeAndSkipFlagsForSheet)");

  const lastRow = inputSheet.getLastRow();
  if (lastRow < 2) return;

  // Pull JPN size from Size Export (if the column exists) and write into Input.
  if (sizeSheet) {
    const norm = v => (v ? v.toString().trim().toLowerCase() : "");
    const sizeData = sizeSheet.getDataRange().getValues();
    const header = sizeData.shift();
    const eanIdx = header.findIndex(h => norm(h) === "ean");
    const colorNoIdx = header.findIndex(h => norm(h) === "color no");
    const jpnIdx = header.findIndex(h => norm(h) === "print size code (jpn)");

    if (eanIdx !== -1 && jpnIdx !== -1) {
      // Map EAN -> JPN size for direct lookup against Input rows (Input col 16 = EAN/customSku source).
      const eanToJpn = {};
      sizeData.forEach(row => {
        const ean = row[eanIdx];
        if (ean) eanToJpn[norm(ean)] = row[jpnIdx] || "";
      });

      const eanColInInput = inputSheet.getRange(2, 16, lastRow - 1, 1).getValues(); // col P (EAN)
      const jpnOut = eanColInInput.map(r => [eanToJpn[norm(r[0])] || ""]);
      inputSheet.getRange(2, JPN_SIZE_COL, jpnOut.length, 1).setValues(jpnOut);
    } else {
      // No JPN column available upstream — leave blank, not an error.
      inputSheet.getRange(2, JPN_SIZE_COL, lastRow - 1, 1).setValue("");
    }
  }
  inputSheet.getRange(1, JPN_SIZE_COL).setValue("JPN Size");
  inputSheet.getRange(1, SKIP_ROW_COL).setValue("Skip Row");
  inputSheet.getRange(1, RESOLVED_SIZE_SOURCE_COL).setValue("Size Source Used");

  // --- Determine per-article whether UK size is present at all ---
  const data = inputSheet.getRange(2, 1, lastRow - 1, Math.max(JPN_SIZE_COL, 22)).getValues();
  // Column indices (0-based) relative to the range above: col V (22) = UK size (per populateSizeData mapping).
  const UK_SIZE_IDX = 21 - 1; // sheet col 21 -> index 20 within a 1-based getRange starting at col 1... see note below.

  // NOTE: populateSizeData() writes UK size into column V (22) as outRow[21] (0-indexed) -> sheet column 22.
  // Re-derive correctly against a full-width read to avoid off-by-one mistakes:
  const fullData = inputSheet.getRange(2, 1, lastRow - 1, RESOLVED_SIZE_SOURCE_COL).getValues();
  const styleNoColIdx = 0;      // Column A
  const ukSizeColIdx = 21;      // Column V (1-indexed 22 -> 0-indexed 21)
  const jpnSizeColIdx = JPN_SIZE_COL - 1;

  const styleHasUK = {};
  fullData.forEach(row => {
    const style = row[styleNoColIdx];
    const uk = row[ukSizeColIdx];
    if (!style) return;
    if (!styleHasUK[style]) styleHasUK[style] = false;
    if (uk !== "" && uk !== undefined && uk !== null) styleHasUK[style] = true;
  });

  // --- Recognized combined sizes that are NOT considered "dual size" duplicates ---
  const RECOGNIZED_COMBINED_SIZES = ["S/M", "M/L", "L/XL"];

  const skipFlags = [];
  const sizeSourceUsed = [];

  fullData.forEach(row => {
    const style = row[styleNoColIdx];
    const uk = row[ukSizeColIdx];
    const jpn = row[jpnSizeColIdx];

    let skip = "";
    let sourceUsed = "";

    const ukPresentForArticle = styleHasUK[style] === true;

    if (uk !== "" && uk !== undefined && uk !== null) {
      // UK size present on this row — check for dual-size pattern.
      const ukStr = uk.toString();
      const isRecognizedCombo = RECOGNIZED_COMBINED_SIZES.some(c => ukStr.indexOf(c) !== -1);
      const looksLikeDualSize = ukStr.indexOf("/") !== -1 && !isRecognizedCombo;

      if (looksLikeDualSize) {
        skip = "1"; // Requirement: identify & skip dual-size SKUs
        sourceUsed = "SKIPPED-DUAL";
      } else {
        sourceUsed = "UK";
      }
    } else if (!ukPresentForArticle && jpn !== "" && jpn !== undefined && jpn !== null) {
      // No UK size anywhere for this article -> fall back to JPN size.
      sourceUsed = "JPN-FALLBACK";
    } else if (ukPresentForArticle && (uk === "" || uk === undefined || uk === null)) {
      // UK exists for the article generally but not this particular row — and JPN
      // rows are skipped by default per requirement #2, since UK data does exist elsewhere.
      skip = "1";
      sourceUsed = "SKIPPED-JPN-DEFAULT";
    } else {
      // No UK size for the article and no JPN size either — nothing usable.
      skip = "1";
      sourceUsed = "SKIPPED-NO-SIZE-DATA";
    }

    skipFlags.push([skip]);
    sizeSourceUsed.push([sourceUsed]);
  });

  inputSheet.getRange(2, SKIP_ROW_COL, skipFlags.length, 1).setValues(skipFlags);
  inputSheet.getRange(2, RESOLVED_SIZE_SOURCE_COL, sizeSourceUsed.length, 1).setValues(sizeSourceUsed);

  SpreadsheetApp.flush();
}

/* -------------------------------------------------------------------------------------
 * Helper used by output generation to get the "effective" size string for a row,
 * honoring the JPN fallback resolved above. Replaces raw variation2() calls where size
 * text is actually needed downstream (sorting, mapping keys, display).
 * ------------------------------------------------------------------------------------- */
function getEffectiveSize(inputSheet, rowIndex) {
  const uk = inputSheet.getRange(rowIndex, 22).getValue();   // Column V
  const jpn = inputSheet.getRange(rowIndex, JPN_SIZE_COL).getValue();
  const sourceUsed = inputSheet.getRange(rowIndex, RESOLVED_SIZE_SOURCE_COL).getValue();

  if (sourceUsed === "JPN-FALLBACK") return jpn;
  return uk; // default: UK size (already validated as non-dual by resolveSizeAndSkipFlagsForSheet)
}

function isRowSkipped(inputSheet, rowIndex) {
  return inputSheet.getRange(rowIndex, SKIP_ROW_COL).getValue() === "1";
}

/* -------------------------------------------------------------------------------------
 * REQUIREMENT #4 — Tiered image fetching: Global -> SEA -> PHL -> IND
 * -------------------------------------------------------------------------------------
 * Replaces generatePumaImageURLs(). Skips "Coming Soon" placeholder images and moves
 * to the next region tier. Writes resolved image URLs directly into Input so output
 * generation doesn't need network calls at all.
 * ------------------------------------------------------------------------------------- */

const IMAGE_REGION_FND_CODES = ["SEA", "PHL", "IND"]; // Global is checked first via the base "global" path/no fnd param variant
const IMAGE_RESOLVED_COL = 40; // New column on Input sheet holding the final image URL(s)

function resolveImageURLsForSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const inputSheet = ss.getSheetByName("Input");
  if (!inputSheet) throw new Error("Input sheet not found (resolveImageURLsForSheet)");

  const lastRow = inputSheet.getLastRow();
  if (lastRow < 2) return;

  inputSheet.getRange(1, IMAGE_RESOLVED_COL).setValue("Resolved Image URL");

  const BASE = "https://images.puma.com/image/upload/f_auto,q_auto,b_rgb:ffffff,w_1000,h_1000/global/";
  const SUFFIX_TEMPLATE = "/fnd/{REGION}/fmt/jpg/";

  const data = inputSheet.getRange(2, 1, lastRow - 1, 14).getValues(); // need col I (colorNo, idx8) and N (division, idx13)
  const results = [];

  for (let i = 0; i < data.length; i++) {
    const colorNoRaw = data[i][8];   // Column I
    const division = data[i][13];    // Column N
    const colorNo = colorNoRaw ? colorNoRaw.toString().trim().toUpperCase() : "";

    if (!colorNo || !division) {
      results.push([""]);
      continue;
    }

    const colorPath = colorNo.replace(/_/g, "/") + "/";
    let imageCodes = [];
    if (division === "Accessories" || division === "Footwear") {
      imageCodes = ["sv01", "sv02", "sv03", "sv04", "bv", "mod01", "mod02", "mod03"];
    } else if (division === "Apparel") {
      imageCodes = ["bv", "dt01", "mod01", "mod02", "mod03", "mod04", "mod05"];
    }

    const resolvedUrl = findFirstValidImageAcrossRegions(BASE, colorPath, imageCodes, SUFFIX_TEMPLATE);
    results.push([resolvedUrl || ""]);
  }

  inputSheet.getRange(2, IMAGE_RESOLVED_COL, results.length, 1).setValues(results);
  SpreadsheetApp.flush();
}

/**
 * Checks Global first, then SEA, PHL, IND in order. Returns the first valid,
 * non-"Coming Soon" image URL found, or "" if none exist in any region.
 */
function findFirstValidImageAcrossRegions(base, colorPath, imageCodes, suffixTemplate) {
  // Tier 1: Global (no /fnd/REGION/ segment — uses the plain "/fmt/jpg/" suffix)
  const globalSuffix = "/fmt/jpg/";
  for (const code of imageCodes) {
    const url = base + colorPath + code + globalSuffix;
    const status = checkImageStatus(url);
    if (status === "VALID") return url;
    // status === "COMING_SOON" or "INVALID" -> keep checking other codes in this tier
  }

  // Tiers 2-4: SEA, PHL, IND
  for (const region of IMAGE_REGION_FND_CODES) {
    const suffix = suffixTemplate.replace("{REGION}", region);
    for (const code of imageCodes) {
      const url = base + colorPath + code + suffix;
      const status = checkImageStatus(url);
      if (status === "VALID") return url;
    }
  }

  return ""; // Nothing found in any region/tier
}

/**
 * Returns "VALID", "COMING_SOON", or "INVALID".
 * "Coming Soon" placeholders are detected either by a non-200 response or by an
 * unusually small image (PUMA's placeholder is a fixed small graphic) — adjust the
 * dimension/byte-size heuristic below if your placeholder differs.
 */
function checkImageStatus(url) {
  try {
    const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (res.getResponseCode() !== 200) return "INVALID";

    const blob = res.getBlob();
    const img = ImagesService.openImage(blob);
    const width = img.getWidth();
    const height = img.getHeight();

    // Reject tiny placeholder-sized images (typical "Coming Soon" graphics are small).
    if (width < 650 || height < 650) return "COMING_SOON";

    return "VALID";
  } catch (e) {
    return "INVALID";
  }
}

/* -------------------------------------------------------------------------------------
 * Basic validation pass so bad input fails fast with a clear message instead of
 * crashing deep inside output generation.
 * ------------------------------------------------------------------------------------- */
function validateInputSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const inputSheet = ss.getSheetByName("Input");
  if (!inputSheet) throw new Error("Input sheet not found");
  const lastRow = inputSheet.getLastRow();
  if (lastRow < 2) throw new Error("Input sheet has no data rows to process");
  Logger.log("Input validation passed: " + (lastRow - 1) + " data rows found.");
}

/* =====================================================================================
 * SECTION B: OUTPUT GENERATION
 * =====================================================================================
 * Reads the already-resolved Input sheet (title/description with fallback applied,
 * size with JPN fallback + skip flags applied, image URLs pre-resolved) and writes
 * the final Output sheet. No network calls or export-sheet lookups happen here.
 * ===================================================================================== */

function runOutputGeneration() {
  var amountMap = constructAmountMap();
  var quantityMap = constructQuantityMap();
  var categoryMap = constructCategoryMap();
  var styleCountMap = countNoOfItems();
  buildOutputSheet(amountMap, quantityMap, categoryMap, styleCountMap);
}

function buildOutputSheet(amountMap, quantityMap, categoryMap, styleCountMap) {
  var main = SpreadsheetApp.getActive().getSheetByName("Output");
  var inputSheet = SpreadsheetApp.getActive().getSheetByName("Input");
  var processedStyle = [];
  var index = 2;
  var parentRow = 2;
  var processedParentCount = 0;
  var currentParentIndex = 2;
  var childIndex = 0;
  var childUpdateIndexMap = {};

  for (var i = 2; i <= inputSheet.getLastRow(); i++) {
    if (i == 2) {
      createHeadingForTargetSheet(main);
    }

    // ---- REQUIREMENT #2/#3: skip rows flagged during input processing instead of
    // letting mismatched size formats throw errors downstream. ----
    if (isRowSkipped(inputSheet, i)) {
      continue;
    }

    var style;
    var style_next_row;
    var products = inputSheet.getRange(i, 14).getValue();
    if (products == "Footwear") {
      style = inputSheet.getRange(i, 9).getValue();
      style_next_row = inputSheet.getRange(i + 1, 9).getValue();
    } else {
      style = inputSheet.getRange(i, 1).getValue();
      style_next_row = inputSheet.getRange(i + 1, 1).getValue();
    }

    if ((styleCountMap[style] == 1) || ((style == style_next_row) && processedStyle.indexOf(style) == -1)) {
      fillParentRow(main, inputSheet, index, i, categoryMap, amountMap, styleCountMap, childUpdateIndexMap);
      currentParentIndex = index;
      if (styleCountMap[style] > 1) {
        parentRow = i + processedParentCount;
        processedParentCount++;
      }
      index++;
    }
    if (styleCountMap[style] == 1) {
      continue;
    }

    var customSku = inputSheet.getRange(i, 16).getValue();
    var variation1 = inputSheet.getRange(i, 12).getValue();
    var newVariation1 = variation1.includes("Puma") ? variation1.replace("Puma", "PUMA") : variation1;

    // ---- Use effective size (UK or JPN fallback) instead of raw variation2() ----
    var variationTwo = getEffectiveSize(inputSheet, i);
    var temp_var_2 = variationTwo;
    if (temp_var_2 && temp_var_2.indexOf(" L") != -1) {
      temp_var_2 = temp_var_2.replace("Int:W", "").replace("Int:", "").replace("W", "").replace(" L", "/");
    }
    var mappingKey = variation1 + "_" + (temp_var_2 || "")
      .replace("UK:", "").replace("FR:", "").replace("US:", "").replace("ASIA:", "").replace("Int:", "")
      .replace(" yrs", "Y").replace("W", "").replace(" L", "/");

    childIndex = childUpdateIndexMap[mappingKey];
    if (childIndex === undefined) {
      // Mapping key not found (e.g. size sort didn't register this row) — skip safely.
      continue;
    }
    childIndex = childIndex + parentRow + 1;
    main.getRange(childIndex, 11).setValue(variationTwo);
    processedStyle.push(style);

    var amountMapValue = amountMap[customSku];
    var itemAmount, salePrice;
    if (amountMapValue != "" && amountMapValue != undefined) {
      itemAmount = amountMapValue[3];
      salePrice = amountMapValue[4];
    } else {
      main.getRange(childIndex, 17).setValue("error");
      main.getRange(childIndex, 14).setValue("error");
    }

    var ageGroup = inputSheet.getRange(i, 4).getValue();
    var articleGroup = inputSheet.getRange(i, 6).getValue();
    var brand = inputSheet.getRange(i, 3).getValue();
    // ---- REQUIREMENT #1: title now comes from the resolved (fallback-applied) column ----
    var regionalDispalyName = inputSheet.getRange(i, RESOLVED_TITLE_COL).getValue();
    var gender = inputSheet.getRange(i, 5).getValue();
    var activityGroup = inputSheet.getRange(i, 8).getValue();
    var articleType = inputSheet.getRange(i, 7).getValue();
    var searchColorName = inputSheet.getRange(i, 13).getValue();
    var colorName = inputSheet.getRange(i, 9).getValue();

    var newRegionalDisplayName = regionalDispalyName.includes("’s") ? regionalDispalyName.replace("’s", "'s™") : regionalDispalyName;
    var getSearchColorName;
    if (searchColorName && searchColorName.includes(' - ')) {
      getSearchColorName = searchColorName.split(' - ')[1];
    }

    var title, itemTitle;
    if (regionalDispalyName.includes("Men") || regionalDispalyName.includes("Women")) {
      title = formTitle(brand, newRegionalDisplayName, activityGroup, articleType, "", getSearchColorName, products);
    } else {
      title = formTitle(brand, newRegionalDisplayName, activityGroup, articleType, gender, getSearchColorName, products);
    }
    itemTitle = removeDuplicates(title);

    var mappedKey = ageGroup + '-' + gender + '-' + articleGroup + '-' + articleType + '-' + activityGroup;
    var categoryMapValue = categoryMap[mappedKey];
    if (categoryMapValue != undefined && categoryMapValue.length > 0) {
      main.getRange(childIndex, 21).setValue(categoryMapValue[1]);
    } else {
      main.getRange(childIndex, 21).setValue("error");
    }

    main.getRange(childIndex, 4).setValue(customSku);
    main.getRange(childIndex, 5).setValue(replaceSplCharacter(itemTitle));
    if (salePrice != undefined && salePrice != "") {
      main.getRange(childIndex, 14).setValue(salePrice);
    }
    main.getRange(childIndex, 10).setValue(newVariation1);
    fillDefaultValues(main, childIndex, amountMapValue);
    main.getRange(childIndex, 17).setValue(itemAmount);
    main.getRange(childIndex, 19).setValue(0);
    main.getRange(childIndex, 23).setValue(brand);
    main.getRange(childIndex, 24).setValue(colorName);
    main.getRange(childIndex, 30).setValue("1 X " + replaceSplCharacter(itemTitle));
    main.getRange(childIndex, 31).setValue("sku.color_family=[\"" + newVariation1 + "\",]");
    main.getRange(childIndex, 32).setValue("sku.size=[\"" + variationTwo + "\",]");
    main.getRange(currentParentIndex, 31).setValue(main.getRange(currentParentIndex + 1, 31).getValue());
    main.getRange(currentParentIndex, 32).setValue(main.getRange(currentParentIndex + 1, 32).getValue());

    // ---- REQUIREMENT #4: image URL is pre-resolved on Input; just copy it across ----
    var resolvedImage = inputSheet.getRange(i, IMAGE_RESOLVED_COL).getValue();
    if (resolvedImage) {
      main.getRange(childIndex, 20).setValue(resolvedImage);
    }

    index++;
  }
}

/* -------------------------------------------------------------------------------------
 * REQUIREMENT #5 — Short Description optional + Color Number removed from output
 * ------------------------------------------------------------------------------------- */
function getShortDescription(shortDescription, brand, searchColorName, gender, activityGroup, collection, material, materialLocal, upperMaterial,
  midSoleMaterial, outerSoleMaterial, shellMaterial, toeType,
  heelType, fastener, fit, pumaTechnology, technologyPurpose, inputSheet, index, style) {

  // Short Description is now optional — default to empty string instead of failing.
  var shortDesc = (shortDescription != undefined && shortDescription != null) ? shortDescription : "";

  if (brand) shortDesc += "<li>Brand : " + brand + "</li>";

  // Strip any embedded color number pattern from the color name before using it
  // (e.g. "01 - Black" -> "Black"), so no color codes leak into the description.
  if (searchColorName) {
    var cleanedColorName = searchColorName.toString().replace(/^\s*\d+\s*-\s*/, "").trim();
    if (cleanedColorName) shortDesc += "<li>Color Name : " + cleanedColorName + "</li>";
  }

  if (gender) shortDesc += "<li>Gender : " + gender + "</li>";
  if (activityGroup) shortDesc += "<li>Activity Group : " + activityGroup + "</li>";
  if (collection) shortDesc += "<li>Collection : " + collection + "</li>";

  if (material && material != "Other") {
    var newMaterial = "<li>Material : " + material + "</li>";
    var main_material_2_present = false;
    if (newMaterial.indexOf("Main Material 1") != -1) {
      newMaterial = newMaterial.replace("<li>Material : ", "<li>");
    }
    if (newMaterial.indexOf("Main Material 2") != -1) {
      main_material_2_present = true;
      newMaterial = newMaterial.replace("<li>Material : ", "<li>");
      newMaterial = newMaterial.replace("Main Material 2", "</li><li>Main Material 2");
    }
    if (newMaterial.indexOf("Main Material 3") != -1) {
      newMaterial = newMaterial.replace("<li>Material : ", "<li>");
      newMaterial = main_material_2_present
        ? newMaterial.replace("Main Material 3", "</li><li>Main Material 3")
        : newMaterial.replace("Main Material 3", "</li><li>Main Material 2");
    }
    shortDesc += newMaterial;
  }

  if (materialLocal && materialLocal != "Other") shortDesc += "<li>Material Local : " + materialLocal + "</li>";
  if (upperMaterial && upperMaterial != "Other") shortDesc += "<li>Upper Material : " + upperMaterial + "</li>";
  if (midSoleMaterial && midSoleMaterial != "Other") shortDesc += "<li>Mid Sole Material : " + midSoleMaterial + "</li>";
  if (outerSoleMaterial && outerSoleMaterial != "Other") shortDesc += "<li>Outer Sole Material : " + outerSoleMaterial + "</li>";
  if (shellMaterial && shellMaterial != "Other") shortDesc += "<li>Shell Material : " + shellMaterial + "</li>";
  if (toeType) shortDesc += "<li>Toe Type : " + toeType + "</li>";
  if (heelType) shortDesc += "<li>Heel Type : " + heelType + "</li>";
  if (fastener) shortDesc += "<li>Fastener : " + fastener + "</li>";
  if (fit) shortDesc += "<li>Fit : " + fit + "</li>";
  if (pumaTechnology) shortDesc += "<li>PUMA Technology : " + pumaTechnology + "</li>";
  if (technologyPurpose) shortDesc += "<li>Technology Purpose : " + technologyPurpose + "</li>";

  // NOTE: "Style Number" (style) is intentionally NOT appended here — that is the
  // color/style numeric code the requirement asks to remove from the output.

  return shortDesc;
}

/* =====================================================================================
 * UNCHANGED SUPPORT FUNCTIONS (kept from original script, referenced above)
 * ===================================================================================== */

function replaceSplCharacter(value) {
  if (value == undefined || value == null) return "";
  return value.toString()
    .replace("â€œ", "“").replace("â€", "”").replace("â€˜", "‘").replace("â€™", "’")
    .replace("â€”", "–").replace("â€“", "—").replace("â€¢", "-").replace("â€¦", "…")
    .replace("Ã˜", "Ø").replace("Ã‚Â®", "®").replace("Â³", "³").replace("Â®", "®")
    .replace("Ã¸", "Ÿ").replace("Ã‚", "Ÿ");
}

function fillDefaultValues(main, index, amountMapValue) {
  if (amountMapValue != "" && amountMapValue != undefined) {
    var salePrice = amountMapValue[4];
    if (salePrice != "") {
      main.getRange(index, 15).setValue("2024-05-10 00:00:00");
      main.getRange(index, 16).setValue("2024-06-10 23:59:00");
    }
  }
  main.getRange(index, 6).setValue("userTemplate-PH_PumaAccessories");
  main.getRange(index, 18).setValue("PHP");
  main.getRange(index, 22).setValue("default");
  main.getRange(index, 25).setValue("No Warranty");
  main.getRange(index, 26).setValue("0.5");
  main.getRange(index, 27).setValue("15");
  main.getRange(index, 28).setValue("12");
  main.getRange(index, 29).setValue("12");
}

function getItemTitle(regionalDispalyName, brand, gender, activityGroup, articleType, searchColorName, productsDivision) {
  var title, itemTitle, newRegionalDisplayName, getSearchColorName;
  newRegionalDisplayName = regionalDispalyName.includes("’s") ? regionalDispalyName.replace("’s", "'s™") : regionalDispalyName;
  if (searchColorName && searchColorName.includes(' - ')) {
    getSearchColorName = searchColorName.split(' - ')[1];
  }
  if (regionalDispalyName.includes("Men") || regionalDispalyName.includes("Women")) {
    title = formTitle(brand, newRegionalDisplayName, activityGroup, articleType, "", getSearchColorName, productsDivision);
  } else {
    title = formTitle(brand, newRegionalDisplayName, activityGroup, articleType, gender, getSearchColorName, productsDivision);
  }
  itemTitle = removeDuplicates(title);
  return itemTitle;
}

function formTitle(brand, newRegionalDisplayName, activityGroup, articleType, gender, searchColorName, productsDivision) {
  var title = "[NEW] ";
  title += brand.includes("Licence") ? brand.replace("Licence", "PUMA") : brand;

  if (gender != undefined && title.indexOf(gender) == -1) {
    if (gender == "Unisex") title += " " + gender;
  }

  if (title.indexOf(newRegionalDisplayName) == -1) {
    var checkRegionalDisplayName = "";
    if (newRegionalDisplayName.includes("Trainers")) {
      checkRegionalDisplayName = newRegionalDisplayName.replace("Trainers", "Shoes");
      title += " " + checkRegionalDisplayName;
    } else if (newRegionalDisplayName.includes("Sandals")) {
      checkRegionalDisplayName = newRegionalDisplayName.replace("Sandals", "Sports Sandals");
      title += " " + checkRegionalDisplayName;
    } else if (newRegionalDisplayName.includes("Slides")) {
      checkRegionalDisplayName = newRegionalDisplayName.replace("Slides", "Slides Slippers");
      title += " " + checkRegionalDisplayName;
    } else if (newRegionalDisplayName.includes("Trainer")) {
      checkRegionalDisplayName = newRegionalDisplayName.replace("Trainer", "Shoes");
      title += " " + checkRegionalDisplayName;
    } else {
      title += " " + newRegionalDisplayName;
    }
  }

  if (productsDivision == "Footwear" && title.indexOf(searchColorName) == -1) {
    title += " (" + searchColorName + ") ";
  }

  return title;
}

function countNoOfItems() {
  var inputSheet = SpreadsheetApp.getActive().getSheetByName("Input");
  var colorNumberValues = [];
  var styleValues = [];
  for (var i = 2; i <= inputSheet.getLastRow(); i++) {
    if (isRowSkipped(inputSheet, i)) continue; // honor skip flags in counts too
    var products = inputSheet.getRange(i, 14).getValue();
    if (products == "Footwear") {
      colorNumberValues.push(inputSheet.getRange(i, 9).getValue());
    } else {
      styleValues.push(inputSheet.getRange(i, 1).getValue());
    }
  }
  var result = {};
  colorNumberValues.forEach(x => { result[x] = (result[x] || 0) + 1; });
  styleValues.forEach(x => { result[x] = (result[x] || 0) + 1; });
  return result;
}

function fillParentRow(main, inputSheet, index, i, categoryMap, amountMap, styleCountMap, childUpdateIndexMap) {
  var customSku = inputSheet.getRange(i, 16).getValue();
  var ageGroup = inputSheet.getRange(i, 4).getValue();
  var articleGroup = inputSheet.getRange(i, 6).getValue();
  var brand = inputSheet.getRange(i, 3).getValue();
  var regionalDispalyName = inputSheet.getRange(i, RESOLVED_TITLE_COL).getValue(); // req #1
  var gender = inputSheet.getRange(i, 5).getValue();
  var activityGroup = inputSheet.getRange(i, 8).getValue();
  var articleType = inputSheet.getRange(i, 7).getValue();
  var searchColorName = inputSheet.getRange(i, 13).getValue();
  var longDescription = inputSheet.getRange(i, RESOLVED_LONG_DESC_COL).getValue(); // req #1
  var collection = inputSheet.getRange(i, 26).getValue();
  var material = inputSheet.getRange(i, 27).getValue();
  var materialLocal = inputSheet.getRange(i, 28).getValue();
  var upperMaterial = inputSheet.getRange(i, 29).getValue();
  var midSoleMaterial = inputSheet.getRange(i, 30).getValue();
  var outerSoleMaterial = inputSheet.getRange(i, 31).getValue();
  var shellMaterial = inputSheet.getRange(i, 32).getValue();
  var toeType = inputSheet.getRange(i, 33).getValue();
  var heelType = inputSheet.getRange(i, 34).getValue();
  var fastener = inputSheet.getRange(i, 66).getValue();
  var fit = inputSheet.getRange(i, 67).getValue();
  var pumaTechnology = inputSheet.getRange(i, 35).getValue();
  var technologyPurpose = inputSheet.getRange(i, 36).getValue();
  var shortDescription = inputSheet.getRange(i, RESOLVED_SHORT_DESC_COL).getValue(); // req #1 & #5 (optional)
  var care = inputSheet.getRange(i, 43).getValue();
  var careLabel = inputSheet.getRange(i, 44).getValue();
  var productsDivision = inputSheet.getRange(i, 14).getValue();

  var itemTitle = getItemTitle(regionalDispalyName, brand, gender, activityGroup, articleType, searchColorName, productsDivision);
  main.getRange(index, 5).setValue(replaceSplCharacter(itemTitle));
  main.getRange(index, 30).setValue("1 X " + replaceSplCharacter(itemTitle));

  var mappedKey = ageGroup + '-' + gender + '-' + articleGroup + '-' + articleType + '-' + activityGroup;
  var categoryMapValue = categoryMap[mappedKey];
  var amountMapValue = amountMap[customSku];

  if (amountMapValue != "" && amountMapValue != undefined) {
    main.getRange(index, 17).setValue(amountMapValue[3]);
  }

  var act_group = inputSheet.getRange(i, 8).getValue();
  if (act_group == "Prime/Select") {
    act_group = "Others";
  } else if (["Sport Classics", "Evolution", "Basics", "Kids", "Auto"].indexOf(act_group) !== -1) {
    act_group = "Lifestyle";
  }

  var val1 = "";
  if (material.indexOf("100% polyester") != -1) val1 = 'normal.clothing_material=["Polyester",]';
  else if (material.indexOf("100% nylon") != -1) val1 = 'normal.clothing_material=["Nylon",]';
  else if (material.indexOf("100% cotton") != -1) val1 = 'normal.clothing_material=["Cotton",]';
  else if (material.indexOf("polyester") != -1 && material.indexOf("nylon") != -1) val1 = 'normal.clothing_material=["Polyester+Nylon",]';
  else if (material.indexOf("polyester") != -1 && material.indexOf("cotton") != -1) val1 = 'normal.clothing_material=["Polyester+Cotton",]';
  else if (material.indexOf("polyester") != -1 && material.indexOf("elastane") != -1) val1 = 'normal.clothing_material=["Polyester+Elasteane",]';
  else if (material.indexOf("polyester") != -1 && material.indexOf("spandex") != -1) val1 = 'normal.clothing_material=["Polyester+Spandex",]';

  var itemSpecIndex = 33;
  main.getRange(index, itemSpecIndex).setValue('normal.activity_type=["' + act_group + '",]');
  if (val1 != "") {
    itemSpecIndex++;
    main.getRange(index, itemSpecIndex).setValue(val1);
  }
  itemSpecIndex++;
  main.getRange(index, itemSpecIndex).setValue('normal.delivery_option_economy=["No",]');

  if (articleGroup && articleGroup.toLowerCase() == "tops") {
    var tops_type = articleType == "Tee" ? "T-Shirts" : (articleType == "Polo" ? "Polo" : "");
    if (tops_type != "") {
      itemSpecIndex++;
      main.getRange(index, itemSpecIndex).setValue('normal.tops_type=["' + tops_type + '",]');
    }
  }

  main.getRange(index, 21).setValue(categoryMapValue && categoryMapValue.length > 0 ? categoryMapValue[1] : "error");

  var style = (productsDivision == "Footwear") ? inputSheet.getRange(i, 9).getValue() : inputSheet.getRange(i, 1).getValue();

  var shortDescrition = getShortDescription(shortDescription, brand, searchColorName, gender, activityGroup, collection, material, materialLocal, upperMaterial,
    midSoleMaterial, outerSoleMaterial, shellMaterial, toeType, heelType, fastener, fit, pumaTechnology, technologyPurpose, inputSheet, index, style);

  var styleCount = styleCountMap[style];
  sortChildIndexBasedOnSize(childUpdateIndexMap, styleCount, i, index);

  fillDefaultValues(main, index, amountMapValue);
  var templateAttributeValueList = getTemplateAttribute1();
  var sizeChartKey = ageGroup + "-" + gender + "-" + articleGroup + "-" + articleType;
  var templateAttributeValue = templateAttributeValueList[sizeChartKey];
  var templateAttribute1 = "", templateAttribute4 = "", templateAttribute5 = "";
  if (templateAttributeValue != "" && templateAttributeValue != undefined) {
    templateAttribute1 = templateAttributeValue[1];
  }
  if (care != "" && care != undefined) templateAttribute4 += "<p><strong>Care:</strong>" + care + "<p>";
  if (careLabel != "" && careLabel != undefined) templateAttribute4 += "<p><strong>Care Label:</strong>" + careLabel + "<p>";

  fillTempateAttributes(main, templateAttribute1, templateAttribute4, templateAttribute5, index, longDescription);

  main.getRange(index, 19).setValue(0);
  if (styleCountMap[style] > 1) {
    main.getRange(index, 4).setValue(style);
    main.getRange(index, 9).setValue(styleCount);
    main.getRange(index, 10).setValue("color_family");
    main.getRange(index, 11).setValue("size");
  } else {
    main.getRange(index, 4).setValue(customSku);
  }
  main.getRange(index, 13).setValue("<ul>" + replaceSplCharacter(shortDescrition) + "</ul>");
  main.getRange(index, 23).setValue(brand);
  main.getRange(index, 24).setValue(style);

  // req #4: resolved image URL copied straight across for the parent row too.
  var resolvedImage = inputSheet.getRange(i, IMAGE_RESOLVED_COL).getValue();
  if (resolvedImage) {
    main.getRange(index, 20).setValue(resolvedImage);
  }
}

function sortChildIndexBasedOnSize(childUpdateIndexMap, styleCount, j, index) {
  var inputSheet = SpreadsheetApp.getActive().getSheetByName("Input");
  var childEndIndex = j + styleCount - 1;
  var sizeValues = inputSheet.getRange("L" + j + ":V" + childEndIndex).getValues();
  var tempArray = [], childArray = [], colourArray = [], colourValueCountMap = {}, customSKUArray = [], parentQuantity = 0;

  for (var i = 0; i < sizeValues.length; i++) {
    var rowIndex = i + j;
    if (isRowSkipped(inputSheet, rowIndex)) continue; // honor skip flags in sizing too

    var value1 = sizeValues[i];
    var sizeValue = getEffectiveSize(inputSheet, rowIndex);
    if (!sizeValue) continue;
    sizeValue = sizeValue.replace("UK:", "").replace("FR:", "").replace("US:", "").replace("ASIA:", "").replace("Int:", "").replace(" yrs", "Y");
    if (sizeValue.indexOf(" L") != -1) {
      sizeValue = sizeValue.replace("Int:W", "").replace("Int:", "").replace("W", "").replace(" L", "/");
    }

    var customSKU = value1[4];
    var colour = value1[0];
    parentQuantity += value1[5];
    customSKUArray.push(customSKU);
    if (tempArray.indexOf(sizeValue) == -1) tempArray.push(sizeValue);
    childArray.push(sizeValue);
    colourArray.push(colour);
    colourValueCountMap[colour] = (colourValueCountMap[colour] || 0) + 1;
  }

  var sortByStringValue = ["3XS", "XXXS", "XXS", "XS", "S", "S/M", "M", "M/L", "L", "L/XL", "XL", "XXL", "XXXL", "3XL", "4XL", "5XL", "6XL",
    "1-2Y", "2-3Y", "3-4Y", "4-5Y", "5-6Y", "6-7Y", "7-8Y", "8-9Y", "9-10Y", "10-11Y", "11-12Y", "12-13Y", "13-14Y", "14-15Y", "15-16Y",
    "6Y", "8Y", "10Y", "12Y", "14Y", "16Y", "18Y", "20Y", "OSFA", "One size", "UA", "Mini", "Kids", "Adult", "Youth"]
    .some(s => childArray.indexOf(s) != -1);

  if (sortByStringValue) {
    sortByStringValues(childArray, tempArray, customSKUArray, childUpdateIndexMap, colourArray, colourValueCountMap);
  } else {
    tempArray.sort((a, b) => (isNaN(a) && isNaN(b)) ? a.localeCompare(b) : a - b);
    sortByIntValues(childArray, tempArray, customSKUArray, childUpdateIndexMap, colourArray, colourValueCountMap);
  }
  return parentQuantity;
}

function sortByIntValues(childArray, tempArray, customSKUArray, childUpdateIndexMap, colourArray, colourValueCountMap) {
  var colourSizeMap = [], availableColour = [];
  for (var i = 0; i < childArray.length; i++) {
    var colour = colourArray[i];
    if (availableColour.indexOf(colour) == -1) availableColour.push(colour);
    colourSizeMap.push(colour + "_" + childArray[i]);
  }
  var colourCount = 0;
  for (var i = 0; i < availableColour.length; i++) {
    for (var j = 0; j < tempArray.length; j++) {
      var key = availableColour[i] + "_" + tempArray[j];
      if (colourSizeMap.indexOf(key) != -1) {
        childUpdateIndexMap[key] = colourCount;
        colourCount++;
      }
    }
  }
}

function sortByStringValues(childArray, tempArray, customSKUArray, childUpdateIndexMap, colourArray, colourValueCountMap) {
  var colourSizeMap = [], availableColour = [];
  for (var i = 0; i < childArray.length; i++) {
    var colour = colourArray[i];
    if (availableColour.indexOf(colour) == -1) availableColour.push(colour);
    colourSizeMap.push(colour + "_" + childArray[i]);
  }
  var loopSize = ["3XS", "XXXS", "XXS", "XS", "S", "S/M", "M", "M/L", "L", "L/XL", "XL", "XXL", "XXXL", "3XL", "4XL", "5XL", "6XL",
    "1-2Y", "2-3Y", "3-4Y", "4-5Y", "5-6Y", "6-7Y", "7-8Y", "8-9Y", "9-10Y", "10-11Y", "11-12Y", "12-13Y", "13-14Y", "14-15Y", "15-16Y",
    "16-17Y", "17-18Y", "18-19Y", "19-20Y", "6Y", "8Y", "10Y", "12Y", "14Y", "16Y", "18Y", "20Y", "OSFA", "One size", "UA", "Mini", "Kids", "Adult", "Youth"];
  var colourCount = 0;
  for (var i = 0; i < availableColour.length; i++) {
    for (var j = 0; j < loopSize.length; j++) {
      var key = availableColour[i] + "_" + loopSize[j];
      if (colourSizeMap.indexOf(key) != -1) {
        childUpdateIndexMap[key] = colourCount;
        colourCount++;
      }
    }
  }
}

function getTemplateAttribute1() {
  var sizeChartMap = {};
  var sizeChartSheet = SpreadsheetApp.getActive().getSheetByName("Size chart");
  var values = sizeChartSheet.getRange("A2:B" + sizeChartSheet.getLastRow()).getValues();
  for (var i = 0; i < values.length; i++) {
    sizeChartMap[values[i][0]] = values[i];
  }
  return sizeChartMap;
}

function removeDuplicates(title) {
  var str = title.split(" ");
  var result = [];
  for (var i = 0; i < str.length; i++) {
    if (result.indexOf(str[i]) === -1) result.push(str[i]);
  }
  return result.join(" ");
}

function fillTempateAttributes(main, templateAttribute1, templateAttribute4, templateAttribute5, index, longDescription) {
  var templateAttribute2 = "", templateAttribute3 = "";
  longDescription = longDescription || ""; // req #1: tolerate blank description safely

  if (longDescription.includes("FEATURES")) {
    templateAttribute2 = longDescription.substring(longDescription.indexOf("<p>"), longDescription.indexOf("FEATURES"));
    templateAttribute3 = longDescription.substring(longDescription.indexOf("FEATURES"));
  } else if (longDescription.includes("DETAILS")) {
    templateAttribute2 = longDescription.substring(longDescription.indexOf("<p>"), longDescription.indexOf("DETAILS"));
    templateAttribute3 = longDescription.substring(longDescription.indexOf("DETAILS"));
  } else if (longDescription.indexOf("<p>") !== -1) {
    templateAttribute2 = longDescription.substring(longDescription.indexOf("<p>"));
  }

  main.getRange(index, 56).setValue("sizechart=" + templateAttribute1);
  if (templateAttribute2 != "") main.getRange(index, 57).setValue("description=" + replaceSplCharacter(templateAttribute2).replace("<h3>", ""));
  if (templateAttribute3 != "") main.getRange(index, 58).setValue("productstory=<h3>" + replaceSplCharacter(templateAttribute3));
  if (templateAttribute4 != "") main.getRange(index, 59).setValue("care=" + replaceSplCharacter(templateAttribute4));
}

function capitalizeFirstLetters(str) {
  var strVal = '';
  str = str.split(' ');
  for (var chr = 0; chr < str.length; chr++) {
    strVal += str[chr].substring(0, 1).toUpperCase() + str[chr].substring(1) + ' ';
  }
  return strVal;
}

function constructAmountMap() {
  var amountMap = {};
  var priceSheet = SpreadsheetApp.getActive().getSheetByName("Price Sheet");
  var values = priceSheet.getRange("A2:E" + priceSheet.getLastRow()).getValues();
  for (var i = 0; i < values.length; i++) amountMap[values[i][2]] = values[i];
  return amountMap;
}

function constructQuantityMap() {
  var quantitytMap = {};
  var quantitySheet = SpreadsheetApp.getActive().getSheetByName("Stock sheet");
  var values = quantitySheet.getRange("A2:B" + quantitySheet.getLastRow()).getValues();
  for (var i = 0; i < values.length; i++) quantitytMap[values[i][0]] = values[i];
  return quantitytMap;
}

function constructCategoryMap() {
  var categoryMap = {};
  var categorySheet = SpreadsheetApp.getActive().getSheetByName("Category sheet");
  var values = categorySheet.getRange("A2:C" + categorySheet.getLastRow()).getValues();
  for (var i = 0; i < values.length; i++) categoryMap[values[i][0]] = values[i];
  return categoryMap;
}

function createHeadingForTargetSheet(target) {
  var headings = ["SKU", "status", "errorDetails", "customSKU", "itemTitle", "itemDescription1", "itemDescription2", "itemDescription3", "noOfVariants", "variation1", "variation2", "variation3", "shortDescription", "salePrice", "saleStartDate", "saleEndDate", "itemAmount", "currencyCode", "noOfItem", "imageURI", "categoryID", "taxClass", "brand", "model", "warrantyType", "packageWeight(kg)", "packageHeight(cm)", "packageLength(cm)", "packageWidth(cm)", "packageContent", "itemSpecifics1", "itemSpecifics2", "itemSpecifics3", "itemSpecifics4", "itemSpecifics5", "itemSpecifics6", "itemSpecifics7", "itemSpecifics8", "itemSpecifics9", "itemSpecifics10", "itemSpecifics11", "itemSpecifics12", "itemSpecifics13", "itemSpecifics14", "itemSpecifics15", "itemSpecifics16", "itemSpecifics17", "itemSpecifics18", "itemSpecifics19", "itemSpecifics20", "itemSpecifics21", "itemSpecifics22", "itemSpecifics23", "itemSpecifics24", "itemSpecifics25", "templateAttribute1", "templateAttribute2", "templateAttribute3", "templateAttribute4", "templateAttribute5", "postAsNonVariant"];
  for (var i = 0; i < headings.length; i++) target.getRange(1, i + 1).setValue(headings[i]);
}

/* -------------------------------------------------------------------------------------
 * populateSizeData / populateColorDataFromColorExport / populateStyleDataFromStyleExport
 * kept functionally the same as original (input-side raw export ingestion), with the
 * duplicate populateStyleDataFromStyleExport() definition removed (the original file
 * defined it twice — only the second, correct version using "Style no." is kept).
 * ------------------------------------------------------------------------------------- */

function populateSizeData() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sizeSheet = ss.getSheetByName("Size Export");
  const inputSheet = ss.getSheetByName("Input") || ss.insertSheet("Input");
  if (!sizeSheet) throw new Error("Size Export sheet not found");

  const data = sizeSheet.getDataRange().getValues();
  const header = data.shift();
  const eanIndex = header.findIndex(h => h && h.toString().trim().toLowerCase() === "ean");
  const colorNoIndex = header.findIndex(h => h && h.toString().trim().toLowerCase() === "color no");
  const UKSizeIndex = header.findIndex(h => h && h.toString().trim().toLowerCase() === "print size code (uk)");
  const FRSizeIndex = header.findIndex(h => h && h.toString().trim().toLowerCase() === "print size code (fr)");
  const USASizeIndex = header.findIndex(h => h && h.toString().trim().toLowerCase() === "print size code (usa)");
  const INTSizeIndex = header.findIndex(h => h && h.toString().trim().toLowerCase() === "print size code (int)");
  if (eanIndex === -1 || colorNoIndex === -1) throw new Error("EAN or Color No column not found in Size Export");

  const output = [];
  data.forEach(row => {
    const outRow = new Array(23).fill("");
    outRow[0] = row[colorNoIndex] || "";
    outRow[15] = row[eanIndex] || "";
    outRow[19] = row[USASizeIndex] || "";
    outRow[20] = row[FRSizeIndex] || "";
    outRow[21] = row[UKSizeIndex] || "";
    outRow[22] = row[INTSizeIndex] || "";
    output.push(outRow);
  });

  inputSheet.getRange(2, 1, output.length, 23).setValues(output);
  inputSheet.getRange("A1").setValue("Style no.");
  inputSheet.getRange("P1").setValue("EAN");
  inputSheet.getRange("T1").setValue("SizeUS");
  inputSheet.getRange("U1").setValue("SizeFR");
  inputSheet.getRange("V1").setValue("SizeUK");
  inputSheet.getRange("W1").setValue("SizeASIA");
  SpreadsheetApp.flush();
}

function populateColorDataFromColorExport() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const inputSheet = ss.getSheetByName("Input");
  const colorSheet = ss.getSheetByName("Color Export");
  if (!inputSheet || !colorSheet) throw new Error("Input sheet or Color Export sheet not found");

  const norm = v => v ? v.toString().trim().toLowerCase() : "";
  const findIndex = (header, name) => header.findIndex(h => norm(h) === norm(name));

  const inputData = inputSheet.getDataRange().getValues();
  const inputHeader = inputData[0];
  const styleNoIdx = findIndex(inputHeader, "Style no.");
  if (styleNoIdx === -1) throw new Error("StyleNo column not found in Input sheet");

  const colorData = colorSheet.getDataRange().getValues();
  const colorHeader = colorData.shift();
  const colorStyleNoIdx = findIndex(colorHeader, "Color No");
  if (colorStyleNoIdx === -1) throw new Error("Style No column not found in Color Export sheet");

  const colorMap = {};
  colorData.forEach(row => {
    const key = norm(row[colorStyleNoIdx]);
    if (key) colorMap[key] = row;
  });

  const columnMapping = [
    { inputCol: 9, colorCol: "Color No" },
    { inputCol: 12, colorCol: "Color Name" },
    { inputCol: 13, colorCol: "Search Color Name" },
    { inputCol: 29, colorCol: "Upper (English (UK))" },
    { inputCol: 30, colorCol: "Mid Sole (English (UK))" },
    { inputCol: 31, colorCol: "Outer Sole (English (UK))" },
    { inputCol: 41, colorCol: "Pattern" }
  ];
  columnMapping.forEach(m => {
    m.colorIdx = findIndex(colorHeader, m.colorCol);
    if (m.colorIdx === -1) throw new Error(`Column "${m.colorCol}" not found in Color Export`);
  });

  for (let r = 1; r < inputData.length; r++) {
    const styleNo = norm(inputData[r][styleNoIdx]);
    const colorRow = colorMap[styleNo];
    if (!colorRow) continue;
    columnMapping.forEach(m => {
      inputData[r][m.inputCol - 1] = colorRow[m.colorIdx] || "";
    });
  }

  inputSheet.getRange(1, 1, inputData.length, inputData[0].length).setValues(inputData);
  SpreadsheetApp.flush();
}

function populateStyleDataFromStyleExport() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const inputSheet = ss.getSheetByName("Input");
  const styleSheet = ss.getSheetByName("Style Export");
  if (!inputSheet || !styleSheet) throw new Error("Input sheet or Style Export sheet not found");

  const norm = v => v ? v.toString().trim().toLowerCase() : "";
  const findIndex = (header, name) => header.findIndex(h => norm(h) === norm(name));

  const inputData = inputSheet.getDataRange().getValues();
  const inputHeader = inputData[0];
  const styleNoIdx = findIndex(inputHeader, "Style no.");
  if (styleNoIdx === -1) throw new Error("StyleNo column not found in Input sheet");

  const styleData = styleSheet.getDataRange().getValues();
  const styleHeader = styleData.shift();
  const styleExportStyleNoIdx = findIndex(styleHeader, "Style no.");
  if (styleExportStyleNoIdx === -1) throw new Error("Style no column not found in Style Export sheet");

  const styleMap = {};
  styleData.forEach(row => {
    const key = norm(row[styleExportStyleNoIdx]);
    if (key) styleMap[key] = row;
  });

  const columnMapping = [
    { inputCol: 1, styleCol: "Style no." },
    { inputCol: 3, styleCol: "Brand" },
    { inputCol: 4, styleCol: "Age Group" },
    { inputCol: 5, styleCol: "Gender" },
    { inputCol: 6, styleCol: "Article Group" },
    { inputCol: 7, styleCol: "Article Type" },
    { inputCol: 8, styleCol: "Activity Group" },
    { inputCol: 14, styleCol: "Product Division" },
    { inputCol: 26, styleCol: "Collection" },
    { inputCol: 27, styleCol: "Material" },
    { inputCol: 28, styleCol: "Material (English)" },
    { inputCol: 34, styleCol: "Heel Type" },
    { inputCol: 35, styleCol: "Puma Technology" },
    { inputCol: 36, styleCol: "Technology Purpose" },
    { inputCol: 42, styleCol: "Dimensions Accessories" },
    { inputCol: 66, styleCol: "Fastener" },
    { inputCol: 67, styleCol: "Fit" },
    { inputCol: 68, styleCol: "Notes (SEA)" },
    { inputCol: 69, styleCol: "Body Style 1" },
    { inputCol: 70, styleCol: "Body Style 2" }
    // NOTE: Regional Display Name / Short Description / Long Description columns are
    // intentionally handled by resolveTitleAndDescriptionForSheet() (req #1) instead,
    // so they are removed from this mapping to avoid being overwritten afterward.
  ];
  columnMapping.forEach(m => {
    m.styleIdx = findIndex(styleHeader, m.styleCol);
    if (m.styleIdx === -1) throw new Error(`Column "${m.styleCol}" not found in Style Export`);
  });

  for (let r = 1; r < inputData.length; r++) {
    const rawStyleNo = inputData[r][styleNoIdx];
    if (!rawStyleNo) continue;
    const lookupKey = norm(rawStyleNo.toString());
    const styleRow = styleMap[lookupKey];
    if (!styleRow) continue;
    columnMapping.forEach(m => {
      inputData[r][m.inputCol - 1] = styleRow[m.styleIdx] || "";
    });
  }

  inputSheet.getRange(1, 1, inputData.length, inputData[0].length).setValues(inputData);
  SpreadsheetApp.flush();
}
