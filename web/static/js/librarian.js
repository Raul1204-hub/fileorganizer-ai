/* Pixel-art librarian mascot — FileOrganizer AI */
(function () {
  'use strict';

  // ── Palette ────────────────────────────────────────────────────────────────
  const _ = null;
  const HA = '#2C1B0E'; // hair dark
  const hA = '#57311A'; // hair mid
  const SK = '#FBC99A'; // skin
  const sk = '#C8724A'; // skin shadow / mouth
  const GL = '#1C1C1C'; // glasses / eye
  const JB = '#1E40AF'; // jacket blue
  const BK = '#991B1B'; // book cover
  const BP = '#FEF3C7'; // book page
  const PN = '#111827'; // pants
  const SH = '#030712'; // shoes
  const TI = '#DC2626'; // tie
  const SP = '#FDE68A'; // sparkle

  const PX = 5; // screen px per art px
  const W  = 12;
  const H  = 14;

  // ── Frames ─────────────────────────────────────────────────────────────────
  /* idle */
  const I1 = [
    [_,_,HA,HA,HA,HA,_,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,GL,SK,GL,SK,hA,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,SK,sk,SK,sk,hA,_,_,_,_,_],
    [_,_,SK,JB,JB,SK,_,_,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,JB,_,_,_,_],
    [JB,JB,JB,TI,JB,JB,JB,JB,_,_,_,_],
    [SK,JB,JB,TI,BK,BK,JB,JB,SK,_,_,_],
    [_,JB,JB,TI,BP,BK,JB,JB,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,_,_,_,_,_],
    [_,_,PN,PN,PN,PN,_,_,_,_,_,_],
    [_,_,PN,_,_,PN,_,_,_,_,_,_],
    [_,_,SH,_,_,SH,_,_,_,_,_,_],
  ];
  /* idle blink */
  const I2 = [
    [_,_,HA,HA,HA,HA,_,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,GL,SK,GL,SK,hA,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,SK,sk,SK,sk,hA,_,_,_,_,_],
    [_,_,SK,JB,JB,SK,_,_,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,JB,_,_,_,_],
    [JB,JB,JB,TI,JB,JB,JB,JB,_,_,_,_],
    [_,JB,JB,TI,BK,BK,JB,JB,SK,_,_,_],
    [SK,JB,JB,TI,BP,BK,JB,JB,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,_,_,_,_,_],
    [_,_,PN,PN,PN,PN,_,_,_,_,_,_],
    [_,_,PN,_,_,PN,_,_,_,_,_,_],
    [_,_,SH,_,_,SH,_,_,_,_,_,_],
  ];
  // blink = same as I1 but eyes replaced with flat lines
  I2[2] = [_,HA,GL,GL,GL,GL,hA,_,_,_,_,_];

  /* working arm-left */
  const WK1 = [
    [_,_,HA,HA,HA,HA,_,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,GL,sk,GL,sk,hA,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,SK,sk,SK,sk,hA,_,_,_,_,_],
    [_,_,SK,JB,JB,SK,_,_,_,_,_,_],
    [SK,SK,JB,JB,JB,JB,JB,JB,_,_,_,_],
    [SK,JB,JB,TI,JB,JB,JB,JB,_,_,_,_],
    [_,JB,JB,TI,BK,BK,JB,JB,SK,_,_,_],
    [_,JB,JB,TI,BP,BK,JB,JB,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,_,_,_,_,_],
    [_,_,PN,PN,PN,PN,_,_,_,_,_,_],
    [_,_,PN,_,_,PN,_,_,_,_,_,_],
    [_,_,SH,_,_,SH,_,_,_,_,_,_],
  ];
  /* working arm-right */
  const WK2 = [
    [_,_,HA,HA,HA,HA,_,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,GL,sk,GL,sk,hA,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,SK,sk,SK,sk,hA,_,_,_,_,_],
    [_,_,SK,JB,JB,SK,_,_,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,SK,SK,_,_,_],
    [JB,JB,JB,TI,JB,JB,JB,JB,SK,_,_,_],
    [SK,JB,JB,TI,BK,BK,JB,JB,_,_,_,_],
    [_,JB,JB,TI,BP,BK,JB,JB,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,_,_,_,_,_],
    [_,_,PN,PN,PN,PN,_,_,_,_,_,_],
    [_,_,PN,_,_,PN,_,_,_,_,_,_],
    [_,_,SH,_,_,SH,_,_,_,_,_,_],
  ];
  /* working head-tilt */
  const WK3 = [
    [_,_,_,HA,HA,HA,HA,_,_,_,_,_],
    [_,_,HA,SK,SK,SK,SK,hA,_,_,_,_],
    [_,_,HA,GL,sk,GL,sk,hA,_,_,_,_],
    [_,_,HA,SK,SK,SK,SK,hA,_,_,_,_],
    [_,_,HA,SK,sk,SK,sk,hA,_,_,_,_],
    [_,_,_,SK,JB,JB,SK,_,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,JB,_,_,_,_],
    [JB,JB,JB,TI,JB,JB,JB,JB,_,_,_,_],
    [SK,JB,JB,TI,BK,BK,JB,JB,SK,_,_,_],
    [_,JB,JB,TI,BP,BK,JB,JB,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,_,_,_,_,_],
    [_,_,PN,PN,PN,PN,_,_,_,_,_,_],
    [_,_,PN,_,_,PN,_,_,_,_,_,_],
    [_,_,SH,_,_,SH,_,_,_,_,_,_],
  ];

  /* happy — arms out, smile */
  const HP1 = [
    [_,_,HA,HA,HA,HA,_,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,GL,SK,GL,SK,hA,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,sk,SK,SK,sk,hA,_,_,_,_,_],
    [_,_,SK,JB,JB,SK,_,_,_,_,_,_],
    [SK,JB,JB,JB,JB,JB,JB,SK,_,_,_,_],
    [_,JB,JB,TI,JB,JB,JB,_,_,_,_,_],
    [_,JB,JB,TI,JB,JB,JB,_,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,_,_,_,_,_],
    [_,_,PN,PN,PN,PN,_,_,_,_,_,_],
    [_,_,PN,_,_,PN,_,_,_,_,_,_],
    [_,_,SH,_,_,SH,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_,_,_],
  ];
  /* happy — jump frame with sparkles */
  const HP2 = [
    [SP,_,HA,HA,HA,HA,_,SP,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,GL,SK,GL,SK,hA,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,sk,SK,SK,sk,hA,_,_,_,_,_],
    [_,_,SK,JB,JB,SK,_,_,_,_,_,_],
    [SK,JB,JB,JB,JB,JB,JB,SK,_,_,_,_],
    [_,JB,JB,TI,JB,JB,JB,_,_,_,_,_],
    [_,JB,JB,TI,JB,JB,JB,_,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,_,_,_,_,_],
    [_,_,PN,PN,PN,PN,_,_,_,_,_,_],
    [_,_,_,PN,PN,_,_,_,_,_,_,_],
    [_,_,_,SH,SH,_,_,_,_,_,_,_],
    [_,_,_,_,_,_,_,_,_,_,_,_],
  ];

  /* sad — arms low, frown */
  const SD1 = [
    [_,_,HA,HA,HA,HA,_,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,GL,SK,GL,SK,hA,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,SK,SK,sk,SK,hA,_,_,_,_,_],
    [_,_,SK,JB,JB,SK,_,_,_,_,_,_],
    [_,_,JB,JB,JB,JB,JB,_,_,_,_,_],
    [_,JB,JB,TI,JB,JB,JB,JB,_,_,_,_],
    [SK,JB,JB,TI,JB,JB,JB,JB,SK,_,_,_],
    [SK,JB,JB,JB,JB,JB,JB,SK,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,_,_,_,_,_],
    [_,_,PN,PN,PN,PN,_,_,_,_,_,_],
    [_,_,PN,_,_,PN,_,_,_,_,_,_],
    [_,_,SH,_,_,SH,_,_,_,_,_,_],
  ];

  /* thinking — hand on chin */
  const TH1 = [
    [_,_,HA,HA,HA,HA,_,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,GL,SK,GL,SK,hA,_,_,_,_,_],
    [_,HA,SK,SK,SK,SK,hA,_,_,_,_,_],
    [_,HA,SK,sk,SK,_,hA,_,_,_,_,_],
    [_,SK,SK,JB,JB,SK,_,_,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,JB,_,_,_,_],
    [_,JB,JB,TI,JB,JB,JB,JB,_,_,_,_],
    [SK,JB,JB,TI,JB,JB,JB,JB,SK,_,_,_],
    [_,JB,JB,TI,JB,JB,JB,_,_,_,_,_],
    [_,JB,JB,JB,JB,JB,JB,_,_,_,_,_],
    [_,_,PN,PN,PN,PN,_,_,_,_,_,_],
    [_,_,PN,_,_,PN,_,_,_,_,_,_],
    [_,_,SH,_,_,SH,_,_,_,_,_,_],
  ];

  // ── State config ───────────────────────────────────────────────────────────
  const STATES = {
    idle:     { frames: [I1, I2, I1, I1], fps: 1.2, loop: true },
    working:  { frames: [WK1, WK2, WK3, WK2], fps: 5, loop: true },
    happy:    { frames: [HP1, HP2, HP1, HP2], fps: 2.5, loop: true },
    sad:      { frames: [SD1], fps: 0, loop: false },
    thinking: { frames: [TH1], fps: 0, loop: false },
  };

  // ── Page messages ──────────────────────────────────────────────────────────
  const MSGS = {
    idle: {
      '/':                ['¿Listo para organizar?', '¡Escanea tu colección!'],
      '/dashboard':       ['¡Aquí están tus estadísticas!', '¿Qué analizamos hoy?'],
      '/plan':            ['Vamos a planificar', 'Sin tocar el disco todavía'],
      '/recomendaciones': ['Tengo sugerencias para ti', '¡Hay cosas por mejorar!'],
      '/chat':            ['Pregúntame lo que quieras', '¿En qué puedo ayudarte?'],
      '/explorar':        ['¡Explora tu colección!', 'Todos tus archivos aquí'],
      '/organizar':       ['Organicemos tus archivos', '¿Cómo quieres ordenarlos?'],
      '/duplicados':      ['Busco duplicados para ti', '¡Recupera espacio en disco!'],
      '/historial':       ['Aquí está tu historial', 'Todo queda registrado'],
      '/backup':          ['Tus copias de seguridad', '¡Siempre puedes deshacer!'],
      '/vigilancia':      ['Estoy vigilando tu carpeta', '¡Nada se me escapa!'],
      default:            ['¿En qué puedo ayudarte?', '¡Estoy aquí para ayudar!'],
    },
    working: ['Trabajando en ello…', 'Un momento por favor…', 'Procesando…'],
    happy:   ['¡Todo en orden!', '¡Hecho con éxito!', '¡Misión completada!'],
    sad:     ['Algo salió mal…', 'Hay errores pendientes', 'Revisa los detalles'],
    thinking: ['Déjame pensar…', 'Hmm…', '¿Qué haremos hoy?'],
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  let _canvas, _ctx, _state = 'idle', _frameIdx = 0, _lastTs = 0, _rafId = null;
  let _bubble, _bubbleTimer = null;
  let _variant = 'default';

  function _draw(frame) {
    if (!_ctx) return;
    _ctx.clearRect(0, 0, W * PX, H * PX);
    for (let r = 0; r < frame.length; r++) {
      for (let c = 0; c < frame[r].length; c++) {
        const col = frame[r][c];
        if (col) {
          _ctx.fillStyle = col;
          _ctx.fillRect(c * PX, r * PX, PX, PX);
        }
      }
    }
  }

  function _tick(ts) {
    const cfg = STATES[_state] || STATES.idle;
    const interval = cfg.fps > 0 ? 1000 / cfg.fps : Infinity;
    if (ts - _lastTs >= interval) {
      if (cfg.loop || _frameIdx < cfg.frames.length - 1) {
        _frameIdx = (_frameIdx + 1) % cfg.frames.length;
      }
      _draw(cfg.frames[_frameIdx]);
      _lastTs = ts;
    }
    _rafId = requestAnimationFrame(_tick);
  }

  function _pickMsg(state) {
    const path = window.location.pathname;
    if (state === 'idle') {
      const pool = MSGS.idle[path] || MSGS.idle.default;
      return pool[Math.floor(Math.random() * pool.length)];
    }
    const pool = MSGS[state] || MSGS.idle.default;
    return pool[Math.floor(Math.random() * pool.length)];
  }

  function _showBubble(text) {
    if (!_bubble) return;
    _bubble.textContent = text;
    _bubble.classList.remove('lib-bubble-hide');
    _bubble.classList.add('lib-bubble-show');
    clearTimeout(_bubbleTimer);
    _bubbleTimer = setTimeout(() => {
      _bubble.classList.remove('lib-bubble-show');
      _bubble.classList.add('lib-bubble-hide');
    }, 5000);
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  window.librarianSetState = function (state, msg) {
    if (!STATES[state]) return;
    _state = state;
    _frameIdx = 0;
    _lastTs = 0;
    _showBubble(msg || _pickMsg(state));
  };

  // ── Init ───────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    _canvas = document.getElementById('lib-canvas');
    _bubble = document.getElementById('lib-bubble');
    if (!_canvas) return;

    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    _canvas.width  = W * PX * ratio;
    _canvas.height = H * PX * ratio;
    _canvas.style.width  = W * PX + 'px';
    _canvas.style.height = H * PX + 'px';
    _ctx = _canvas.getContext('2d');
    _ctx.imageSmoothingEnabled = false;
    _ctx.scale(ratio, ratio);

    _draw(STATES.idle.frames[0]);
    _rafId = requestAnimationFrame(_tick);

    // Show greeting after 800ms
    setTimeout(() => _showBubble(_pickMsg('idle')), 800);

    // Click = random greeting
    _canvas.style.cursor = 'pointer';
    _canvas.addEventListener('click', () => {
      if (_state === 'idle') _showBubble(_pickMsg('idle'));
    });

    // Wire scan events from base.html
    const _origApply = window._applyState;
    if (typeof _origApply === 'function') {
      window._applyState = function (s) {
        _origApply(s);
        if (s.running) {
          librarianSetState('working', s.fase === 'analizando'
            ? 'Analizando con IA…' : 'Escaneando archivos…');
        } else if (s.fase === 'completado') {
          const failed = ((s.summary || {}).fallos_extraccion || 0)
                       + ((s.summary || {}).fallos_ollama || 0);
          librarianSetState(failed ? 'sad' : 'happy',
            failed ? `¡Completado con ${failed} fallos!` : '¡Escaneo completado!');
          setTimeout(() => librarianSetState('idle'), 4000);
        } else if (s.fase === 'error') {
          librarianSetState('sad', 'Algo salió mal…');
          setTimeout(() => librarianSetState('idle'), 4000);
        }
      };
    }
  });
})();
