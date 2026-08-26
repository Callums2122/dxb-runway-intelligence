/**
 * DXB Runway Stock Flow reader.
 * Security: Gmail API GET requests only, gmail.readonly scope only, no send,
 * modify, trash, label, draft or write operation exists in this project.
 */
const RUNWAY_ASSIGNEE = 'Callum Steen';

function doGet(e) {
  const expected = PropertiesService.getScriptProperties().getProperty('DXB_STOCK_FLOW_ACCESS_KEY');
  if (!expected || !e || !e.parameter || e.parameter.key !== expected) {
    return json_({status: 'error', error: 'unauthorised'});
  }
  try {
    const query = 'from:admin@albacars.kissflow.com newer_than:45d {subject:"STOCK FLOW" subject:"PRICE REDUCTION"}';
    const listed = gmailGet_('/gmail/v1/users/me/messages?q=' + encodeURIComponent(query) + '&maxResults=200');
    const messages = gmailGetMany_((listed.messages || []).map(function(row) {
      return '/gmail/v1/users/me/messages/' + encodeURIComponent(row.id) + '?format=full';
    }));
    const events = messages.map(function(message) {
      return parseMessage_(message);
    }).filter(function(row) { return row !== null; });
    return json_({status: 'ok', readOnly: true, stockEvents: events});
  } catch (error) {
    return json_({status: 'error', error: String(error && error.message || error)});
  }
}

function gmailGetMany_(paths) {
  const token = ScriptApp.getOAuthToken();
  const results = [];
  for (let offset = 0; offset < paths.length; offset += 50) {
    const requests = paths.slice(offset, offset + 50).map(function(path) {
      return {
        url: 'https://gmail.googleapis.com' + path,
        method: 'get',
        headers: {Authorization: 'Bearer ' + token},
        muteHttpExceptions: true
      };
    });
    UrlFetchApp.fetchAll(requests).forEach(function(response) {
      if (response.getResponseCode() !== 200) throw new Error('Gmail read failed: HTTP ' + response.getResponseCode());
      results.push(JSON.parse(response.getContentText()));
    });
  }
  return results;
}

function gmailGet_(path) {
  const response = UrlFetchApp.fetch('https://gmail.googleapis.com' + path, {
    method: 'get',
    headers: {Authorization: 'Bearer ' + ScriptApp.getOAuthToken()},
    muteHttpExceptions: true
  });
  if (response.getResponseCode() !== 200) throw new Error('Gmail read failed: HTTP ' + response.getResponseCode());
  return JSON.parse(response.getContentText());
}

function parseMessage_(message) {
  const headers = {};
  (message.payload.headers || []).forEach(function(header) { headers[String(header.name).toLowerCase()] = header.value; });
  const subject = headers.subject || '';
  const text = htmlToText_(messageBody_(message.payload));
  if (!/stock\s*flow|price\s*(reduction|change)|photoshoot|pull\s*out|prep|booked|moved\s+to\s+stock/i.test(subject + ' ' + text)) return null;
  const assignee = match_(text, /Assignee\s*:\s*([^\n\r]+)/i);
  if (assignee && assignee.toLowerCase().indexOf(RUNWAY_ASSIGNEE.toLowerCase()) < 0) return null;
  const workflow = match_(subject + '\n' + text, /\b(STFL[-\s]?\d+)\b/i).replace(/\s/g, '-').toUpperCase();
  const title = match_(text, /(?:^|\n)\s*(\d{4,6})\s*-\s*([^\n\r]+)/i, 0);
  const titleMatch = title.match(/(\d{4,6})\s*-\s*(.+?)(?:\s+(19\d{2}|20\d{2}))?\s*$/i);
  const stockNumber = titleMatch ? titleMatch[1] : '';
  let vehicle = titleMatch ? titleMatch[2].trim() : '';
  const yearMatch = (titleMatch && titleMatch[3]) || match_(vehicle, /\b(19\d{2}|20\d{2})\b/);
  if (yearMatch) vehicle = vehicle.replace(new RegExp('\\b' + yearMatch + '\\b'), '').trim();
  const status = match_(text, /Status\s*:\s*([^\n\r]+)/i);
  const priceText = match_(text, /(?:New\s+Price|Reduced\s+Price|Price)\s*:\s*(?:AED\s*)?([\d,]+(?:\.\d+)?)/i);
  if (!stockNumber || !vehicle) return null;
  return {
    messageId: message.id,
    createTime: new Date(Number(message.internalDate || Date.now())).toISOString(),
    subject: subject,
    workflowId: workflow,
    stockNumber: stockNumber,
    vehicle: vehicle,
    year: yearMatch ? Number(yearMatch) : null,
    status: status,
    priceAed: priceText ? Number(priceText.replace(/,/g, '')) : null,
    assignee: assignee,
    text: text.slice(0, 12000)
  };
}

function messageBody_(payload) {
  if (payload.body && payload.body.data) return decode_(payload.body.data);
  const parts = payload.parts || [];
  const preferred = parts.filter(function(part) { return part.mimeType === 'text/plain'; })
    .concat(parts.filter(function(part) { return part.mimeType === 'text/html'; }));
  for (let i = 0; i < preferred.length; i++) {
    const body = messageBody_(preferred[i]);
    if (body) return body;
  }
  return '';
}

function decode_(value) {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  return Utilities.newBlob(Utilities.base64Decode(normalized)).getDataAsString('UTF-8');
}

function htmlToText_(value) {
  return String(value || '').replace(/<style[\s\S]*?<\/style>/gi, ' ').replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<br\s*\/?>/gi, '\n').replace(/<\/p>|<\/div>|<\/tr>|<\/li>/gi, '\n').replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ').replace(/&amp;/gi, '&').replace(/&lt;/gi, '<').replace(/&gt;/gi, '>')
    .replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n').trim();
}

function match_(value, expression, group) {
  const result = String(value || '').match(expression);
  return result ? String(result[group === undefined ? 1 : group] || '').trim() : '';
}

function json_(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload)).setMimeType(ContentService.MimeType.JSON);
}
