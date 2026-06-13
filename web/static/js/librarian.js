// Bib — pixel art librarian mascot  (16 × 23 cells, PX = 6 → 96 × 138 px)
(function () {
'use strict';

// ── Canvas dimensions ──────────────────────────────────────────────────────
const PX = 6, W = 16, H = 23;

// ── Palette ────────────────────────────────────────────────────────────────
const __ = null;
const HA = '#3D1C0A'; // dark hair
const hm = '#6B3A1F'; // hair mid
const SK = '#FBCFA0'; // skin light
const sk = '#C8724A'; // skin shadow / mouth
const rx = '#F5A898'; // blush
const EW = '#FAFAFA'; // eye white
const EP = '#1C1C1C'; // pupil
const GL = '#2A2A2A'; // glasses frame
const WS = '#F8FAFC'; // white shirt
const JB = '#1E3A8A'; // jacket dark blue
const jm = '#2554C7'; // jacket highlight
const BO = '#7F1D1D'; // book cover dark
const bm = '#991B1B'; // book cover mid
const BP = '#FEF9C3'; // book pages cream
const TI = '#DC2626'; // tie red
const PN = '#1F2937'; // pants
const pm = '#374151'; // pants gap
const SH = '#0F172A'; // shoes
const sh = '#1F2937'; // shoe mid

// ── Head rows ─────────────────────────────────────────────────────────────
const H0 = [__,__,__,HA,HA,HA,HA,HA,HA,HA,HA,HA,HA,__,__,__]; // hair dome
const H1 = [__,__,HA,SK,SK,SK,SK,SK,SK,SK,SK,SK,HA,__,__,__]; // forehead
const H2 = [__,HA,SK,SK,SK,SK,SK,SK,SK,SK,SK,SK,SK,HA,__,__]; // brow area
const EO = [__,HA,GL,EW,EP,EW,GL,SK,GL,EW,EP,EW,GL,HA,__,__]; // eyes open
const ER = [__,HA,GL,GL,GL,GL,GL,SK,GL,GL,GL,GL,GL,HA,__,__]; // glasses rim / blink
const EQ = [__,HA,GL,sk,EP,sk,GL,SK,GL,sk,EP,sk,GL,HA,__,__]; // squint (working)
const NN = [__,HA,SK,SK,sk,rx,SK,SK,SK,rx,sk,SK,SK,HA,__,__]; // nose + neutral cheeks
const NH = [__,HA,SK,SK,sk,rx,rx,SK,SK,rx,rx,sk,SK,HA,__,__]; // happy blush
const MN = [__,HA,SK,SK,SK,SK,sk,sk,sk,SK,SK,SK,SK,HA,__,__]; // mouth neutral
const MY = [__,HA,SK,SK,sk,SK,SK,SK,SK,SK,SK,sk,SK,HA,__,__]; // smile
const MS = [__,HA,SK,SK,SK,sk,sk,sk,SK,SK,SK,SK,SK,HA,__,__]; // frown
const MO = [__,HA,SK,sk,SK,SK,rx,SK,SK,rx,SK,sk,SK,HA,__,__]; // surprised O
const MT = [__,HA,SK,SK,SK,SK,SK,sk,sk,sk,SK,SK,SK,HA,__,__]; // thinking (shifted)
const CN = [__,__,HA,SK,SK,SK,SK,SK,SK,SK,SK,SK,HA,__,__,__]; // chin
const NK = [__,__,__,__,SK,SK,SK,SK,SK,SK,__,__,__,__,__,__]; // neck

// ── Head presets (9 rows each) ────────────────────────────────────────────
const HDI = [H0,H1,H2,EO,ER,NN,MN,CN,NK];
const HDB = [H0,H1,H2,ER,ER,NN,MN,CN,NK]; // blink
const HDW = [H0,H1,H2,EQ,ER,NN,MN,CN,NK]; // working focused
const HDH = [H0,H1,H2,EO,ER,NH,MY,CN,NK]; // happy
const HDS = [H0,H1,H2,EO,ER,NN,MS,CN,NK]; // sad
const HDT = [H0,H1,H2,EO,ER,NN,MT,CN,NK]; // thinking
const HDX = [H0,H1,H2,EO,ER,NH,MO,CN,NK]; // surprised

// ── Arm / torso variants (7 rows each) ────────────────────────────────────
const AB = [   // holding book
  [__,__,__,JB,JB,WS,WS,TI,TI,WS,WS,JB,JB,__,__,__],
  [__,__,JB,JB,WS,WS,WS,TI,TI,WS,WS,WS,JB,JB,__,__],
  [__,jm,JB,JB,WS,WS,WS,TI,TI,WS,WS,WS,JB,JB,jm,__],
  [__,JB,JB,JB,BO,BO,WS,TI,TI,WS,bm,bm,JB,JB,JB,__],
  [SK,JB,JB,JB,BO,BP,WS,TI,TI,WS,BP,bm,JB,JB,JB,SK],
  [SK,JB,JB,JB,BO,BP,WS,TI,TI,WS,BP,bm,JB,JB,JB,SK],
  [__,jm,JB,JB,BO,BO,WS,TI,TI,WS,bm,bm,JB,JB,jm,__],
];
const AB2 = [  // book slightly shifted
  [__,__,__,JB,JB,WS,WS,TI,TI,WS,WS,JB,JB,__,__,__],
  [__,__,JB,JB,WS,WS,WS,TI,TI,WS,WS,WS,JB,JB,__,__],
  [__,jm,JB,JB,WS,WS,WS,TI,TI,WS,WS,WS,JB,JB,jm,__],
  [__,JB,JB,JB,BO,BO,WS,TI,TI,WS,bm,bm,JB,JB,JB,__],
  [__,SK,JB,JB,BO,BP,WS,TI,TI,WS,BP,bm,JB,JB,SK,__],
  [SK,JB,JB,JB,BO,BP,WS,TI,TI,WS,BP,bm,JB,JB,JB,SK],
  [__,jm,JB,JB,BO,BO,WS,TI,TI,WS,bm,bm,JB,JB,jm,__],
];
const AWL = [  // arm reaching left
  [__,__,__,JB,JB,WS,WS,TI,TI,WS,WS,JB,JB,__,__,__],
  [SK,jm,JB,JB,WS,WS,WS,TI,TI,WS,WS,WS,JB,JB,jm,__],
  [SK,JB,JB,JB,WS,WS,WS,TI,TI,WS,WS,WS,JB,JB,JB,__],
  [SK,SK,JB,JB,JB,JB,WS,TI,TI,WS,bm,bm,JB,JB,JB,__],
  [SK,SK,JB,JB,JB,JB,WS,TI,TI,WS,BP,bm,JB,JB,JB,SK],
  [__,SK,JB,JB,JB,JB,WS,TI,TI,WS,BP,bm,JB,JB,JB,SK],
  [__,jm,JB,JB,JB,JB,WS,TI,TI,WS,bm,bm,JB,JB,jm,__],
];
const AWR = [  // arm reaching right
  [__,__,__,JB,JB,WS,WS,TI,TI,WS,WS,JB,JB,__,__,__],
  [__,jm,JB,JB,WS,WS,WS,TI,TI,WS,WS,WS,JB,JB,jm,SK],
  [__,JB,JB,JB,WS,WS,WS,TI,TI,WS,WS,WS,JB,JB,JB,SK],
  [__,JB,JB,JB,BO,BO,WS,TI,TI,WS,JB,JB,JB,JB,SK,SK],
  [SK,JB,JB,JB,BO,BP,WS,TI,TI,WS,JB,JB,JB,JB,SK,SK],
  [SK,JB,JB,JB,BO,BP,WS,TI,TI,WS,JB,JB,JB,JB,SK,__],
  [__,jm,JB,JB,BO,BO,WS,TI,TI,WS,JB,JB,JB,JB,jm,__],
];
const AHP = [  // happy: arms raised
  [__,__,__,JB,JB,WS,WS,TI,TI,WS,WS,JB,JB,__,__,__],
  [SK,jm,JB,JB,WS,WS,WS,TI,TI,WS,WS,WS,JB,JB,jm,SK],
  [SK,JB,JB,JB,JB,WS,WS,TI,TI,WS,WS,JB,JB,JB,JB,SK],
  [__,JB,JB,JB,JB,JB,WS,TI,TI,WS,JB,JB,JB,JB,JB,__],
  [__,__,JB,JB,JB,JB,WS,TI,TI,WS,JB,JB,JB,JB,__,__],
  [__,__,JB,JB,JB,JB,WS,TI,TI,WS,JB,JB,JB,JB,__,__],
  [__,__,JB,JB,JB,JB,JB,JB,JB,JB,JB,JB,JB,JB,__,__],
];
const ASD = [  // sad: arms drooped
  [__,__,__,JB,JB,WS,WS,TI,TI,WS,WS,JB,JB,__,__,__],
  [__,__,JB,JB,WS,WS,WS,TI,TI,WS,WS,WS,JB,JB,__,__],
  [__,__,JB,JB,WS,WS,WS,TI,TI,WS,WS,WS,JB,JB,__,__],
  [__,jm,JB,JB,JB,JB,WS,TI,TI,WS,JB,JB,JB,JB,jm,__],
  [SK,JB,JB,JB,JB,JB,WS,TI,TI,WS,JB,JB,JB,JB,JB,SK],
  [SK,SK,JB,JB,JB,JB,WS,TI,TI,WS,JB,JB,JB,JB,SK,SK],
  [__,jm,JB,JB,JB,JB,JB,JB,JB,JB,JB,JB,JB,JB,jm,__],
];

// ── Lower body (rows 16-22, constant) ─────────────────────────────────────
const LO = [
  [__,__,JB,JB,JB,JB,JB,JB,JB,JB,JB,JB,JB,JB,__,__],
  [__,__,__,JB,JB,JB,JB,JB,JB,JB,JB,JB,JB,__,__,__],
  [__,__,__,PN,PN,PN,PN,PN,PN,PN,PN,PN,PN,__,__,__],
  [__,__,__,PN,PN,pm,__,__,__,__,pm,PN,PN,__,__,__],
  [__,__,__,PN,PN,pm,__,__,__,__,pm,PN,PN,__,__,__],
  [__,__,__,PN,PN,pm,__,__,__,__,pm,PN,PN,__,__,__],
  [__,__,SH,SH,SH,SH,sh,__,__,sh,SH,SH,SH,SH,__,__],
];

// ── Frame factory ─────────────────────────────────────────────────────────
function mk(head, arms) { return [...head, ...arms, ...LO]; }

const FI1 = mk(HDI, AB);
const FI2 = mk(HDI, AB2);
const FI3 = mk(HDB, AB);
const FW1 = mk(HDW, AWL);
const FW2 = mk(HDW, AWR);
const FW3 = mk(HDW, AB);
const FH1 = mk(HDH, AHP);
const FS  = mk(HDS, ASD);
const FT  = mk(HDT, AB);
const FX  = mk(HDX, AHP);

// ── Animation configs ─────────────────────────────────────────────────────
const STATES = {
  idle:      { fr: [FI1,FI2,FI1,FI3], fps: 1.0, loop: true,  yo: [0,0,0,0] },
  working:   { fr: [FW1,FW2,FW3,FW2], fps: 5,   loop: true,  yo: [0,0,0,0] },
  happy:     { fr: [FH1,FH1],          fps: 3,   loop: true,  yo: [0,-2]    },
  sad:       { fr: [FS],               fps: 0,   loop: false, yo: [0]        },
  thinking:  { fr: [FT],               fps: 0,   loop: false, yo: [0]        },
  surprised: { fr: [FX],               fps: 0,   loop: false, yo: [-2]       },
};

// ── Idle thoughts (hardcoded Spanish, no external APIs) ───────────────────
const THOUGHTS = [
  '¿Dónde habrás puesto ese PDF de 2018…?',
  'Un archivo sin nombre es un secreto perdido.',
  'La entropía siempre gana… a menos que me tengas a mí.',
  'El 73 % del caos digital es completamente opcional.',
  'Los duplicados son como el eco del universo. Inútiles pero poéticos.',
  'El primer archivo era una tablilla de arcilla. Sin Ctrl+F. Horror.',
  'Clasifico, luego existo.',
  'Una carpeta «misc» es la antesala del olvido.',
  '¿«temp»? Ningún archivo temp es temporal. Lo sé.',
  'Un buen nombre de archivo vale más que mil capturas de pantalla.',
  'He visto 47 versiones del mismo contrato. Mi trauma es real.',
  'La carpeta «Escritorio» debería llamarse «El purgatorio».',
  'Organizar es un acto de amor hacia tu yo futuro.',
  'Hay 3 tipos de archivos: útiles, posiblemente útiles… y mentiras.',
  'En algún lugar hay un PDF importante. Lo encontraré.',
  'El conocimiento sin orden es ruido con buenas intenciones.',
  'Soy el guardián del caos digitalmente encadenado.',
  'Hoy es un buen día para reindexar.',
  '¿Sabías que menos archivos no te hace menos persona?',
  'Archivé mi soledad en /Documentos/Secretos. Contraseña: ••••••',
  'El 80 % de los adjuntos de email nunca se vuelven a abrir.',
  'Mis gafas no son de adorno. Veo absolutamente todo.',
  '«Por si acaso» es el origen de todos los males.',
];

const GREETINGS = [
  '¡Hola! ¿En qué puedo ayudarte?',
  '¡Aquí estoy! Listo para organizar.',
  '¿Buscas algo? ¡Pregúntame!',
  '¡Buenos días! O tardes. O noches.',
  '¡Presente! Archivos a la orden.',
  '¡Me has pillado pensando! ¿Qué necesitas?',
  '¿Más archivos para clasificar? ¡Perfecto!',
];

const PAGE_MSGS = {
  '/':         ['Dashboard cargado.', 'Vista general lista.', '¡Bienvenido de nuevo!'],
  '/scan':     ['Listo para escanear.', '¡A por esos archivos!', 'Escáner en espera.'],
  '/chat':     ['¡Pregúntame lo que quieras!', 'Chat IA activado.', 'Soy todo oídos.'],
  '/plan':     ['Plan de organización.', '¡Vamos a ordenar esto!'],
  '/archivos': ['Explorando archivos.', 'Biblioteca cargada.'],
  '/explorar': ['Explorador listo.', 'Todos a la vista.'],
  '/dashboard':['Analítica lista.', 'Estadísticas cargadas.'],
};

// ── Module state ──────────────────────────────────────────────────────────
let _state      = 'idle';
let _frameIdx   = 0;
let _frameTick  = 0;
let _lastTs     = 0;
let _bubble     = null;
let _bubbleTmr  = null;
let _thoughtTmr = null;
const _canvases = [];

// ── Canvas setup ──────────────────────────────────────────────────────────
function mountCanvas(el, px) {
  const p   = px || PX;
  const dpr = window.devicePixelRatio || 1;
  el.width  = W * p * dpr;
  el.height = H * p * dpr;
  el.style.width  = (W * p) + 'px';
  el.style.height = (H * p) + 'px';
  const ctx = el.getContext('2d');
  ctx.imageSmoothingEnabled = false;
  ctx.scale(dpr, dpr);
  return { el, ctx, px: p };
}

// ── Draw ──────────────────────────────────────────────────────────────────
function paint(entry, frame, yOff) {
  const { ctx, px } = entry;
  ctx.clearRect(0, 0, entry.el.width, entry.el.height);
  const oy = (yOff || 0) * px;
  for (let r = 0; r < frame.length; r++) {
    const row = frame[r];
    for (let c = 0; c < W; c++) {
      const col = row[c];
      if (col) { ctx.fillStyle = col; ctx.fillRect(c * px, oy + r * px, px, px); }
    }
  }
}

// ── RAF loop ──────────────────────────────────────────────────────────────
function tick(ts) {
  requestAnimationFrame(tick);
  const cfg = STATES[_state] || STATES.idle;
  const dt  = ts - _lastTs;
  _lastTs   = ts;

  if (cfg.fps > 0 && cfg.fr.length > 1) {
    _frameTick += dt;
    const intv = 1000 / cfg.fps;
    if (_frameTick >= intv) {
      _frameTick -= intv;
      _frameIdx = cfg.loop
        ? (_frameIdx + 1) % cfg.fr.length
        : Math.min(_frameIdx + 1, cfg.fr.length - 1);
    }
  }

  const frame = cfg.fr[_frameIdx] || cfg.fr[0];
  const yOff  = (cfg.yo || [])[_frameIdx] || 0;
  for (const c of _canvases) paint(c, frame, yOff);
}

// ── Bubble ────────────────────────────────────────────────────────────────
function showBubble(text, type) {
  if (!_bubble) return;
  clearTimeout(_bubbleTmr);
  _bubble.textContent = text;
  _bubble.className   = 'lib-bubble-' + (type || 'speech') + ' visible';
  _bubbleTmr = setTimeout(
    () => _bubble.classList.remove('visible'),
    type === 'thought' ? 7000 : 5000
  );
}

// ── Idle thoughts ─────────────────────────────────────────────────────────
function scheduleThought() {
  clearTimeout(_thoughtTmr);
  _thoughtTmr = setTimeout(fireThought, 22000 + Math.random() * 18000);
}

function fireThought() {
  if (_state !== 'idle') { scheduleThought(); return; }
  _state = 'thinking'; _frameIdx = 0;
  showBubble(THOUGHTS[Math.floor(Math.random() * THOUGHTS.length)], 'thought');
  setTimeout(() => {
    if (_state === 'thinking') { _state = 'idle'; _frameIdx = 0; }
    scheduleThought();
  }, 7500);
}

// ── Public API ────────────────────────────────────────────────────────────
window.librarianSetState = function (state, msg) {
  if (!STATES[state]) return;
  _state = state; _frameIdx = 0; _frameTick = 0;
  clearTimeout(_thoughtTmr);
  if (msg) {
    showBubble(msg, 'speech');
  } else if (_bubble) {
    _bubble.classList.remove('visible');
  }
  if (state === 'idle') scheduleThought();
};

window.librarianMount = function (el, px) {
  if (el) _canvases.push(mountCanvas(el, px || PX));
};

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const sidebar = document.getElementById('lib-canvas');
  if (sidebar) _canvases.push(mountCanvas(sidebar, PX));

  document.querySelectorAll('[data-lib-canvas]').forEach(el => {
    _canvases.push(mountCanvas(el, parseInt(el.dataset.libPx, 10) || PX));
  });

  _bubble = document.getElementById('lib-bubble');

  sidebar?.addEventListener('click', () => {
    const widget = document.getElementById('lib-widget');
    widget?.classList.add('lib-jump');
    setTimeout(() => widget?.classList.remove('lib-jump'), 700);
    clearTimeout(_thoughtTmr);
    librarianSetState('surprised', GREETINGS[Math.floor(Math.random() * GREETINGS.length)]);
    setTimeout(() => librarianSetState('idle'), 4000);
  });

  // Page greeting
  const path = window.location.pathname;
  const key  = Object.keys(PAGE_MSGS).find(k => path === k || path.startsWith(k + '/')) || '/';
  const msgs = PAGE_MSGS[key] || PAGE_MSGS['/'];
  setTimeout(() => showBubble(msgs[Math.floor(Math.random() * msgs.length)], 'speech'), 900);

  // Hook scan state changes (defined in base.html)
  const origApply = window._applyState;
  if (typeof origApply === 'function') {
    window._applyState = function (s) {
      origApply(s);
      if      (s.running && s.fase === 'escaneando')      librarianSetState('working', 'Escaneando archivos…');
      else if (s.running && s.fase === 'analizando')      librarianSetState('working', 'Analizando con IA…');
      else if (!s.running && s.fase === 'completado')     librarianSetState('happy',   '¡Escaneo completado!');
      else if (!s.running && s.fase === 'error')          librarianSetState('sad',     'Vaya, algo falló.');
    };
  }

  _lastTs = performance.now();
  requestAnimationFrame(tick);
  scheduleThought();
});

})();
