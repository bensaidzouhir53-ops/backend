/**
 * Nasama Shop — Google Sheets order webhook + COD Network forward
 *
 * Setup:
 * 1. Open your Google Sheet (tab name must match SHEET_NAME below — default: nasama-ksa)
 * 2. Row 1 headers (exact order):
 *    date | order id | country | name | phone | product | sku | quantity | total price | currency | statue | url
 * 3. Extensions → Apps Script → paste this entire file → Save
 * 4. Run setupCodNetwork_() once (edit token/SKU inside that function first)
 * 5. Deploy → New deployment → Web app
 *    Execute as: Me | Who has access: Anyone
 * 6. Copy the Web App URL into Easypanel backend env:
 *    GOOGLE_SHEET_WEBHOOK_URL=https://script.google.com/macros/s/XXXX/exec
 *    ENABLE_SHEET_WEBHOOK=true
 * 7. Restart/redeploy the backend
 *
 * Change COD SKU anytime: Project Settings → Script properties
 *   ENABLE_COD_NETWORK = true
 *   COD_NETWORK_API_TOKEN = your JWT token
 *   COD_NETWORK_SKU = HBLEANSPRY3
 *   COD_NETWORK_PRODUCT_NAME = Herbal lung cleansing spray
 */

const SHEET_NAME = 'nasama-ksa';

const HEADERS = [
  'date',
  'order id',
  'country',
  'name',
  'phone',
  'product',
  'sku',
  'quantity',
  'total price',
  'currency',
  'statue',
  'url',
];

/** Run once from Apps Script editor after pasting your token + SKU. */
function setupCodNetwork_() {
  PropertiesService.getScriptProperties().setProperties({
    ENABLE_COD_NETWORK: 'true',
    COD_NETWORK_API_TOKEN: 'PASTE_YOUR_COD_NETWORK_TOKEN_HERE',
    COD_NETWORK_SKU: 'HBLEANSPRY3',
    COD_NETWORK_PRODUCT_NAME: 'Herbal lung cleansing spray',
  });
  Logger.log('COD Network script properties saved.');
}

function codConfig_() {
  const props = PropertiesService.getScriptProperties();
  return {
    enabled: String(props.getProperty('ENABLE_COD_NETWORK') || '').toLowerCase() === 'true',
    token: (props.getProperty('COD_NETWORK_API_TOKEN') || '').trim(),
    sku: (props.getProperty('COD_NETWORK_SKU') || 'HBLEANSPRY3').trim(),
    productName: (props.getProperty('COD_NETWORK_PRODUCT_NAME') || 'Herbal lung cleansing spray').trim(),
  };
}

function firstPart_(value) {
  if (!value) {
    return '';
  }
  return String(value).split('/')[0].trim();
}

function parseQuantity_(value) {
  const raw = firstPart_(value);
  const qty = parseInt(raw, 10);
  return Number.isFinite(qty) && qty > 0 ? qty : 1;
}

function splitParts_(value) {
  if (!value) {
    return [];
  }
  return String(value).split('/').map(function (part) {
    return part.trim();
  }).filter(Boolean);
}

function parseQuantityAt_(value, index) {
  const parts = splitParts_(value);
  if (!parts.length) {
    return 1;
  }
  const raw = parts[index] != null ? parts[index] : parts[0];
  const qty = parseInt(raw, 10);
  return Number.isFinite(qty) && qty > 0 ? qty : 1;
}

function buildCodItems_(data, cfg) {
  const skus = splitParts_(data.sku);
  const productNames = splitParts_(data.product);
  const totalPrice = Number(data.total_price) || 0;

  if (!skus.length) {
    return [{
      sku: cfg.sku,
      productName: cfg.productName,
      quantity: parseQuantity_(data.quantity),
      price: totalPrice,
    }];
  }

  const perLinePrice = skus.length > 1
    ? Number((totalPrice / skus.length).toFixed(2))
    : totalPrice;

  return skus.map(function (sku, index) {
    return {
      sku: sku || cfg.sku,
      productName: productNames[index] || productNames[0] || cfg.productName,
      quantity: parseQuantityAt_(data.quantity, index),
      price: perLinePrice,
    };
  });
}

function sendToCodNetwork_(data) {
  const cfg = codConfig_();
  if (!cfg.enabled) {
    return { ok: false, skipped: true, reason: 'cod_disabled' };
  }
  if (!cfg.token) {
    return { ok: false, skipped: true, reason: 'missing_token' };
  }

  const lines = buildCodItems_(data, cfg);
  const phone = String(data.phone || '').replace(/^\+/, '');
  const primary = lines[0];

  const payload = {
    full_name: data.name || '',
    phone: phone,
    address: 'الرياض - سيتم تأكيد العنوان مع العميل هاتفياً',
    city: 'Riyadh',
    area: 'Riyadh',
    country: 'Saudi Arabia',
    currency: data.currency || 'SAR',
    sku_1: primary.sku,
    product_name_1: primary.productName,
    quantity_1: primary.quantity,
    price_1: primary.price,
    'order-id': data.order_id || '',
    notes: 'order=' + (data.order_id || '') + ' | source=google-sheet-webhook',
    items: lines.map(function (line) {
      return { sku: line.sku, quantity: line.quantity, price: line.price };
    }),
  };

  for (var i = 1; i < lines.length; i++) {
    var index = i + 1;
    payload['sku_' + index] = lines[i].sku;
    payload['product_name_' + index] = lines[i].productName;
    payload['quantity_' + index] = lines[i].quantity;
    payload['price_' + index] = lines[i].price;
  }

  const response = UrlFetchApp.fetch('https://api.cod.network/api/v2/seller/leads', {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: 'Bearer ' + cfg.token,
      Accept: 'application/json',
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  const status = response.getResponseCode();
  const body = response.getContentText();
  Logger.log('COD Network response ' + status + ': ' + body.slice(0, 500));

  if (status >= 400 && body.indexOf('41030') !== -1) {
    const fallback = Object.assign({}, payload);
    delete fallback.items;
    const retry = UrlFetchApp.fetch('https://api.cod.network/api/v2/seller/leads', {
      method: 'post',
      contentType: 'application/json',
      headers: {
        Authorization: 'Bearer ' + cfg.token,
        Accept: 'application/json',
      },
      payload: JSON.stringify(fallback),
      muteHttpExceptions: true,
    });
    return {
      ok: retry.getResponseCode() >= 200 && retry.getResponseCode() < 300,
      status: retry.getResponseCode(),
      body: retry.getContentText().slice(0, 500),
      retried_without_items: true,
    };
  }

  return {
    ok: status >= 200 && status < 300,
    status: status,
    body: body.slice(0, 500),
  };
}

function ensureSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);

  if (!sheet) {
    sheet = ss.getActiveSheet();
  }

  const firstCell = sheet.getRange(1, 1).getValue();
  if (!firstCell) {
    sheet.appendRow(HEADERS);
    sheet.getRange(1, 1, 1, HEADERS.length).setFontWeight('bold');
    sheet.setFrozenRows(1);
  }

  return sheet;
}

function rowFromPayload_(data) {
  return [
    data.date || '',
    data.order_id || '',
    data.country || 'KSA',
    data.name || '',
    data.phone || '',
    data.product || '',
    data.sku || '',
    data.quantity || '',
    data.total_price != null ? data.total_price : '',
    data.currency || 'SAR',
    '',
    data.url || '',
  ];
}

function findRowByOrderId_(sheet, orderId) {
  if (!orderId) {
    return -1;
  }

  const values = sheet.getDataRange().getValues();
  for (let i = 1; i < values.length; i++) {
    if (String(values[i][1]) === String(orderId)) {
      return i + 1;
    }
  }
  return -1;
}

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return jsonResponse_({ ok: false, error: 'Empty request body' });
    }

    const data = JSON.parse(e.postData.contents);
    const sheet = ensureSheet_();
    const event = data.event || 'order_created';
    const row = rowFromPayload_(data);
    let codResult = null;

    if (event === 'order_created') {
      const existingRow = findRowByOrderId_(sheet, data.order_id);
      if (existingRow > 0) {
        return jsonResponse_({ ok: true, message: 'duplicate_skipped' });
      }
      sheet.appendRow(row);
      if (data.send_cod !== false) {
        codResult = sendToCodNetwork_(data);
      }
      return jsonResponse_({ ok: true, message: 'order_created', cod: codResult });
    }

    if (event === 'upsell_accepted') {
      const existingRow = findRowByOrderId_(sheet, data.order_id);
      if (existingRow > 0) {
        sheet.getRange(existingRow, 1, 1, HEADERS.length).setValues([row]);
      } else {
        sheet.appendRow(row);
      }
      if (data.send_cod !== false) {
        codResult = sendToCodNetwork_(data);
      }
      return jsonResponse_({ ok: true, message: 'upsell_updated', cod: codResult });
    }

    return jsonResponse_({ ok: false, error: 'Unknown event' });
  } catch (err) {
    Logger.log('Webhook error: ' + err.toString());
    return jsonResponse_({ ok: false, error: err.toString() });
  }
}

function doGet() {
  const cfg = codConfig_();
  return jsonResponse_({
    ok: true,
    service: 'nasama-shop-webhook',
    cod_enabled: cfg.enabled,
    cod_sku: cfg.sku,
    cod_token_set: Boolean(cfg.token),
  });
}

function jsonResponse_(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
