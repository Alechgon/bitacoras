/**
 * SOSER San Pablo · Respaldo y tablero
 * ------------------------------------------------------------------
 * Recibe el estado completo desde la página de GitHub Pages, lo guarda
 * en un Google Sheet y en un JSON de Drive, y lo deja visible desde
 * cualquier parte en /exec.
 *
 * Implementar:  Implementar → Nueva implementación → Aplicación web
 *   Ejecutar como:        Yo
 *   Quién tiene acceso:   Cualquier usuario  (hace falta para que la
 *                         página pueda escribir sin pedir login)
 *
 * Cada vez que cambies el código hay que crear una NUEVA versión de la
 * implementación, si no el /exec sigue sirviendo el código viejo.
 */

var PROP = PropertiesService.getScriptProperties();
var NOMBRE_SHEET = 'SOSER San Pablo · Respaldo';
var NOMBRE_JSON  = 'soser-estado.json';
var TZ = 'America/Santiago';

/* ================================================================
   ENTRADA
   ================================================================ */

function doPost(e) {
  try {
    var cuerpo = JSON.parse(e.postData.contents);
    if (cuerpo.accion === 'ping') return json({ ok: true, pong: ahora() });

    var estado = cuerpo.estado || cuerpo;
    guardarJson(estado);
    escribirHojas(estado);
    PROP.setProperty('ultimo', ahora());
    PROP.setProperty('ultimoOrigen', cuerpo.origen || 'web');

    return json({
      ok: true,
      guardado: ahora(),
      hoja: urlSheet(),
      filas: {
        programa: (estado.PLAN || []).length,
        establecimientos: (estado.ESTAB || []).length,
        correctivos: (estado.CORR || []).length,
        bitacoras: (estado.BITS || []).length,
        datacora: (estado.DC || []).length
      }
    });
  } catch (err) {
    return json({ ok: false, error: String(err && err.message || err) });
  }
}

function doGet(e) {
  var p = (e && e.parameter) || {};
  if (p.modo === 'json')    return json(leerJson() || {});
  if (p.modo === 'resumen') return json(resumen());
  if (p.modo === 'ping')    return json({ ok: true, pong: ahora(), ultimo: PROP.getProperty('ultimo') });
  return HtmlService.createHtmlOutput(tablero())
    .setTitle('SOSER San Pablo · Mantención')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/* ================================================================
   GUARDADO
   ================================================================ */

function guardarJson(estado) {
  var txt = JSON.stringify(estado);
  var id = PROP.getProperty('jsonId');
  if (id) {
    try { DriveApp.getFileById(id).setContent(txt); return; }
    catch (err) { PROP.deleteProperty('jsonId'); }
  }
  var f = DriveApp.createFile(NOMBRE_JSON, txt, MimeType.PLAIN_TEXT);
  PROP.setProperty('jsonId', f.getId());
}

function leerJson() {
  var id = PROP.getProperty('jsonId');
  if (!id) return null;
  try { return JSON.parse(DriveApp.getFileById(id).getBlob().getDataAsString()); }
  catch (err) { return null; }
}

function libro() {
  var id = PROP.getProperty('sheetId');
  if (id) { try { return SpreadsheetApp.openById(id); } catch (err) { PROP.deleteProperty('sheetId'); } }
  var ss = SpreadsheetApp.create(NOMBRE_SHEET);
  PROP.setProperty('sheetId', ss.getId());
  return ss;
}

function urlSheet() {
  var id = PROP.getProperty('sheetId');
  return id ? 'https://docs.google.com/spreadsheets/d/' + id : null;
}

function hoja(ss, nombre, cabecera, filas) {
  var h = ss.getSheetByName(nombre) || ss.insertSheet(nombre);
  h.clear();
  var datos = [cabecera].concat(filas.length ? filas : [cabecera.map(function () { return ''; })]);
  h.getRange(1, 1, datos.length, cabecera.length).setValues(datos);
  var cab = h.getRange(1, 1, 1, cabecera.length);
  cab.setFontWeight('bold').setBackground('#14532d').setFontColor('#ffffff').setWrap(true);
  h.setFrozenRows(1);
  if (datos.length > 1) h.getRange(1, 1, datos.length, cabecera.length).createFilter();
  for (var c = 1; c <= cabecera.length; c++) {
    h.autoResizeColumn(c);
    if (h.getColumnWidth(c) > 320) h.setColumnWidth(c, 320);
  }
  return h;
}

function escribirHojas(st) {
  var ss = libro();
  var ESTAB = st.ESTAB || [], PLAN = st.PLAN || [], CORR = st.CORR || [];
  var BITS = st.BITS || [], DC = st.DC || [], LOG = st.LOG || [], MENC = st.MENC || [];
  var E = {};
  ESTAB.forEach(function (x) { E[x.rbd] = x; });
  var nom = function (r) { return (E[r] || {}).nombre || ''; };
  var m = st.META || {};
  var a = calcAvance(st);

  hoja(ss, 'Resumen',
    ['Indicador', 'Valor', 'Detalle'],
    [
      ['Último respaldo', ahora(), 'Hora de Santiago'],
      ['Versión de los datos', m.version || '—', ''],
      ['Sitios de la sucursal', ESTAB.length, '60 Junaeb + 27 Junji + 6 Integra'],
      ['Meta 1 · JUNAEB con visita', a.hechoJ + ' / ' + a.junaeb,
       'Plazo ' + (m.metaJunaeb || '') + ' · cuenta cualquier visita en Datácora'],
      ['Meta 2 · Jardines con preventiva', a.hechoG + ' / ' + a.jard,
       'Plazo ' + (m.metaJardines || '') + ' · solo Plan Preventivo, con JI y SC'],
      ['Correctivos abiertos', CORR.length, 'Reportados por las supervisoras'],
      ['Visitas en el programa', PLAN.length, 'Histórico más lo planificado'],
      ['Realizadas', PLAN.filter(function (p) { return p.estado === 'realizada'; }).length, ''],
      ['Pendientes', PLAN.filter(function (p) { return p.estado === 'programada'; }).length, ''],
      ['Bitácoras con detalle', BITS.length, 'PDF leídos'],
      ['Bitácoras en Datácora', DC.length, 'Export oficial'],
      ['Aplazamientos registrados', LOG.length, '']
    ]);

  hoja(ss, 'Programa',
    ['Fecha', 'Origen', 'Clase', 'Tipo real', 'Parte', 'Bloque', 'Horario', 'Técnico', 'RBD',
     'Establecimiento', 'Institución', 'Comuna', 'Dirección', 'Supervisora', 'Puntaje',
     'Estado', 'Aplazamientos', 'Folio', 'Trabajo'],
    PLAN.filter(function (p) { return p.estado !== 'anulada'; })
      .sort(function (x, y) { return x.fecha < y.fecha ? -1 : 1; })
      .map(function (p) {
        var e = E[p.rbd] || {};
        return [p.fecha, p.origen === 'historico' ? 'Histórico' : 'Planificado', p.clase,
          p.tipoReal || '', p.parte || '', p.bloque, p.hora || '',
          ((m.tecnicos || {})[p.tec] || {}).nombre || p.tec, p.rbd, e.nombre || '',
          e.inst || '', e.comuna || '', e.dir || '', e.sup || '', p.pts || '',
          p.estado, p.aplaz || 0, p.folio || '', p.detalle || ''];
      }));

  hoja(ss, 'Establecimientos',
    ['RBD', 'Establecimiento', 'Institución', 'Dirección', 'Comuna', 'Supervisora', 'Gas',
     'Raciones', 'Bitácoras', 'Unidades', 'Puntaje', 'Cobertura', 'Preventiva 2°sem',
     'Partes levantadas', 'Fecha preventiva', 'Visitas 1er sem', 'Visitas 2°sem',
     'Correctivas 2°sem', 'Última visita', 'Desglose del puntaje'],
    ESTAB.map(function (e) {
      return [e.rbd, e.nombre, e.inst, e.dir, e.comuna, e.sup, e.gas, e.rac, e.nbit,
        (e.unidades || []).join(' + '), e.pts, e.cobertura,
        e.inst === 'Junaeb' ? 'no aplica' : (e.prevOK ? 'completa' : 'falta'),
        (e.prevPartes || []).join('+'), e.prevFecha || '', e.s1, e.s2, e.corr2 || 0,
        e.ultima || '', e.why || ''];
    }));

  hoja(ss, 'Correctivos',
    ['Puntaje', 'RBD', 'Establecimiento', 'Supervisora', 'Comuna', 'Tipo', 'Estado',
     'Reportado', 'Días abiertos', 'Prioridad', 'Agendado', 'Trabajo'],
    CORR.slice().sort(function (x, y) { return y.pts - x.pts; }).map(function (c) {
      var e = E[c.rbd] || {};
      return [c.pts, c.rbd, e.nombre || '', e.sup || '', e.comuna || '', c.crit, c.estado,
        c.freporte, c.dias, c.prio ? 'SÍ' : '', c.agendado || '', c.detalle];
    }));

  var items = [];
  BITS.forEach(function (b) {
    (b.items || []).forEach(function (i) {
      items.push([b.folio || '', b.fecha, b.rbd, b.estab || nom(b.rbd), i.categoria, i.item,
        i.ubicacion || '', i.cantidad, i.accion, i.observacion, b.tecnico || '', b.encargado || '']);
    });
  });
  hoja(ss, 'Bitácoras detalle',
    ['Folio', 'Fecha', 'RBD', 'Establecimiento', 'Categoría', 'Ítem', 'Ubicación',
     'Cantidad', 'Acción', 'Observación', 'Técnico', 'Encargado PAE'], items);

  hoja(ss, 'Datácora',
    ['Folio', 'Fecha', 'Tipo', 'RBD', 'Establecimiento', 'Institución', 'Técnico',
     'Cuenta para el conteo', 'Revisión', 'Observación'],
    DC.map(function (d) {
      return [d.folio, d.fecha, d.tipo, d.rbd, d.estab, d.inst, d.tec,
        d.cuenta ? 'SÍ' : 'NO', d.revision || '', d.det || ''];
    }));

  hoja(ss, 'Aplazamientos',
    ['Cuándo', 'RBD', 'Establecimiento', 'Veces', 'Nueva fecha', 'Motivo'],
    LOG.slice().reverse().map(function (l) {
      return [l.ts, l.rbd, nom(l.rbd), l.aplaz, l.nueva, l.motivo];
    }));

  hoja(ss, 'Reportes supervisoras',
    ['Fecha', 'Autor', 'RBD', 'Establecimiento', 'Texto'],
    MENC.map(function (x) { return [x.fecha, x.autor, x.rbd, nom(x.rbd), x.texto]; }));

  SpreadsheetApp.flush();
}

/* ================================================================
   CÁLCULO
   ================================================================ */

function esPrev(t) { return /preventiv/i.test(String(t || '')); }

function calcAvance(st) {
  var E = st.ESTAB || [], P = st.PLAN || [], DC = st.DC || [], m = st.META || {};
  var junaeb = E.filter(function (e) { return e.inst === 'Junaeb'; });
  var jard = E.filter(function (e) { return e.inst !== 'Junaeb'; });

  var okJ = {};
  DC.forEach(function (d) { if (d.cuenta) okJ[d.rbd] = 1; });
  P.forEach(function (p) {
    if (p.estado === 'realizada' && p.fecha >= (m.datacoraCorte || '2026-09-30')) okJ[p.rbd] = 1;
  });

  var partes = {};
  P.forEach(function (p) {
    if (p.estado === 'realizada' && p.fecha >= (m.corteS2 || '2026-07-01') && esPrev(p.tipoReal)) {
      partes[p.rbd] = partes[p.rbd] || {};
      partes[p.rbd][p.parte || 'JI'] = 1;
    }
  });
  DC.forEach(function (d) {
    if (d.tipo === 'Preventiva') { partes[d.rbd] = partes[d.rbd] || {}; partes[d.rbd].JI = 1; }
  });

  var hechoG = jard.filter(function (e) {
    var h = partes[e.rbd]; if (!h) return false;
    return e.nbit === 2 ? (h.JI && h.SC) : true;
  }).length;

  return {
    junaeb: junaeb.length,
    hechoJ: junaeb.filter(function (e) { return okJ[e.rbd]; }).length,
    jard: jard.length,
    hechoG: hechoG
  };
}

function resumen() {
  var st = leerJson();
  if (!st) return { ok: false, error: 'todavía no hay respaldo' };
  var a = calcAvance(st);
  var m = st.META || {};
  return {
    ok: true, ultimo: PROP.getProperty('ultimo'), version: m.version,
    metaJunaeb: { hecho: a.hechoJ, total: a.junaeb, plazo: m.metaJunaeb },
    metaJardines: { hecho: a.hechoG, total: a.jard, plazo: m.metaJardines },
    correctivos: (st.CORR || []).length,
    hoja: urlSheet()
  };
}

function ahora() {
  return Utilities.formatDate(new Date(), TZ, 'dd-MM-yyyy HH:mm');
}

function json(o) {
  return ContentService.createTextOutput(JSON.stringify(o))
    .setMimeType(ContentService.MimeType.JSON);
}

/* ================================================================
   TABLERO (lo que se ve al abrir /exec)
   ================================================================ */

function tablero() {
  var st = leerJson();
  if (!st) {
    return '<!doctype html><meta charset="utf-8"><body style="font:15px system-ui;padding:36px;color:#15211b">' +
      '<h2>Todavía no llega ningún respaldo</h2>' +
      '<p>Abre la página de mantención, anda a <b>Ajustes</b> y toca <b>Respaldar en Google</b>.</p></body>';
  }
  var a = calcAvance(st), m = st.META || {};
  var E = {}; (st.ESTAB || []).forEach(function (x) { E[x.rbd] = x; });
  var hoy = Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd');

  var delDia = (st.PLAN || []).filter(function (p) {
    return p.fecha === hoy && p.estado !== 'anulada' && p.origen !== 'historico';
  }).sort(function (x, y) { return (x.bloque || 9) - (y.bloque || 9); });

  var corr = (st.CORR || []).slice().sort(function (x, y) { return y.pts - x.pts; }).slice(0, 15);

  var pct = function (h, t) { return t ? Math.round(100 * h / t) : 0; };
  var fila = function (p) {
    var e = E[p.rbd] || {};
    return '<tr><td>' + (p.bloque >= 4 ? 'extra' : 'B' + p.bloque) + '</td>' +
      '<td>' + (((m.tecnicos || {})[p.tec] || {}).nombre || p.tec).split(' ')[0] + '</td>' +
      '<td><b>' + p.rbd + '</b></td><td>' + esc(e.nombre || '') + '</td>' +
      '<td class="d">' + esc(e.comuna || '') + '</td>' +
      '<td><span class="pill ' + (p.estado === 'realizada' ? 'ok' : 'pen') + '">' +
      (p.estado === 'realizada' ? 'listo' : 'pendiente') + '</span></td>' +
      '<td class="d">' + esc((p.detalle || '').slice(0, 120)) + '</td></tr>';
  };

  return '<!doctype html><html lang="es"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>SOSER San Pablo</title><style>' +
    ':root{--bg:#f4f6f5;--pan:#fff;--ink:#15211b;--mut:#6b7772;--lin:#dfe5e2;--grn:#14532d;--red:#b3261e;--amb:#8a6100}' +
    '@media(prefers-color-scheme:dark){:root{--bg:#10150f;--pan:#18201b;--ink:#e8efe9;--mut:#95a39b;--lin:#2b352e}}' +
    '*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Arial}' +
    'header{background:var(--grn);color:#fff;padding:14px 18px}header h1{margin:0;font-size:16px}' +
    'header div{font-size:12px;opacity:.8;margin-top:3px}' +
    'main{max-width:1100px;margin:0 auto;padding:16px}' +
    '.card{background:var(--pan);border:1px solid var(--lin);border-radius:12px;padding:16px;margin-bottom:14px}' +
    '.g2{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:700px){.g2{grid-template-columns:1fr}}' +
    'h2{font-size:15px;margin:0 0 8px}.d{color:var(--mut);font-size:12.5px}' +
    '.big{font-size:30px;font-weight:800;line-height:1.1}' +
    '.bar{height:9px;background:var(--lin);border-radius:99px;overflow:hidden;margin-top:8px}' +
    '.bar i{display:block;height:100%;background:var(--grn)}' +
    'table{width:100%;border-collapse:collapse;font-size:13px}' +
    'th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--mut);' +
    'border-bottom:2px solid var(--lin);padding:7px 6px}' +
    'td{border-bottom:1px solid var(--lin);padding:7px 6px;vertical-align:top}' +
    '.pill{padding:2px 8px;border-radius:99px;font-size:11px;font-weight:700;background:#e4f0e8;color:var(--grn)}' +
    '.pill.pen{background:#fff2cc;color:var(--amb)}.pill.gas{background:#fbe4e1;color:var(--red)}' +
    '.sc{display:inline-block;min-width:26px;text-align:center;border-radius:7px;font-weight:800;font-size:12px;padding:2px 5px}' +
    '.sc.hi{background:#fbe4e1;color:var(--red)}.sc.md{background:#fff2cc;color:var(--amb)}.sc.lo{background:#e4f0e8;color:var(--grn)}' +
    'a.btn{display:inline-block;background:var(--grn);color:#fff;text-decoration:none;padding:9px 14px;border-radius:9px;font-size:13px;font-weight:600}' +
    '.ov{overflow:auto}</style></head><body>' +
    '<header><h1>SOSER · Sucursal San Pablo</h1>' +
    '<div>Mantención PAE · 85-34-LR25 · respaldo del ' + (PROP.getProperty('ultimo') || '—') + '</div></header><main>' +

    '<div class="g2">' +
    '<div class="card"><h2>Meta 1 · JUNAEB en Datácora</h2>' +
    '<div class="d">Plazo ' + (m.metaJunaeb || '') + ' · cuenta cualquier visita</div>' +
    '<div class="big">' + a.hechoJ + ' <span class="d">de ' + a.junaeb + '</span></div>' +
    '<div class="bar"><i style="width:' + pct(a.hechoJ, a.junaeb) + '%"></i></div></div>' +
    '<div class="card"><h2>Meta 2 · Preventiva en jardines</h2>' +
    '<div class="d">Plazo ' + (m.metaJardines || '') + ' · solo Plan Preventivo</div>' +
    '<div class="big">' + a.hechoG + ' <span class="d">de ' + a.jard + '</span></div>' +
    '<div class="bar"><i style="width:' + pct(a.hechoG, a.jard) + '%"></i></div></div>' +
    '</div>' +

    '<div class="card"><h2>Hoy ' + hoy + '</h2>' +
    (delDia.length
      ? '<div class="ov"><table><tr><th>Bloque</th><th>Técnico</th><th>RBD</th><th>Establecimiento</th>' +
        '<th>Comuna</th><th>Estado</th><th>Trabajo</th></tr>' + delDia.map(fila).join('') + '</table></div>'
      : '<div class="d">No hay visitas planificadas para hoy.</div>') + '</div>' +

    '<div class="card"><h2>Correctivos abiertos (' + (st.CORR || []).length + ')</h2>' +
    '<div class="ov"><table><tr><th>Pts</th><th>RBD</th><th>Establecimiento</th><th>Supervisora</th>' +
    '<th>Tipo</th><th>Días</th><th>Agendado</th><th>Trabajo</th></tr>' +
    corr.map(function (c) {
      var e = E[c.rbd] || {};
      return '<tr><td><span class="sc ' + (c.pts >= 13 ? 'hi' : c.pts >= 9 ? 'md' : 'lo') + '">' + c.pts + '</span></td>' +
        '<td><b>' + c.rbd + '</b></td><td>' + esc(e.nombre || '') + '</td>' +
        '<td class="d">' + esc(e.sup || '') + '</td>' +
        '<td><span class="pill' + (c.crit === 'GAS' ? ' gas' : ' pen') + '">' + c.crit + '</span></td>' +
        '<td>' + c.dias + '</td><td>' + (c.agendado || '—') + '</td>' +
        '<td class="d">' + esc((c.detalle || '').slice(0, 110)) + '</td></tr>';
    }).join('') + '</table></div></div>' +

    '<div class="card"><h2>Todo el detalle</h2>' +
    '<div class="d">Programa, establecimientos, bitácoras, Datácora, aplazamientos y reportes de las supervisoras.</div>' +
    '<p style="margin:12px 0 0">' +
    (urlSheet() ? '<a class="btn" href="' + urlSheet() + '" target="_blank">Abrir la planilla</a>' : '<span class="d">La planilla se crea con el primer respaldo.</span>') +
    '</p></div>' +

    '<div class="d" style="text-align:center;padding:8px 0 24px">' +
    'Esta vista se actualiza cada vez que la página respalda. Recarga para ver lo último.</div>' +
    '</main></body></html>';
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* ================================================================
   UTILIDADES — se corren a mano desde el editor
   ================================================================ */

function verUrlPlanilla() { Logger.log(urlSheet() || 'todavía no existe'); }

function borrarTodo() {
  PROP.deleteAllProperties();
  Logger.log('Propiedades borradas. El próximo respaldo crea una planilla nueva.');
}
