/**
 * SOSER San Pablo · Respaldo, KPI y tablero
 * ------------------------------------------------------------------
 * Recibe el estado desde la página, lo deja ordenado en una planilla
 * de Google con formato, calcula los indicadores de contrato y guarda
 * un histórico acumulativo para ver la tendencia.
 *
 * Implementar:  Implementar → Nueva implementación → Aplicación web
 *   Ejecutar como:        Yo
 *   Quién tiene acceso:   Cualquier usuario
 *
 * Al cambiar el código hay que crear una VERSIÓN NUEVA de la
 * implementación; si no, /exec sigue sirviendo el código viejo.
 */

var PROP = PropertiesService.getScriptProperties();
var NOMBRE_SHEET = 'SOSER San Pablo · Mantención';
var NOMBRE_JSON  = 'soser-estado.json';
var TZ = 'America/Santiago';

var C = {
  marca:  '#14532d',
  marca2: '#1e6b3a',
  tinta:  '#10211a',
  acero:  '#5a6b64',
  linea:  '#d9e0dc',
  banda:  '#f4f7f5',
  rojo:   '#b3261e',
  rojoBg: '#fbe4e1',
  ambar:  '#8a6100',
  ambarBg:'#fff3d6',
  verde:  '#2e7d32',
  verdeBg:'#e3f1e6',
  azul:   '#1f5fb4',
  azulBg: '#e4edfa'
};

/* ================================================================
   ENTRADA
   ================================================================ */

function doPost(e) {
  try {
    var cuerpo = JSON.parse(e.postData.contents);
    if (cuerpo.accion === 'ping') return json({ ok: true, pong: ahora() });

    var estado = cuerpo.estado || cuerpo;
    guardarJson(estado);
    var k = kpis(estado);
    escribirHojas(estado, k);
    anotarHistorico(k);
    PROP.setProperty('ultimo', ahora());

    return json({
      ok: true, guardado: ahora(), hoja: urlSheet(), kpi: k,
      filas: {
        programa: (estado.PLAN || []).length,
        establecimientos: (estado.ESTAB || []).length,
        correctivos: (estado.CORR || []).length,
        bitacoras: (estado.BITS || []).length,
        datacora: (estado.DC || []).length
      }
    });
  } catch (err) {
    return json({ ok: false, error: String((err && err.message) || err) });
  }
}

function doGet(e) {
  var p = (e && e.parameter) || {};
  if (p.modo === 'json')      return json(leerJson() || {});
  if (p.modo === 'kpi')       return json(kpis(leerJson() || {}));
  if (p.modo === 'historico') return json({ ok: true, filas: historico() });
  if (p.modo === 'ping')      return json({ ok: true, pong: ahora(), ultimo: PROP.getProperty('ultimo') });
  return HtmlService.createHtmlOutput(tablero())
    .setTitle('SOSER San Pablo · Mantención')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/* ================================================================
   INDICADORES DE CONTRATO
   ================================================================ */

function esPrev(t) { return /preventiv/i.test(String(t || '')); }
function hoyISO() { return Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd'); }

function habilesEntre(desde, hasta, feriados) {
  var f = {}; (feriados || []).forEach(function (x) { f[x] = 1; });
  var d = new Date(desde + 'T12:00:00'), fin = new Date(hasta + 'T12:00:00'), n = 0;
  while (d <= fin) {
    var iso = Utilities.formatDate(d, TZ, 'yyyy-MM-dd');
    var dw = d.getDay();
    if (dw >= 1 && dw <= 5 && !f[iso]) n++;
    d.setDate(d.getDate() + 1);
  }
  return n;
}

function kpis(st) {
  var E = st.ESTAB || [], P = st.PLAN || [], DC = st.DC || [], CO = st.CORR || [], m = st.META || {};
  var hoy = hoyISO();
  var junaeb = E.filter(function (e) { return e.inst === 'Junaeb'; });
  var jard   = E.filter(function (e) { return e.inst !== 'Junaeb'; });

  // --- meta 1: JUNAEB con visita cargada en Datácora
  var okJ = {};
  DC.forEach(function (d) { if (d.cuenta) okJ[d.rbd] = 1; });
  P.forEach(function (p) {
    if (p.estado === 'realizada' && p.fecha >= (m.datacoraCorte || '2026-09-30')) okJ[p.rbd] = 1;
  });
  var hechoJ = junaeb.filter(function (e) { return okJ[e.rbd]; }).length;

  // --- meta 2: jardines con preventiva completa (JI y SC si corresponde)
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
  var completo = function (e) {
    var h = partes[e.rbd]; if (!h) return false;
    return e.nbit === 2 ? !!(h.JI && h.SC) : true;
  };
  var hechoG  = jard.filter(completo).length;
  var mediasG = jard.filter(function (e) { return !completo(e) && partes[e.rbd]; }).length;

  // --- ritmo: lo que falta contra los días hábiles que quedan
  var fer = m.feriados || [];
  var habJ = Math.max(0, habilesEntre(hoy, m.metaJunaeb || hoy, fer));
  var habG = Math.max(0, habilesEntre(hoy, m.metaJardines || hoy, fer));
  var faltaJ = junaeb.length - hechoJ, faltaG = jard.length - hechoG;
  var ritmoReqJ = habJ ? faltaJ / habJ : faltaJ;
  var ritmoReqG = habG ? faltaG / habG : faltaG;

  // ritmo real: realizadas en los últimos 10 días hábiles
  var desde = Utilities.formatDate(new Date(new Date().getTime() - 14 * 86400000), TZ, 'yyyy-MM-dd');
  var hechasRec = P.filter(function (p) {
    return p.estado === 'realizada' && p.fecha >= desde && p.fecha <= hoy && p.origen !== 'historico';
  }).length;
  var habRec = Math.max(1, habilesEntre(desde, hoy, fer));
  var ritmoReal = hechasRec / habRec;

  // --- cumplimiento: realizadas sobre programadas hasta hoy
  var vencidas = P.filter(function (p) {
    return p.origen !== 'historico' && p.estado !== 'anulada' && p.fecha <= hoy;
  });
  var cumplidas = vencidas.filter(function (p) { return p.estado === 'realizada'; }).length;
  var cumplimiento = vencidas.length ? cumplidas / vencidas.length : 1;

  // --- correctivos
  var dias = CO.map(function (c) { return c.dias || 0; });
  var prom = dias.length ? dias.reduce(function (a, b) { return a + b; }, 0) / dias.length : 0;
  var porCrit = {};
  CO.forEach(function (c) { porCrit[c.crit] = (porCrit[c.crit] || 0) + 1; });
  var porSup = {};
  var Emap = {}; E.forEach(function (x) { Emap[x.rbd] = x; });
  CO.forEach(function (c) {
    var s = (Emap[c.rbd] || {}).sup || 'Sin supervisora';
    porSup[s] = (porSup[s] || 0) + 1;
  });
  var fuera = CO.filter(function (c) { return (c.dias || 0) > 10; }).length;

  // --- aplazamientos
  var LOG = st.LOG || [];
  var dobles = P.filter(function (p) { return (p.aplaz || 0) >= 2; }).length;

  return {
    actualizado: ahora(), version: m.version || '',
    meta1: {
      nombre: 'JUNAEB en Datácora', plazo: m.metaJunaeb || '', total: junaeb.length,
      hecho: hechoJ, falta: faltaJ, pct: junaeb.length ? hechoJ / junaeb.length : 0,
      habiles: habJ, ritmoRequerido: r2(ritmoReqJ), alcanza: ritmoReal >= ritmoReqJ
    },
    meta2: {
      nombre: 'Preventiva en jardines', plazo: m.metaJardines || '', total: jard.length,
      hecho: hechoG, falta: faltaG, aMedias: mediasG,
      pct: jard.length ? hechoG / jard.length : 0,
      habiles: habG, ritmoRequerido: r2(ritmoReqG), alcanza: ritmoReal >= ritmoReqG
    },
    ritmoReal: r2(ritmoReal),
    cumplimiento: r2(cumplimiento),
    correctivos: {
      abiertos: CO.length, diasPromedio: r2(prom), sobre10dias: fuera,
      porCriticidad: porCrit, porSupervisora: porSup
    },
    visitas: {
      total: P.length,
      realizadas: P.filter(function (p) { return p.estado === 'realizada'; }).length,
      pendientes: P.filter(function (p) { return p.estado === 'programada'; }).length,
      aplazadasDosOMas: dobles, movimientos: LOG.length
    }
  };
}

function r2(x) { return Math.round(x * 100) / 100; }

/* ================================================================
   PLANILLA
   ================================================================ */

function guardarJson(estado) {
  var txt = JSON.stringify(estado);
  var id = PROP.getProperty('jsonId');
  if (id) { try { DriveApp.getFileById(id).setContent(txt); return; } catch (err) { PROP.deleteProperty('jsonId'); } }
  PROP.setProperty('jsonId', DriveApp.createFile(NOMBRE_JSON, txt, MimeType.PLAIN_TEXT).getId());
}
function leerJson() {
  var id = PROP.getProperty('jsonId'); if (!id) return null;
  try { return JSON.parse(DriveApp.getFileById(id).getBlob().getDataAsString()); }
  catch (err) { return null; }
}
function libro() {
  var id = PROP.getProperty('sheetId');
  if (id) { try { return SpreadsheetApp.openById(id); } catch (err) { PROP.deleteProperty('sheetId'); } }
  var ss = SpreadsheetApp.create(NOMBRE_SHEET);
  PROP.setProperty('sheetId', ss.getId());
  try { ss.getSheetByName('Hoja 1').setName('Panel'); } catch (e) { }
  return ss;
}
function urlSheet() {
  var id = PROP.getProperty('sheetId');
  return id ? 'https://docs.google.com/spreadsheets/d/' + id : null;
}

/** Escribe una hoja con formato de tabla: cabecera, bandas, filtro y anchos. */
function tabla(ss, nombre, cols, filas, opc) {
  opc = opc || {};
  var h = ss.getSheetByName(nombre) || ss.insertSheet(nombre);
  h.clear();
  try { h.getFilter().remove(); } catch (e) { }
  try { h.getBandings().forEach(function (b) { b.remove(); }); } catch (e) { }

  var nc = cols.length;
  var titulo = opc.titulo || nombre;
  h.getRange(1, 1, 1, nc).merge()
    .setValue(titulo)
    .setFontSize(13).setFontWeight('bold').setFontColor('#ffffff')
    .setBackground(C.marca).setVerticalAlignment('middle');
  h.setRowHeight(1, 30);
  h.getRange(2, 1, 1, nc).merge()
    .setValue(opc.sub || ('Actualizado ' + ahora()))
    .setFontSize(9).setFontColor(C.acero).setBackground(C.banda);

  h.getRange(3, 1, 1, nc).setValues([cols.map(function (c) { return c.t; })])
    .setFontWeight('bold').setFontSize(9).setFontColor('#ffffff')
    .setBackground(C.marca2).setWrap(true).setVerticalAlignment('middle');
  h.setRowHeight(3, 28);

  if (filas.length) {
    var r = h.getRange(4, 1, filas.length, nc);
    r.setValues(filas).setFontSize(10).setVerticalAlignment('top');
    r.setBorder(null, null, null, null, null, true, C.linea, SpreadsheetApp.BorderStyle.SOLID);
    try {
      h.getRange(3, 1, filas.length + 1, nc)
        .applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false);
    } catch (e) { }
    cols.forEach(function (c, i) {
      var col = h.getRange(4, i + 1, filas.length, 1);
      if (c.fmt) col.setNumberFormat(c.fmt);
      if (c.al) col.setHorizontalAlignment(c.al);
      if (c.mono) col.setFontFamily('Roboto Mono');
      if (c.wrap) col.setWrap(true);
    });
    h.getRange(3, 1, filas.length + 1, nc).createFilter();
  }
  h.setFrozenRows(3);
  if (opc.congelarCol) h.setFrozenColumns(opc.congelarCol);
  cols.forEach(function (c, i) { h.setColumnWidth(i + 1, c.w || 110); });
  h.setHiddenGridlines(true);
  return h;
}

function escribirHojas(st, k) {
  var ss = libro();
  var E = {}; (st.ESTAB || []).forEach(function (x) { E[x.rbd] = x; });
  var nom = function (r) { return (E[r] || {}).nombre || ''; };
  var m = st.META || {};
  var tec = function (t) { return ((m.tecnicos || {})[t] || {}).nombre || t; };

  panel(ss, st, k);

  // ---------- Programa ----------
  tabla(ss, 'Programa', [
    { t: 'Fecha', w: 92, fmt: 'dd-mmm-yyyy', al: 'center' },
    { t: 'Origen', w: 86, al: 'center' },
    { t: 'Clase', w: 150 },
    { t: 'Tipo real', w: 92, al: 'center' },
    { t: 'Parte', w: 56, al: 'center' },
    { t: 'Bloque', w: 56, al: 'center' },
    { t: 'Horario', w: 96, al: 'center', mono: true },
    { t: 'Técnico', w: 150 },
    { t: 'RBD', w: 70, al: 'center', mono: true },
    { t: 'Establecimiento', w: 230 },
    { t: 'Inst.', w: 66, al: 'center' },
    { t: 'Comuna', w: 118 },
    { t: 'Dirección', w: 190 },
    { t: 'Supervisora', w: 140 },
    { t: 'Pts', w: 48, al: 'center' },
    { t: 'Estado', w: 92, al: 'center' },
    { t: 'Aplaz.', w: 56, al: 'center' },
    { t: 'Folio', w: 72, al: 'center', mono: true },
    { t: 'Trabajo', w: 340, wrap: true }
  ], (st.PLAN || []).filter(function (p) { return p.estado !== 'anulada'; })
    .sort(function (x, y) { return x.fecha < y.fecha ? -1 : 1; })
    .map(function (p) {
      var e = E[p.rbd] || {};
      return [fecha(p.fecha), p.origen === 'historico' ? 'Histórico' : 'Plan', p.clase,
        p.tipoReal || '', p.parte || '', 'B' + p.bloque, p.hora || '', tec(p.tec),
        p.rbd, e.nombre || '', e.inst || '', e.comuna || '', e.dir || '', e.sup || '',
        p.pts || '', p.estado, p.aplaz || 0, p.folio || '', p.detalle || ''];
    }), { titulo: 'Programa de visitas', congelarCol: 1,
          sub: 'Histórico y planificado. Una fila por visita · ' + ahora() });
  pintarEstado(ss.getSheetByName('Programa'), 16);

  // ---------- Establecimientos ----------
  tabla(ss, 'Establecimientos', [
    { t: 'RBD', w: 70, al: 'center', mono: true },
    { t: 'Establecimiento', w: 240 },
    { t: 'Inst.', w: 66, al: 'center' },
    { t: 'Dirección', w: 200 },
    { t: 'Comuna', w: 120 },
    { t: 'Supervisora', w: 140 },
    { t: 'Tipo de gas', w: 120 },
    { t: 'Raciones', w: 74, al: 'center', fmt: '#,##0' },
    { t: 'Bitácoras', w: 70, al: 'center' },
    { t: 'Pts', w: 48, al: 'center' },
    { t: 'Cobertura', w: 120, al: 'center' },
    { t: 'Preventiva 2°sem', w: 118, al: 'center' },
    { t: 'Partes', w: 70, al: 'center' },
    { t: '1er sem', w: 62, al: 'center' },
    { t: '2° sem', w: 62, al: 'center' },
    { t: 'Correctivas', w: 76, al: 'center' },
    { t: 'Última visita', w: 96, al: 'center' },
    { t: 'Desglose del puntaje', w: 330, wrap: true }
  ], (st.ESTAB || []).slice().sort(function (a, b) { return b.pts - a.pts; }).map(function (e) {
    return [e.rbd, e.nombre, e.inst, e.dir, e.comuna, e.sup, e.gas, e.rac, e.nbit, e.pts,
      e.cobertura, e.inst === 'Junaeb' ? '—' : (e.prevOK ? 'Completa' : 'Falta'),
      (e.prevPartes || []).join('+'), e.s1, e.s2, e.corr2 || 0, e.ultima || '', e.why || ''];
  }), { titulo: 'Establecimientos de la sucursal', congelarCol: 2,
        sub: 'Ordenados por criticidad · ' + ahora() });
  var hE = ss.getSheetByName('Establecimientos');
  escalaPuntaje(hE, 10);
  reglaTexto(hE, 11, 'SIN VISITA', C.rojoBg, C.rojo);
  reglaTexto(hE, 12, 'Falta', C.ambarBg, C.ambar);
  reglaTexto(hE, 12, 'Completa', C.verdeBg, C.verde);

  // ---------- Correctivos ----------
  tabla(ss, 'Correctivos', [
    { t: 'Pts', w: 48, al: 'center' },
    { t: 'RBD', w: 70, al: 'center', mono: true },
    { t: 'Establecimiento', w: 230 },
    { t: 'Supervisora', w: 140 },
    { t: 'Comuna', w: 118 },
    { t: 'Tipo', w: 72, al: 'center' },
    { t: 'Estado', w: 96, al: 'center' },
    { t: 'Reportado', w: 96, fmt: 'dd-mmm-yyyy', al: 'center' },
    { t: 'Días', w: 54, al: 'center' },
    { t: 'Prioridad', w: 72, al: 'center' },
    { t: 'Agendado', w: 96, fmt: 'dd-mmm-yyyy', al: 'center' },
    { t: 'Trabajo comprometido', w: 400, wrap: true }
  ], (st.CORR || []).slice().sort(function (x, y) { return y.pts - x.pts; }).map(function (c) {
    var e = E[c.rbd] || {};
    return [c.pts, c.rbd, e.nombre || '', e.sup || '', e.comuna || '', c.crit, c.estado,
      fecha(c.freporte), c.dias, c.prio ? 'SÍ' : '', fecha(c.agendado), c.detalle];
  }), { titulo: 'Requerimientos de las supervisoras',
        sub: 'Abiertos, ordenados por criticidad · ningún requerimiento debe superar 10 días · ' + ahora() });
  var hC = ss.getSheetByName('Correctivos');
  escalaPuntaje(hC, 1);
  reglaTexto(hC, 6, 'GAS', C.rojoBg, C.rojo);
  reglaMayor(hC, 9, 10, C.rojoBg, C.rojo);

  // ---------- Bitácoras ----------
  var items = [];
  (st.BITS || []).forEach(function (b) {
    (b.items || []).forEach(function (i) {
      items.push([b.folio || '', fecha(b.fecha), b.rbd, b.estab || nom(b.rbd), i.categoria,
        i.item, i.ubicacion || '', i.cantidad, i.accion, i.observacion, b.tecnico || '', b.encargado || '']);
    });
  });
  tabla(ss, 'Bitácoras', [
    { t: 'Folio', w: 72, al: 'center', mono: true },
    { t: 'Fecha', w: 92, fmt: 'dd-mmm-yyyy', al: 'center' },
    { t: 'RBD', w: 70, al: 'center', mono: true },
    { t: 'Establecimiento', w: 220 },
    { t: 'Categoría', w: 110, al: 'center' },
    { t: 'Ítem revisado', w: 230 },
    { t: 'Ubicación', w: 90, al: 'center' },
    { t: 'Cantidad', w: 70, al: 'center' },
    { t: 'Acción', w: 100, al: 'center' },
    { t: 'Observación', w: 380, wrap: true },
    { t: 'Técnico', w: 150 },
    { t: 'Encargado PAE', w: 150 }
  ], items, { titulo: 'Bitácoras · detalle por ítem',
              sub: 'Un ítem revisado por fila, leído de los PDF · ' + ahora() });

  // ---------- Datácora ----------
  tabla(ss, 'Datácora', [
    { t: 'Folio', w: 72, al: 'center', mono: true },
    { t: 'Fecha', w: 92, fmt: 'dd-mmm-yyyy', al: 'center' },
    { t: 'Tipo de visita', w: 120, al: 'center' },
    { t: 'RBD', w: 70, al: 'center', mono: true },
    { t: 'Establecimiento', w: 230 },
    { t: 'Inst.', w: 70, al: 'center' },
    { t: 'Técnico', w: 150 },
    { t: 'Cuenta', w: 70, al: 'center' },
    { t: 'Revisión', w: 140 },
    { t: 'Observación', w: 380, wrap: true }
  ], (st.DC || []).map(function (d) {
    return [d.folio, fecha(d.fecha), d.tipo, d.rbd, d.estab, d.inst, d.tec,
      d.cuenta ? 'SÍ' : 'NO', d.revision || '', d.det || ''];
  }), { titulo: 'Bitácoras cargadas en Datácora',
        sub: 'En JUNAEB cuenta cualquier visita; en jardines solo la preventiva · ' + ahora() });
  var hD = ss.getSheetByName('Datácora');
  reglaTexto(hD, 8, 'NO', C.ambarBg, C.ambar);
  reglaTexto(hD, 3, 'Plan Preventivo Mantención', C.verdeBg, C.verde);

  // ---------- Movimientos ----------
  tabla(ss, 'Movimientos', [
    { t: 'Cuándo', w: 140, al: 'center' },
    { t: 'RBD', w: 70, al: 'center', mono: true },
    { t: 'Establecimiento', w: 230 },
    { t: 'Veces aplazada', w: 92, al: 'center' },
    { t: 'Nueva fecha', w: 100, al: 'center' },
    { t: 'Motivo', w: 460, wrap: true }
  ], (st.LOG || []).slice().reverse().map(function (l) {
    return [String(l.ts || '').slice(0, 16).replace('T', ' '), l.rbd, nom(l.rbd),
      l.aplaz, l.nueva, l.motivo];
  }), { titulo: 'Aplazamientos y cambios',
        sub: 'Un aplazamiento sin autorización; el segundo lo autoriza el encargado · ' + ahora() });
  reglaMayor(ss.getSheetByName('Movimientos'), 4, 1, C.rojoBg, C.rojo);

  // ---------- Reportes ----------
  tabla(ss, 'Reportes supervisoras', [
    { t: 'Fecha', w: 92, fmt: 'dd-mmm-yyyy', al: 'center' },
    { t: 'Quién lo reportó', w: 180 },
    { t: 'RBD', w: 70, al: 'center', mono: true },
    { t: 'Establecimiento', w: 230 },
    { t: 'Lo que dijo', w: 560, wrap: true }
  ], (st.MENC || []).map(function (x) {
    return [fecha(x.fecha), x.autor, x.rbd, nom(x.rbd), x.texto];
  }), { titulo: 'Lo reportado en el grupo', sub: 'Menciones del chat de supervisoras · ' + ahora() });

  SpreadsheetApp.flush();
}

function fecha(iso) {
  if (!iso) return '';
  var p = String(iso).split('-');
  if (p.length !== 3) return iso;
  return new Date(+p[0], +p[1] - 1, +p[2]);
}

function reglaTexto(h, col, texto, bg, fg) {
  if (!h || h.getLastRow() < 4) return;
  var r = h.getRange(4, col, h.getLastRow() - 3, 1);
  var reglas = h.getConditionalFormatRules();
  reglas.push(SpreadsheetApp.newConditionalFormatRule()
    .whenTextContains(texto).setBackground(bg).setFontColor(fg).setRanges([r]).build());
  h.setConditionalFormatRules(reglas);
}
function reglaMayor(h, col, n, bg, fg) {
  if (!h || h.getLastRow() < 4) return;
  var r = h.getRange(4, col, h.getLastRow() - 3, 1);
  var reglas = h.getConditionalFormatRules();
  reglas.push(SpreadsheetApp.newConditionalFormatRule()
    .whenNumberGreaterThan(n).setBackground(bg).setFontColor(fg).setRanges([r]).build());
  h.setConditionalFormatRules(reglas);
}
function escalaPuntaje(h, col) {
  if (!h || h.getLastRow() < 4) return;
  var r = h.getRange(4, col, h.getLastRow() - 3, 1);
  var reglas = h.getConditionalFormatRules();
  reglas.push(SpreadsheetApp.newConditionalFormatRule()
    .setGradientMinpointWithValue(C.verdeBg, SpreadsheetApp.InterpolationType.NUMBER, '1')
    .setGradientMidpointWithValue(C.ambarBg, SpreadsheetApp.InterpolationType.NUMBER, '10')
    .setGradientMaxpointWithValue(C.rojoBg, SpreadsheetApp.InterpolationType.NUMBER, '20')
    .setRanges([r]).build());
  h.setConditionalFormatRules(reglas);
}
function pintarEstado(h, col) {
  reglaTexto(h, col, 'realizada', C.verdeBg, C.verde);
  reglaTexto(h, col, 'programada', C.ambarBg, C.ambar);
  reglaTexto(h, col, 'Sin acceso', C.rojoBg, C.rojo);
}

/* ---------- Panel de indicadores ---------- */

function panel(ss, st, k) {
  var h = ss.getSheetByName('Panel') || ss.insertSheet('Panel', 0);
  h.clear();
  try { h.getConditionalFormatRules().length && h.setConditionalFormatRules([]); } catch (e) { }
  ss.setActiveSheet(h); ss.moveActiveSheet(1);

  h.getRange('A1:H1').merge().setValue('SOSER · Sucursal San Pablo · Mantención PAE')
    .setFontSize(16).setFontWeight('bold').setFontColor('#ffffff').setBackground(C.marca)
    .setVerticalAlignment('middle');
  h.setRowHeight(1, 38);
  h.getRange('A2:H2').merge()
    .setValue('Licitación 85-34-LR25 · respaldo del ' + ahora() + ' · versión ' + (k.version || '—'))
    .setFontSize(9).setFontColor(C.acero).setBackground(C.banda);

  var filas = [
    ['', '', '', '', '', '', '', ''],
    ['METAS DE CONTRATO', '', '', '', '', '', '', ''],
    ['Meta', 'Plazo', 'Avance', 'Total', '% cumplido', 'Faltan', 'Días hábiles', 'Visitas/día que exige'],
    [k.meta1.nombre, k.meta1.plazo, k.meta1.hecho, k.meta1.total, k.meta1.pct, k.meta1.falta,
      k.meta1.habiles, k.meta1.ritmoRequerido],
    [k.meta2.nombre, k.meta2.plazo, k.meta2.hecho, k.meta2.total, k.meta2.pct, k.meta2.falta,
      k.meta2.habiles, k.meta2.ritmoRequerido],
    ['', '', '', '', '', '', '', ''],
    ['RITMO Y CUMPLIMIENTO', '', '', '', '', '', '', ''],
    ['Indicador', 'Valor', 'Lectura', '', '', '', '', ''],
    ['Visitas por día hábil (últimas 2 semanas)', k.ritmoReal,
      k.ritmoReal >= k.meta1.ritmoRequerido ? 'Alcanza para la meta de octubre' : 'Por debajo de lo que exige octubre', '', '', '', '', ''],
    ['Cumplimiento de lo programado', k.cumplimiento,
      k.cumplimiento >= 0.9 ? 'Al día' : 'Hay programación sin ejecutar', '', '', '', '', ''],
    ['Jardines con preventiva a medias', k.meta2.aMedias, 'Tienen el jardín pero falta la sala cuna', '', '', '', '', ''],
    ['', '', '', '', '', '', '', ''],
    ['REQUERIMIENTOS DE LAS SUPERVISORAS', '', '', '', '', '', '', ''],
    ['Indicador', 'Valor', 'Lectura', '', '', '', '', ''],
    ['Abiertos', k.correctivos.abiertos, 'Reportados y sin cerrar', '', '', '', '', ''],
    ['Días promedio abiertos', k.correctivos.diasPromedio, 'Desde que lo reportaron', '', '', '', '', ''],
    ['Sobre 10 días', k.correctivos.sobre10dias,
      k.correctivos.sobre10dias ? 'Fuera del compromiso' : 'Todos dentro del compromiso', '', '', '', '', ''],
    ['', '', '', '', '', '', '', ''],
    ['Por criticidad', '', '', '', '', '', '', '']
  ];
  Object.keys(k.correctivos.porCriticidad).sort().forEach(function (c) {
    filas.push([c, k.correctivos.porCriticidad[c], '', '', '', '', '', '']);
  });
  filas.push(['', '', '', '', '', '', '', '']);
  filas.push(['Por supervisora', '', '', '', '', '', '', '']);
  Object.keys(k.correctivos.porSupervisora).sort().forEach(function (s) {
    filas.push([s, k.correctivos.porSupervisora[s], '', '', '', '', '', '']);
  });
  filas.push(['', '', '', '', '', '', '', '']);
  filas.push(['VISITAS', '', '', '', '', '', '', '']);
  filas.push(['En el programa', k.visitas.total, '', '', '', '', '', '']);
  filas.push(['Realizadas', k.visitas.realizadas, '', '', '', '', '', '']);
  filas.push(['Pendientes', k.visitas.pendientes, '', '', '', '', '', '']);
  filas.push(['Con dos aplazamientos o más', k.visitas.aplazadasDosOMas,
    k.visitas.aplazadasDosOMas ? 'Necesitan tu autorización' : '', '', '', '', '', '']);

  h.getRange(3, 1, filas.length, 8).setValues(filas).setFontSize(10);

  // títulos de sección y cabeceras
  for (var i = 0; i < filas.length; i++) {
    var f = filas[i], r = 3 + i;
    var esTitulo = f[0] && f[0] === String(f[0]).toUpperCase() && f[0].length > 3 && !f[1];
    var esCab = f[0] === 'Meta' || f[0] === 'Indicador';
    if (esTitulo) {
      h.getRange(r, 1, 1, 8).merge().setFontWeight('bold').setFontSize(11)
        .setFontColor(C.marca).setBackground(C.banda);
      h.setRowHeight(r, 26);
    } else if (esCab) {
      h.getRange(r, 1, 1, 8).setFontWeight('bold').setFontSize(9)
        .setFontColor('#ffffff').setBackground(C.marca2);
    }
  }
  h.getRange(6, 5, 2, 1).setNumberFormat('0.0%');
  h.getRange(6, 8, 2, 1).setNumberFormat('0.00');
  h.getRange(13, 2, 1, 1).setNumberFormat('0.0%');
  h.getRange(6, 2, 2, 1).setNumberFormat('dd-mmm-yyyy');

  [230, 110, 90, 80, 100, 80, 100, 160].forEach(function (w, i) { h.setColumnWidth(i + 1, w); });
  h.setHiddenGridlines(true);
  h.setFrozenRows(2);
}

/* ---------- Histórico acumulativo ---------- */

function anotarHistorico(k) {
  var ss = libro();
  var h = ss.getSheetByName('Histórico');
  if (!h) {
    h = ss.insertSheet('Histórico');
    h.getRange(1, 1, 1, 10).setValues([['Fecha y hora', 'JUNAEB hecho', 'JUNAEB total',
      '% JUNAEB', 'Jardines hecho', 'Jardines total', '% jardines', 'Correctivos abiertos',
      'Ritmo real', 'Cumplimiento']])
      .setFontWeight('bold').setFontSize(9).setFontColor('#ffffff').setBackground(C.marca2);
    h.setFrozenRows(1);
    [140, 100, 100, 90, 100, 100, 90, 120, 90, 110]
      .forEach(function (w, i) { h.setColumnWidth(i + 1, w); });
    h.setHiddenGridlines(true);
  }
  h.appendRow([ahora(), k.meta1.hecho, k.meta1.total, k.meta1.pct,
    k.meta2.hecho, k.meta2.total, k.meta2.pct, k.correctivos.abiertos,
    k.ritmoReal, k.cumplimiento]);
  var n = h.getLastRow();
  h.getRange(n, 4).setNumberFormat('0.0%');
  h.getRange(n, 7).setNumberFormat('0.0%');
  h.getRange(n, 10).setNumberFormat('0.0%');
}

function historico() {
  var ss = libro(), h = ss.getSheetByName('Histórico');
  if (!h || h.getLastRow() < 2) return [];
  var v = h.getRange(2, 1, h.getLastRow() - 1, 10).getValues();
  return v.map(function (r) {
    return { ts: r[0], junaeb: r[1], junaebTotal: r[2], pctJunaeb: r[3],
      jard: r[4], jardTotal: r[5], pctJard: r[6], correctivos: r[7],
      ritmo: r[8], cumplimiento: r[9] };
  });
}

function ahora() { return Utilities.formatDate(new Date(), TZ, 'dd-MM-yyyy HH:mm'); }
function json(o) {
  return ContentService.createTextOutput(JSON.stringify(o))
    .setMimeType(ContentService.MimeType.JSON);
}
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* ================================================================
   TABLERO WEB
   ================================================================ */

function tablero() {
  var st = leerJson();
  if (!st) {
    return '<!doctype html><meta charset="utf-8">' +
      '<body style="font:15px ui-sans-serif,system-ui;padding:40px;max-width:40em;color:#10211a">' +
      '<h2 style="margin:0 0 10px">Todavía no llega ningún respaldo</h2>' +
      '<p>Abre el panel de mantención, entra a <b>Ajustes</b> y toca <b>Respaldar en Google</b>.</p></body>';
  }
  var k = kpis(st), m = st.META || {};
  var E = {}; (st.ESTAB || []).forEach(function (x) { E[x.rbd] = x; });
  var hoy = hoyISO();
  var hist = historico().slice(-14);

  var delDia = (st.PLAN || []).filter(function (p) {
    return p.fecha === hoy && p.estado !== 'anulada' && p.origen !== 'historico';
  }).sort(function (x, y) { return (x.bloque || 9) - (y.bloque || 9); });

  var corr = (st.CORR || []).slice().sort(function (x, y) { return y.pts - x.pts; }).slice(0, 12);
  var pct = function (x) { return Math.round(x * 100); };

  function meta(mk, color) {
    var al = mk.ritmoRequerido <= k.ritmoReal;
    return '<article class="meta"><div class="bar-top" style="background:' + color + '"></div>' +
      '<h3>' + esc(mk.nombre) + '</h3>' +
      '<p class="lede">Plazo ' + esc(mk.plazo) + ' · quedan ' + mk.habiles + ' días hábiles</p>' +
      '<div class="cifra"><b>' + mk.hecho + '</b><span>de ' + mk.total + '</span></div>' +
      '<div class="riel"><i style="width:' + pct(mk.pct) + '%;background:' + color + '"></i></div>' +
      '<dl><div><dt>Faltan</dt><dd>' + mk.falta + '</dd></div>' +
      '<div><dt>Exige</dt><dd>' + mk.ritmoRequerido.toFixed(1) + '/día</dd></div>' +
      '<div><dt>Vas a</dt><dd class="' + (al ? 'ok' : 'alerta') + '">' + k.ritmoReal.toFixed(1) + '/día</dd></div></dl>' +
      '</article>';
  }

  function chispa(campo) {
    if (hist.length < 2) return '';
    var v = hist.map(function (r) { return +r[campo] || 0; });
    var mx = Math.max.apply(null, v) || 1;
    var w = 150, hh = 32, paso = w / (v.length - 1);
    var d = v.map(function (y, i) {
      return (i ? 'L' : 'M') + (i * paso).toFixed(1) + ' ' + (hh - (y / mx) * (hh - 4)).toFixed(1);
    }).join(' ');
    return '<svg viewBox="0 0 ' + w + ' ' + hh + '" width="150" height="32" aria-hidden="true">' +
      '<path d="' + d + '" fill="none" stroke="' + C.marca2 + '" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>';
  }

  return '<!doctype html><html lang="es"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>SOSER San Pablo · Mantención</title>' +
    '<link rel="preconnect" href="https://fonts.googleapis.com">' +
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' +
    '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&' +
    'family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">' +
    '<style>' +
    ':root{--papel:#f5f6f6;--panel:#fff;--tinta:#10211a;--acero:#5a6b64;--linea:#dde4e0;' +
    '--marca:#14532d;--marca2:#1e6b3a;--rojo:#b3261e;--ambar:#8a6100;--azul:#1f5fb4;--verde:#2e7d32}' +
    '@media(prefers-color-scheme:dark){:root{--papel:#0e1511;--panel:#161d19;--tinta:#e7ede9;' +
    '--acero:#8ea096;--linea:#28332d;--marca:#1e6b3a;--marca2:#2f8a4e}}' +
    '*{box-sizing:border-box}' +
    'body{margin:0;background:var(--papel);color:var(--tinta);' +
    "font:15px/1.55 'IBM Plex Sans',ui-sans-serif,system-ui,sans-serif;-webkit-font-smoothing:antialiased}" +
    'header{background:var(--marca);color:#fff;padding:20px 22px}' +
    '.wrap{max-width:1080px;margin:0 auto}' +
    'header h1{margin:0;font-size:17px;font-weight:600;letter-spacing:-.01em}' +
    'header p{margin:4px 0 0;font-size:12.5px;opacity:.78;' +
    "font-family:'IBM Plex Mono',monospace}" +
    'main{max-width:1080px;margin:0 auto;padding:22px}' +
    'section{margin-bottom:26px}' +
    'h2{font-size:12px;font-weight:600;letter-spacing:.02em;color:var(--acero);' +
    'margin:0 0 10px;padding-bottom:7px;border-bottom:1px solid var(--linea)}' +
    '.duo{display:grid;grid-template-columns:1fr 1fr;gap:16px}' +
    '@media(max-width:720px){.duo{grid-template-columns:1fr}}' +
    '.meta{background:var(--panel);border:1px solid var(--linea);border-radius:5px;' +
    'padding:0 18px 16px;position:relative;overflow:hidden}' +
    '.bar-top{position:absolute;inset:0 0 auto 0;height:3px}' +
    '.meta h3{margin:18px 0 2px;font-size:15px;font-weight:600}' +
    '.lede{margin:0;font-size:12.5px;color:var(--acero)}' +
    '.cifra{display:flex;align-items:baseline;gap:8px;margin:14px 0 8px}' +
    ".cifra b{font-family:'IBM Plex Mono',monospace;font-size:42px;font-weight:600;line-height:1}" +
    '.cifra span{font-size:13px;color:var(--acero)}' +
    '.riel{height:6px;background:var(--linea);border-radius:99px;overflow:hidden}' +
    '.riel i{display:block;height:100%}' +
    'dl{display:flex;gap:26px;margin:14px 0 0}' +
    'dl dt{font-size:11.5px;color:var(--acero);margin:0}' +
    "dl dd{margin:2px 0 0;font-family:'IBM Plex Mono',monospace;font-size:15px;font-weight:600}" +
    'dd.ok{color:var(--verde)}dd.alerta{color:var(--rojo)}' +
    '.tira{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;' +
    'background:var(--linea);border:1px solid var(--linea);border-radius:5px;overflow:hidden}' +
    '.tira div{background:var(--panel);padding:13px 15px}' +
    ".tira b{display:block;font-family:'IBM Plex Mono',monospace;font-size:24px;font-weight:600;line-height:1.2}" +
    '.tira span{font-size:11.5px;color:var(--acero)}' +
    '.caja{background:var(--panel);border:1px solid var(--linea);border-radius:5px;overflow:hidden}' +
    '.ov{overflow-x:auto}' +
    'table{width:100%;border-collapse:collapse;font-size:13px}' +
    'th{text-align:left;font-size:11px;font-weight:600;color:var(--acero);' +
    'padding:10px 12px;border-bottom:1px solid var(--linea);white-space:nowrap}' +
    'td{padding:9px 12px;border-bottom:1px solid var(--linea);vertical-align:top}' +
    'tr:last-child td{border-bottom:0}' +
    ".mono{font-family:'IBM Plex Mono',monospace;font-weight:600}" +
    '.mut{color:var(--acero);font-size:12.5px}' +
    '.tag{display:inline-block;padding:1px 8px;border-radius:3px;font-size:11px;font-weight:600}' +
    '.t-ok{background:#e3f1e6;color:#2e7d32}.t-pen{background:#fff3d6;color:#8a6100}' +
    '.t-gas{background:#fbe4e1;color:#b3261e}' +
    '@media(prefers-color-scheme:dark){.t-ok{background:#1b3022;color:#8fd3a3}' +
    '.t-pen{background:#33290f;color:#e4bd6a}.t-gas{background:#3a1f1c;color:#e89a93}}' +
    ".sc{display:inline-block;min-width:26px;text-align:center;border-radius:3px;" +
    "font-family:'IBM Plex Mono',monospace;font-weight:600;font-size:12px;padding:1px 5px}" +
    '.vacio{padding:22px;color:var(--acero);font-size:13.5px}' +
    'a.btn{display:inline-block;background:var(--marca);color:#fff;text-decoration:none;' +
    'padding:10px 16px;border-radius:4px;font-size:13.5px;font-weight:600}' +
    'a.btn:focus-visible{outline:3px solid var(--marca2);outline-offset:2px}' +
    'footer{text-align:center;color:var(--acero);font-size:12px;padding:10px 0 30px}' +
    '</style></head><body>' +

    '<header><div class="wrap"><h1>SOSER · Sucursal San Pablo</h1>' +
    '<p>Mantención PAE · 85-34-LR25 · respaldo ' + esc(PROP.getProperty('ultimo') || '—') + '</p></div></header>' +
    '<main>' +

    '<section><h2>Metas de contrato</h2><div class="duo">' +
    meta(k.meta1, C.marca2) + meta(k.meta2, C.azul) + '</div></section>' +

    '<section><h2>Ritmo y requerimientos</h2><div class="tira">' +
    '<div><b>' + k.ritmoReal.toFixed(1) + '</b><span>visitas por día hábil</span>' + chispa('ritmo') + '</div>' +
    '<div><b>' + pct(k.cumplimiento) + '%</b><span>de lo programado, ejecutado</span></div>' +
    '<div><b>' + k.correctivos.abiertos + '</b><span>requerimientos abiertos</span>' + chispa('correctivos') + '</div>' +
    '<div><b>' + k.correctivos.diasPromedio.toFixed(0) + '</b><span>días promedio abiertos</span></div>' +
    '<div><b>' + k.correctivos.sobre10dias + '</b><span>sobre los 10 días</span></div>' +
    '<div><b>' + k.meta2.aMedias + '</b><span>jardines sin la sala cuna</span></div>' +
    '</div></section>' +

    '<section><h2>Hoy ' + hoy + '</h2><div class="caja">' +
    (delDia.length
      ? '<div class="ov"><table><thead><tr><th>Bloque</th><th>Técnico</th><th>RBD</th>' +
        '<th>Establecimiento</th><th>Comuna</th><th>Estado</th><th>Trabajo</th></tr></thead><tbody>' +
        delDia.map(function (p) {
          var e = E[p.rbd] || {};
          return '<tr><td class="mono">' + (p.bloque >= 4 ? 'extra' : 'B' + p.bloque) + '</td>' +
            '<td>' + esc((((m.tecnicos || {})[p.tec] || {}).nombre || p.tec).split(' ')[0]) + '</td>' +
            '<td class="mono">' + p.rbd + '</td><td>' + esc(e.nombre || '') + '</td>' +
            '<td class="mut">' + esc(e.comuna || '') + '</td>' +
            '<td><span class="tag ' + (p.estado === 'realizada' ? 't-ok' : 't-pen') + '">' +
            (p.estado === 'realizada' ? 'listo' : 'pendiente') + '</span></td>' +
            '<td class="mut">' + esc((p.detalle || '').slice(0, 120)) + '</td></tr>';
        }).join('') + '</tbody></table></div>'
      : '<p class="vacio">No hay visitas planificadas para hoy.</p>') + '</div></section>' +

    '<section><h2>Requerimientos abiertos · ' + (st.CORR || []).length + '</h2><div class="caja"><div class="ov">' +
    '<table><thead><tr><th>Pts</th><th>RBD</th><th>Establecimiento</th><th>Supervisora</th>' +
    '<th>Tipo</th><th>Días</th><th>Agendado</th><th>Trabajo</th></tr></thead><tbody>' +
    corr.map(function (c) {
      var e = E[c.rbd] || {};
      var cl = c.pts >= 13 ? 't-gas' : c.pts >= 9 ? 't-pen' : 't-ok';
      return '<tr><td><span class="sc ' + cl + '">' + c.pts + '</span></td>' +
        '<td class="mono">' + c.rbd + '</td><td>' + esc(e.nombre || '') + '</td>' +
        '<td class="mut">' + esc(e.sup || '') + '</td>' +
        '<td><span class="tag ' + (c.crit === 'GAS' ? 't-gas' : 't-pen') + '">' + esc(c.crit) + '</span></td>' +
        '<td class="mono">' + c.dias + '</td><td class="mono">' + esc(c.agendado || '—') + '</td>' +
        '<td class="mut">' + esc((c.detalle || '').slice(0, 110)) + '</td></tr>';
    }).join('') + '</tbody></table></div></div></section>' +

    '<section><h2>Todo el detalle</h2><div class="caja" style="padding:18px">' +
    '<p style="margin:0 0 14px;font-size:13.5px;color:var(--acero)">Programa, establecimientos, ' +
    'bitácoras, Datácora, movimientos y lo reportado por las supervisoras, con el histórico de cada respaldo.</p>' +
    (urlSheet() ? '<a class="btn" href="' + urlSheet() + '" target="_blank" rel="noopener">Abrir la planilla</a>'
                : '<span class="mut">La planilla se crea con el primer respaldo.</span>') +
    '</div></section>' +

    '<footer>Se actualiza con cada respaldo del panel. Recarga para ver lo último.</footer>' +
    '</main></body></html>';
}

/* ================================================================
   UTILIDADES — se corren a mano desde el editor
   ================================================================ */

function verUrlPlanilla() { Logger.log(urlSheet() || 'todavía no existe'); }
function borrarTodo() {
  PROP.deleteAllProperties();
  Logger.log('Listo. El próximo respaldo crea una planilla nueva.');
}
