// Filex — smooth illustrated kawaii fox (Canvas 2D, NOT pixel art)
// Logical canvas: 100 × 120 units · S=1.5 → 150×180 CSS px sidebar
(function () {
'use strict';

const W = 100, H = 120, S_DEF = 1.5;

// ── Palette ────────────────────────────────────────────────────────────────
const P = {
  out: '#3D1808',                        // warm dark-brown outline
  o1:  '#E06818', o2: '#B84010',         // orange main / shadow
  o3:  '#F4984A', o4: '#F8C890',         // orange light / pale
  c1:  '#F8EDD0', c2: '#F0D8A0',         // cream main / shadow
  cw:  '#FFF8EE',                        // cream highlight
  bk:  '#1A0804', wh: '#FFFFFF',         // near-black / white
  pk:  '#F09070',                        // blush pink
  r1:  '#C03020', r2: '#E04828',         // scarf
  b1:  '#7A4018', b2: '#3A1808',         // bag
  gn:  '#5A7820', gd: '#3A5010',         // green (clasp / cap)
  yl:  '#E8A820',                        // yellow
  bu:  '#5080C0', bl: '#90B0E0',         // blue / light-blue
  pw:  '#5C2808',                        // dark paw
};

// ── Canvas helpers ─────────────────────────────────────────────────────────
function lg(ctx, x0,y0,x1,y1,...st){
  const g=ctx.createLinearGradient(x0,y0,x1,y1);
  st.forEach(([t,c])=>g.addColorStop(t,c)); return g;
}
function rg(ctx, cx,cy,r0,r1,...st){
  const g=ctx.createRadialGradient(cx,cy,r0,cx,cy,r1);
  st.forEach(([t,c])=>g.addColorStop(t,c)); return g;
}
// fill + stroke the current path
function fs(ctx, fill, stroke, lw){
  if(fill){ ctx.fillStyle=fill; ctx.fill(); }
  ctx.strokeStyle=stroke||P.out; ctx.lineWidth=lw||2.2; ctx.stroke();
}
function circ(ctx,cx,cy,r){ ctx.beginPath(); ctx.arc(cx,cy,r,0,Math.PI*2); }
function oval(ctx,cx,cy,rx,ry,rot){
  ctx.beginPath(); ctx.ellipse(cx,cy,rx,ry,rot||0,0,Math.PI*2);
}

// ── TAIL ──────────────────────────────────────────────────────────────────
function dTail(ctx){
  // Large fluffy tail — right side of body
  ctx.beginPath();
  ctx.moveTo(58,115);
  ctx.bezierCurveTo(52,100, 58,82, 68,70);
  ctx.bezierCurveTo(78,58,  96,54, 97,68);
  ctx.bezierCurveTo(99,82,  90,100, 84,115);
  ctx.closePath();
  fs(ctx, lg(ctx,68,54,84,115,[0,P.o2],[0.35,P.o1],[0.65,P.o1],[1,P.o2]));

  // Inner highlight stripe
  ctx.beginPath();
  ctx.moveTo(86,60); ctx.bezierCurveTo(96,70,96,90,88,108);
  ctx.bezierCurveTo(84,100,86,80,82,68); ctx.closePath();
  ctx.fillStyle='rgba(244,152,74,0.35)'; ctx.fill();

  // Cream tip
  oval(ctx,73,110,13,9);
  fs(ctx, lg(ctx,65,108,82,116,[0,P.cw],[0.5,P.c1],[1,P.c2]), P.out,1.6);
}

// ── EARS ──────────────────────────────────────────────────────────────────
function dOneEar(ctx, flip){
  ctx.save();
  if(flip){ ctx.transform(-1,0,0,1,100,0); }

  // Outer orange
  ctx.beginPath();
  ctx.moveTo(14,34);
  ctx.quadraticCurveTo(4,16,  22,3);
  ctx.quadraticCurveTo(38,-2, 40,32);
  ctx.closePath();
  fs(ctx, lg(ctx,22,3,22,34,[0,P.o2],[0.55,P.o1],[1,P.o1]));

  // Cream inner fur
  ctx.beginPath();
  ctx.moveTo(18,30);
  ctx.quadraticCurveTo(10,18, 22,7);
  ctx.quadraticCurveTo(34,3,  36,28);
  ctx.closePath();
  ctx.fillStyle=P.c1; ctx.fill();

  // White tip highlight inside ear
  ctx.beginPath();
  ctx.moveTo(22,7); ctx.quadraticCurveTo(30,4,34,14);
  ctx.quadraticCurveTo(26,10,22,7); ctx.closePath();
  ctx.fillStyle=P.cw; ctx.fill();

  ctx.restore();
}
function dEars(ctx){
  dOneEar(ctx, false); // left ear
  dOneEar(ctx, true);  // right ear (mirrored)
}

// ── BODY ──────────────────────────────────────────────────────────────────
function dBody(ctx){
  // Main torso
  ctx.beginPath();
  ctx.moveTo(22,74);
  ctx.bezierCurveTo(18,82, 18,100, 28,114);
  ctx.lineTo(72,114);
  ctx.bezierCurveTo(82,100, 82,82, 78,74);
  ctx.bezierCurveTo(70,68, 30,68, 22,74);
  ctx.closePath();
  fs(ctx, rg(ctx,46,84,6,32,[0,P.o3],[0.5,P.o1],[1,P.o2]));

  // Cream belly
  oval(ctx,50,96,17,18);
  fs(ctx, rg(ctx,47,88,3,18,[0,P.cw],[0.6,P.c1],[1,P.c2]), P.out,1.5);
}

// ── SCARF ─────────────────────────────────────────────────────────────────
function dScarf(ctx){
  ctx.save();
  ctx.lineCap='round'; ctx.lineJoin='round';

  // Band around neck
  ctx.beginPath();
  ctx.moveTo(22,70);
  ctx.bezierCurveTo(22,76, 38,80, 50,80);
  ctx.bezierCurveTo(62,80, 78,76, 78,70);
  ctx.bezierCurveTo(78,65, 62,66, 50,66);
  ctx.bezierCurveTo(38,66, 22,65, 22,70);
  ctx.closePath();
  fs(ctx, lg(ctx,22,66,78,80,[0,P.r2],[0.5,P.r1],[1,P.r2]));

  // Plaid texture lines
  ctx.save(); ctx.clip();
  ctx.strokeStyle='rgba(255,100,50,0.3)'; ctx.lineWidth=1.2;
  for(let x=24;x<80;x+=6){
    ctx.beginPath(); ctx.moveTo(x,63); ctx.lineTo(x,82); ctx.stroke();
  }
  for(let y=67;y<81;y+=4){
    ctx.beginPath(); ctx.moveTo(20,y); ctx.lineTo(80,y); ctx.stroke();
  }
  ctx.restore();

  // Dangling knot triangle (front)
  ctx.beginPath();
  ctx.moveTo(50,79);
  ctx.bezierCurveTo(44,86,40,94,44,103);
  ctx.bezierCurveTo(46,100,50,95,50,90);
  ctx.bezierCurveTo(50,95,54,100,56,103);
  ctx.bezierCurveTo(60,94,56,86,50,79);
  ctx.closePath();
  fs(ctx, P.r1);

  ctx.restore();
}

// ── BAG ───────────────────────────────────────────────────────────────────
function dBag(ctx){
  ctx.save();
  ctx.lineCap='round';

  // Strap (diagonal from right shoulder → left hip)
  ctx.beginPath();
  ctx.moveTo(68,70); ctx.bezierCurveTo(50,78,28,88,12,102);
  ctx.strokeStyle=P.b2; ctx.lineWidth=3; ctx.stroke();

  // Bag body
  ctx.beginPath();
  ctx.moveTo(4,86); ctx.arcTo(22,86,22,108,3);
  ctx.arcTo(22,108,4,108,3); ctx.arcTo(4,108,4,86,3); ctx.arcTo(4,86,22,86,3);
  ctx.closePath();
  fs(ctx, P.b1, P.b2, 1.5);

  // Flap
  ctx.beginPath();
  ctx.moveTo(4,86); ctx.arcTo(22,86,22,96,3); ctx.lineTo(22,96);
  ctx.quadraticCurveTo(13,100,4,96); ctx.closePath();
  ctx.fillStyle=P.b2; ctx.fill();

  // Green clasp gem
  circ(ctx,13,98,3.5);
  fs(ctx,P.gn,P.gd,1);
  circ(ctx,12,97,1.2);
  ctx.fillStyle='rgba(255,255,255,0.55)'; ctx.fill();

  ctx.restore();
}

// ── HEAD ──────────────────────────────────────────────────────────────────
function dHead(ctx){
  // Large round head
  circ(ctx,50,44,28);
  fs(ctx, rg(ctx,43,36,4,28,[0,P.o3],[0.5,P.o1],[1,P.o2]));

  // Small forehead tuft
  ctx.beginPath();
  ctx.arc(50,18,6,Math.PI*1.1,Math.PI*1.9);
  ctx.quadraticCurveTo(50,12,50,18); ctx.closePath();
  ctx.fillStyle=P.o1; ctx.fill();
}

// ── MUZZLE ────────────────────────────────────────────────────────────────
function dMuzzle(ctx){
  oval(ctx,50,57,18,13);
  fs(ctx, rg(ctx,46,52,2,17,[0,P.cw],[0.5,P.c1],[1,P.c2]), P.out,1.5);
}

// ── NOSE ──────────────────────────────────────────────────────────────────
function dNose(ctx){
  oval(ctx,50,51,5,3.5);
  fs(ctx, P.bk, false);
  // Highlight
  oval(ctx,52,50,1.8,1.1);
  ctx.fillStyle='rgba(255,255,255,0.45)'; ctx.fill();
}

// ── BLUSH ─────────────────────────────────────────────────────────────────
function dBlush(ctx){
  ctx.save(); ctx.globalAlpha=0.55;
  oval(ctx,28,52,10,6); ctx.fillStyle=P.pk; ctx.fill();
  oval(ctx,72,52,10,6); ctx.fill();
  ctx.restore();
}

// ── EYES ──────────────────────────────────────────────────────────────────
function dBigEye(ctx, cx, cy){
  // Outer ring
  circ(ctx,cx,cy,8); fs(ctx,P.bk,P.out,2.2);
  // Iris
  circ(ctx,cx,cy,6.2); ctx.fillStyle='#251008'; ctx.fill();
  // Main white highlight
  circ(ctx,cx+2.8,cy-2.5,2.8); ctx.fillStyle=P.wh; ctx.fill();
  // Secondary soft reflection
  circ(ctx,cx-2,cy+2.5,1.4); ctx.fillStyle='rgba(255,255,255,0.5)'; ctx.fill();
}

function dEyes(ctx,state,frame){
  ctx.lineCap='round'; ctx.lineJoin='round';

  if(state==='sleeping'){
    ctx.strokeStyle=P.out; ctx.lineWidth=2.5;
    ctx.beginPath(); ctx.moveTo(30,41); ctx.quadraticCurveTo(37,46,44,41); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(56,41); ctx.quadraticCurveTo(63,46,70,41); ctx.stroke();
    return;
  }
  if(state==='happy'||state==='celebrating'){
    ctx.strokeStyle=P.out; ctx.lineWidth=2.5;
    ctx.beginPath(); ctx.arc(37,42,7,Math.PI,0); ctx.stroke();
    ctx.beginPath(); ctx.arc(63,42,7,Math.PI,0); ctx.stroke();
    return;
  }
  if(state==='working'){
    ctx.strokeStyle=P.out; ctx.lineWidth=2.5;
    ctx.beginPath(); ctx.moveTo(30,41); ctx.quadraticCurveTo(37,39,44,41); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(56,41); ctx.quadraticCurveTo(63,39,70,41); ctx.stroke();
    ctx.lineWidth=2;
    ctx.beginPath(); ctx.moveTo(30,35); ctx.lineTo(44,34); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(56,34); ctx.lineTo(70,35); ctx.stroke();
    return;
  }

  // Default big round eyes
  dBigEye(ctx,37,41);
  dBigEye(ctx,63,41);

  // Eyebrows
  ctx.strokeStyle=P.out; ctx.lineWidth=2.2; ctx.lineCap='round';
  if(state==='surprised'){
    ctx.beginPath(); ctx.moveTo(28,29); ctx.quadraticCurveTo(37,26,46,29); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(54,29); ctx.quadraticCurveTo(63,26,72,29); ctx.stroke();
  } else if(state==='angry'){
    ctx.lineWidth=2.5;
    ctx.beginPath(); ctx.moveTo(28,34); ctx.lineTo(44,30); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(56,30); ctx.lineTo(72,34); ctx.stroke();
  } else if(state==='sad'){
    ctx.beginPath(); ctx.moveTo(28,31); ctx.lineTo(44,34); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(56,34); ctx.lineTo(72,31); ctx.stroke();
  } else if(state==='thinking'||state==='confused'){
    ctx.beginPath(); ctx.moveTo(28,29); ctx.quadraticCurveTo(37,27,46,30); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(54,33); ctx.quadraticCurveTo(63,31,72,33); ctx.stroke();
  } else if(state==='smart'){
    ctx.beginPath(); ctx.moveTo(28,33); ctx.quadraticCurveTo(37,31,46,33); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(54,29); ctx.quadraticCurveTo(63,27,72,31); ctx.stroke();
  } else {
    ctx.beginPath(); ctx.moveTo(28,32); ctx.quadraticCurveTo(37,29,46,32); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(54,32); ctx.quadraticCurveTo(63,29,72,32); ctx.stroke();
  }
}

// ── MOUTH ─────────────────────────────────────────────────────────────────
function dMouth(ctx,state){
  ctx.strokeStyle=P.out; ctx.lineCap='round'; ctx.lineJoin='round';

  if(state==='sleeping'){
    ctx.lineWidth=2; ctx.beginPath(); ctx.moveTo(44,65); ctx.lineTo(56,65); ctx.stroke();
    return;
  }
  if(state==='surprised'){
    oval(ctx,50,65,6,7); fs(ctx,P.bk,P.out,1.6); return;
  }
  if(state==='happy'||state==='celebrating'){
    ctx.lineWidth=2.5;
    ctx.beginPath(); ctx.moveTo(38,62); ctx.quadraticCurveTo(50,74,62,62); ctx.stroke();
    // Tongue
    ctx.beginPath(); ctx.ellipse(50,68,8,5,0,0,Math.PI);
    ctx.fillStyle=P.pk; ctx.fill(); return;
  }
  if(state==='sad'){
    ctx.lineWidth=2.5;
    ctx.beginPath(); ctx.moveTo(40,67); ctx.quadraticCurveTo(50,62,60,67); ctx.stroke();
    // Teardrop
    ctx.save(); ctx.globalAlpha=0.8;
    oval(ctx,34,55,2.5,3.5); ctx.fillStyle=P.bl; ctx.fill();
    ctx.restore(); return;
  }
  if(state==='angry'){
    ctx.lineWidth=2.2;
    ctx.beginPath();
    ctx.moveTo(40,65); ctx.bezierCurveTo(44,61,48,68,52,64); ctx.bezierCurveTo(56,60,60,65,62,63);
    ctx.stroke(); return;
  }
  if(state==='smart'){
    ctx.lineWidth=2.5;
    ctx.beginPath(); ctx.moveTo(44,65); ctx.quadraticCurveTo(55,71,62,63); ctx.stroke(); return;
  }
  if(state==='warning'){
    ctx.lineWidth=2;
    ctx.beginPath(); ctx.moveTo(42,65); ctx.lineTo(58,65); ctx.stroke(); return;
  }
  // Default gentle smile
  ctx.lineWidth=2.5;
  ctx.beginPath(); ctx.moveTo(40,62); ctx.quadraticCurveTo(50,71,60,62); ctx.stroke();
}

// ── ARMS / PAWS ───────────────────────────────────────────────────────────
function dPaw(ctx,cx,cy,r){ circ(ctx,cx,cy,r); fs(ctx,P.pw,P.out,1.5); }

function dArms(ctx,state){
  ctx.save(); ctx.lineCap='round';

  if(state==='happy'){
    // Right arm waving
    ctx.beginPath();
    ctx.moveTo(74,82); ctx.bezierCurveTo(82,72,86,60,84,50);
    ctx.bezierCurveTo(86,48,90,54,88,62);
    ctx.bezierCurveTo(86,72,82,80,76,88); ctx.closePath();
    fs(ctx, lg(ctx,76,50,76,88,[0,P.o3],[1,P.o1]));
    dPaw(ctx,84,50,7);
  } else if(state==='celebrating'){
    // Both arms up
    ctx.beginPath();
    ctx.moveTo(26,82); ctx.bezierCurveTo(18,72,14,60,16,50);
    ctx.bezierCurveTo(14,48,10,54,12,62);
    ctx.bezierCurveTo(14,72,18,80,24,88); ctx.closePath();
    fs(ctx,P.o1); dPaw(ctx,16,50,7);
    ctx.beginPath();
    ctx.moveTo(74,82); ctx.bezierCurveTo(82,72,86,60,84,50);
    ctx.bezierCurveTo(86,48,90,54,88,62);
    ctx.bezierCurveTo(86,72,82,80,76,88); ctx.closePath();
    fs(ctx,P.o1); dPaw(ctx,84,50,7);
  } else if(state==='thinking'||state==='confused'){
    ctx.beginPath();
    ctx.moveTo(26,82); ctx.bezierCurveTo(16,76,8,70,10,62);
    ctx.bezierCurveTo(8,60,5,66,7,72);
    ctx.bezierCurveTo(10,80,18,84,24,88); ctx.closePath();
    fs(ctx,P.o1); dPaw(ctx,10,62,7);
  } else if(state==='surprised'){
    ctx.beginPath();
    ctx.moveTo(26,80); ctx.bezierCurveTo(14,74,8,66,12,58);
    ctx.bezierCurveTo(8,56,6,62,10,68);
    ctx.bezierCurveTo(14,76,20,82,24,86); ctx.closePath();
    fs(ctx,P.o1); dPaw(ctx,12,58,7);
    ctx.beginPath();
    ctx.moveTo(74,80); ctx.bezierCurveTo(86,74,92,66,88,58);
    ctx.bezierCurveTo(92,56,94,62,90,68);
    ctx.bezierCurveTo(86,76,80,82,76,86); ctx.closePath();
    fs(ctx,P.o1); dPaw(ctx,88,58,7);
  } else if(state==='angry'){
    ctx.beginPath();
    ctx.moveTo(26,82); ctx.bezierCurveTo(14,86,8,93,11,99);
    ctx.bezierCurveTo(8,101,16,102,20,97);
    ctx.bezierCurveTo(22,92,24,87,26,84); ctx.closePath();
    fs(ctx,P.o1);
    ctx.beginPath();
    ctx.moveTo(74,82); ctx.bezierCurveTo(86,86,92,93,89,99);
    ctx.bezierCurveTo(92,101,84,102,80,97);
    ctx.bezierCurveTo(78,92,76,87,74,84); ctx.closePath();
    fs(ctx,P.o1);
  } else if(state==='working'){
    ctx.beginPath();
    ctx.moveTo(26,82); ctx.bezierCurveTo(14,78,4,78,2,86);
    ctx.bezierCurveTo(0,92,6,96,14,95);
    ctx.bezierCurveTo(20,94,24,88,26,85); ctx.closePath();
    fs(ctx,P.o1);
    // Book
    ctx.beginPath(); ctx.moveTo(0,80); ctx.arcTo(20,80,20,102,3);
    ctx.arcTo(20,102,0,102,3); ctx.arcTo(0,102,0,80,3); ctx.arcTo(0,80,20,80,3);
    ctx.closePath(); fs(ctx,P.b1,P.b2,1.5);
    ctx.beginPath(); ctx.moveTo(2,80); ctx.lineTo(2,102);
    ctx.strokeStyle=P.b2; ctx.lineWidth=2.5; ctx.stroke();
    ctx.beginPath(); ctx.moveTo(4,87); ctx.lineTo(18,87);
    ctx.strokeStyle='rgba(248,237,208,0.5)'; ctx.lineWidth=1.2; ctx.stroke();
    ctx.beginPath(); ctx.moveTo(4,91); ctx.lineTo(18,91); ctx.stroke();
  }

  ctx.restore();
}

// ── LEGS ──────────────────────────────────────────────────────────────────
function dLegs(ctx){
  // Left
  oval(ctx,35,113,11,7); fs(ctx,P.o1,P.out,1.8);
  oval(ctx,35,114,8,5); ctx.fillStyle=P.pw; ctx.fill();
  // Right
  oval(ctx,65,113,11,7); fs(ctx,P.o1,P.out,1.8);
  oval(ctx,65,114,8,5); ctx.fillStyle=P.pw; ctx.fill();
}

// ── EXTRAS (per-state decorations) ────────────────────────────────────────
function dExtras(ctx,state,frame){
  ctx.save(); ctx.lineCap='round'; ctx.lineJoin='round';

  if(state==='smart'){
    // Spinning sparkle
    const t=frame*0.06;
    ctx.save(); ctx.translate(84,18); ctx.rotate(t);
    ctx.beginPath();
    for(let i=0;i<4;i++){
      const a=(i*Math.PI)/2, b=a+Math.PI/4;
      if(i===0) ctx.moveTo(Math.cos(a)*13,Math.sin(a)*13);
      else ctx.lineTo(Math.cos(a)*13,Math.sin(a)*13);
      ctx.lineTo(Math.cos(b)*4,Math.sin(b)*4);
    }
    ctx.closePath(); ctx.fillStyle=P.yl; ctx.fill();
    ctx.strokeStyle=P.out; ctx.lineWidth=0.8; ctx.stroke();
    ctx.restore();
  }

  if(state==='thinking'){
    // Green question mark
    ctx.font='bold 20px sans-serif'; ctx.textBaseline='top';
    ctx.fillStyle=P.gn; ctx.fillText('?',78,12);
    // Animated dots
    const d=Math.floor(frame/18)%4;
    for(let i=0;i<3;i++){
      ctx.globalAlpha= i<d ? 1 : 0.2;
      circ(ctx,82+i*6,35,2.2); ctx.fillStyle=P.out; ctx.fill();
    }
    ctx.globalAlpha=1;
  }

  if(state==='confused'){
    ctx.font='bold 20px sans-serif'; ctx.textBaseline='top';
    ctx.fillStyle=P.bu; ctx.fillText('?',78,12);
  }

  if(state==='surprised'){
    ctx.strokeStyle=P.r2; ctx.lineWidth=3;
    // Left !! dashes
    ctx.beginPath(); ctx.moveTo(6,8); ctx.lineTo(10,18); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(13,5); ctx.lineTo(15,16); ctx.stroke();
    ctx.strokeStyle=P.yl;
    ctx.beginPath(); ctx.moveTo(87,8); ctx.lineTo(83,18); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(80,5); ctx.lineTo(78,16); ctx.stroke();
  }

  if(state==='celebrating'){
    // Left pompom
    ctx.save();
    for(let i=0;i<10;i++){
      const a=(i/10)*Math.PI*2, bv=i%2===0;
      circ(ctx,16+Math.cos(a)*10,44+Math.sin(a)*10, bv?5:4);
      ctx.fillStyle=bv?P.yl:'#F0B830'; ctx.fill();
    }
    circ(ctx,16,44,7); ctx.fillStyle=P.yl; ctx.fill();
    ctx.strokeStyle=P.out; ctx.lineWidth=1; ctx.stroke();
    // Right pompom
    for(let i=0;i<10;i++){
      const a=(i/10)*Math.PI*2, bv=i%2===0;
      circ(ctx,84+Math.cos(a)*10,44+Math.sin(a)*10, bv?5:4);
      ctx.fillStyle=bv?P.yl:'#F0B830'; ctx.fill();
    }
    circ(ctx,84,44,7); ctx.fillStyle=P.yl; ctx.fill();
    ctx.strokeStyle=P.out; ctx.lineWidth=1; ctx.stroke();
    // Confetti
    const cc=[P.yl,P.bu,P.pk,P.gn,P.r1,P.bl];
    for(let i=0;i<12;i++){
      const x=((i*13+frame*2)%90)+5;
      const y=((i*9+frame)%60)+5;
      ctx.save(); ctx.translate(x,y); ctx.rotate(frame*0.05+i);
      ctx.fillStyle=cc[i%6]; ctx.fillRect(-2.5,-2.5,5,5); ctx.restore();
    }
    ctx.restore();
  }

  if(state==='warning'){
    ctx.beginPath(); ctx.moveTo(82,26); ctx.lineTo(97,50); ctx.lineTo(67,50); ctx.closePath();
    ctx.fillStyle=P.yl; ctx.fill(); ctx.strokeStyle=P.out; ctx.lineWidth=1.5; ctx.stroke();
    ctx.fillStyle=P.out; ctx.fillRect(81,32,3.5,12); ctx.fillRect(81,46,3.5,3.5);
  }

  if(state==='working'){
    // Magnifying glass
    circ(ctx,84,24,11); ctx.strokeStyle=P.out; ctx.lineWidth=2.5; ctx.stroke();
    circ(ctx,84,24,7); ctx.strokeStyle='rgba(144,176,224,0.65)'; ctx.lineWidth=5; ctx.stroke();
    ctx.beginPath(); ctx.moveTo(92,32); ctx.lineTo(100,42);
    ctx.strokeStyle=P.out; ctx.lineWidth=3.5; ctx.stroke();
  }

  if(state==='sleeping'){
    // Green sleeping cap
    ctx.beginPath();
    ctx.moveTo(12,35); ctx.quadraticCurveTo(12,30,28,26);
    ctx.bezierCurveTo(34,20,44,8,48,2);
    ctx.bezierCurveTo(52,-2,54,10,52,18);
    ctx.bezierCurveTo(60,12,74,18,78,24);
    ctx.quadraticCurveTo(90,28,90,35); ctx.closePath();
    fs(ctx, lg(ctx,30,2,80,35,[0,P.gd],[0.5,P.gn],[1,P.gd]));
    // Pompom
    circ(ctx,47,2,8);
    fs(ctx, rg(ctx,45,0,1,8,[0,P.cw],[0.7,P.c1],[1,P.c2]), P.c2,1);

    // Zzz
    const zf=frame*0.025;
    const zs=[{t:'Z',x:78,y:22,s:17,a:Math.sin(zf)},
              {t:'Z',x:88,y:12,s:13,a:Math.sin(zf+1.2)},
              {t:'z',x:95,y:4,s:10,a:Math.sin(zf+2.4)}];
    ctx.font='bold {s}px sans-serif'; ctx.textBaseline='middle'; ctx.textAlign='center';
    for(const z of zs){
      ctx.save(); ctx.globalAlpha=Math.max(0,(z.a+1)/2);
      ctx.font=`bold ${z.s}px sans-serif`;
      ctx.fillStyle=P.bu; ctx.fillText(z.t,z.x,z.y);
      ctx.restore();
    }
    ctx.textAlign='start';
  }

  ctx.restore();
}

// ── MAIN DRAW ─────────────────────────────────────────────────────────────
function drawFilex(ctx, S, state, frame){
  ctx.save();
  ctx.scale(S, S);
  ctx.imageSmoothingEnabled = true; // smooth, NOT pixel art

  dTail(ctx, state);
  dEars(ctx);
  dArms(ctx, state);    // arms BEFORE body so body overlaps
  dBody(ctx);
  dLegs(ctx);
  dScarf(ctx);
  dBag(ctx);
  dHead(ctx);
  dMuzzle(ctx);
  dBlush(ctx);
  dNose(ctx);
  dEyes(ctx, state, frame);
  dMouth(ctx, state);
  dExtras(ctx, state, frame);

  ctx.restore();
}

// ── ANIMATION STATES ──────────────────────────────────────────────────────
// yo: y-offset in logical units per sub-frame (body bob)
const STATES = {
  idle:        { fps:1.2, yo:[0,0,-1,0,0,-1,0,0], loop:true  },
  happy:       { fps:3,   yo:[0,-2,-1,-2,0,-1],   loop:true  },
  smart:       { fps:2,   yo:[0,-1,0,-1],           loop:true  },
  thinking:    { fps:1.5, yo:[0,0,0,0],             loop:true  },
  working:     { fps:2.5, yo:[0,-1,0,-1,0],         loop:true  },
  surprised:   { fps:0,   yo:[-2],                   loop:false },
  celebrating: { fps:4,   yo:[0,-3,-1,-3,0,-2],     loop:true  },
  sad:         { fps:1,   yo:[0,1,0,1],              loop:true  },
  angry:       { fps:2,   yo:[0,1,0,1],              loop:true  },
  confused:    { fps:1.5, yo:[0,0,0],                loop:true  },
  warning:     { fps:1,   yo:[0,0],                  loop:true  },
  sleeping:    { fps:0.8, yo:[0,0,1,1,0,0],          loop:true  },
};

// ── MODULE STATE ──────────────────────────────────────────────────────────
let _state='idle', _subFrame=0, _tick=0, _frame=0, _lastTs=0;
let _bubble=null, _bubbleTmr=null, _thoughtTmr=null;
const _canvases=[];

function mountCanvas(el, pxParam){
  // pxParam is the CSS width you want divided by 100
  // (legacy: if someone passes 5 or 8 from old pixel-art code, clamp to sane S)
  let S = pxParam ? Math.min(pxParam, 4) : S_DEF;
  if(S > 10) S = S/100; // old px=150 style → 1.5
  if(S < 0.5) S = S_DEF;

  const dpr = window.devicePixelRatio || 1;
  el.width  = Math.round(W * S * dpr);
  el.height = Math.round(H * S * dpr);
  el.style.width  = Math.round(W * S) + 'px';
  el.style.height = Math.round(H * S) + 'px';
  const ctx = el.getContext('2d');
  ctx.scale(dpr, dpr);
  return { el, ctx, S };
}

function tick(ts){
  requestAnimationFrame(tick);
  const cfg = STATES[_state] || STATES.idle;
  const dt  = ts - _lastTs; _lastTs=ts; _frame++;

  if(cfg.fps>0 && cfg.yo.length>1){
    _tick += dt;
    const intv = 1000/cfg.fps;
    if(_tick >= intv){
      _tick -= intv;
      _subFrame = cfg.loop
        ? (_subFrame+1) % cfg.yo.length
        : Math.min(_subFrame+1, cfg.yo.length-1);
    }
  }

  const yOff = cfg.yo[_subFrame] || 0;
  for(const c of _canvases){
    c.ctx.save();
    c.ctx.translate(0, yOff * c.S);
    drawFilex(c.ctx, c.S, _state, _frame);
    c.ctx.restore();
  }
}

// ── BUBBLE ────────────────────────────────────────────────────────────────
function showBubble(text, type){
  if(!_bubble) return;
  clearTimeout(_bubbleTmr);
  _bubble.textContent=text;
  _bubble.className='lib-bubble-'+(type||'speech')+' visible';
  _bubbleTmr=setTimeout(()=>_bubble.classList.remove('visible'),
    type==='thought'?7000:5000);
}

// ── IDLE THOUGHTS ─────────────────────────────────────────────────────────
const THOUGHTS=[
  '¿Dónde habrás puesto ese archivo…?',
  'Organizar es un acto de amor hacia tu yo futuro.',
  'Una carpeta «misc» es la antesala del olvido.',
  'Detecto archivos sin clasificar… me llaman.',
  '¿«temp»? Ninguno es tan temporal como parece.',
  'Soy rápido, listo y un poco pillo. ¡Pero fiable!',
  'El 80% de los adjuntos de email nunca se reabren.',
  'Un buen nombre de archivo vale más que mil capturas.',
  'He encontrado 3 versiones del mismo contrato…',
  '¿Sabías que el orden digital reduce el estrés?',
  'Carpeta «Escritorio»… el purgatorio digital.',
  'Si lo indexas hoy, lo encuentras mañana.',
  'Mis orejas detectan archivos perdidos.',
  'No juzgo los nombres de tus archivos. Los catalogo.',
];
const GREETINGS=[
  '¡Hola! ¿En qué puedo ayudarte?',
  '¡Aquí estoy! A tus órdenes.',
  '¿Buscas algo? ¡Pregúntame!',
  '¡Me has pillado pensando!',
  '¡Buenos días! O tardes. O noches.',
  '¡Rápido, listo y siempre disponible!',
];
const PAGE_MSGS={
  '/':         ['¡Dashboard listo!','¡Bienvenido de nuevo!'],
  '/scan':     ['A por esos archivos.','¡Listo para escanear!'],
  '/chat':     ['¡Pregúntame lo que quieras!','Soy todo oídos.'],
  '/plan':     ['Plan de organización.','¡Vamos a ordenar esto!'],
  '/archivos': ['Biblioteca cargada.','Todos los archivos a la vista.'],
  '/explorar': ['Explorador listo.'],
  '/dashboard':['Analítica cargada.'],
};

function scheduleThought(){
  clearTimeout(_thoughtTmr);
  _thoughtTmr=setTimeout(fireThought, 22000+Math.random()*18000);
}
function fireThought(){
  if(_state!=='idle'){ scheduleThought(); return; }
  _state='thinking'; _subFrame=0;
  showBubble(THOUGHTS[Math.floor(Math.random()*THOUGHTS.length)],'thought');
  setTimeout(()=>{
    if(_state==='thinking'){ _state='idle'; _subFrame=0; }
    scheduleThought();
  },7000);
}

// ── PUBLIC API ────────────────────────────────────────────────────────────
function setState(state, msg){
  if(!STATES[state]) return;
  _state=state; _subFrame=0; _tick=0;
  clearTimeout(_thoughtTmr);
  if(msg) showBubble(msg,'speech');
  else if(_bubble) _bubble.classList.remove('visible');
  if(state==='idle') scheduleThought();
}

window.filexSetState     = setState;
window.librarianSetState = setState;  // backwards-compat
window.librarianMount    = function(el,px){ if(el) _canvases.push(mountCanvas(el,px)); };
window.filexMount        = window.librarianMount;

// ── INIT ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', ()=>{
  const sidebar = document.getElementById('lib-canvas');
  if(sidebar) _canvases.push(mountCanvas(sidebar, S_DEF));

  document.querySelectorAll('[data-lib-canvas]').forEach(el=>{
    const px = parseFloat(el.dataset.libPx) || S_DEF;
    _canvases.push(mountCanvas(el, px));
  });

  _bubble = document.getElementById('lib-bubble');

  const widget = document.getElementById('lib-widget');
  sidebar?.addEventListener('click', ()=>{
    widget?.classList.add('lib-jump');
    setTimeout(()=>widget?.classList.remove('lib-jump'),700);
    clearTimeout(_thoughtTmr);
    setState('happy', GREETINGS[Math.floor(Math.random()*GREETINGS.length)]);
    setTimeout(()=>setState('idle'),4000);
  });

  const path = window.location.pathname;
  const key  = Object.keys(PAGE_MSGS).find(k=>path===k||path.startsWith(k+'/'))||'/';
  const msgs = PAGE_MSGS[key]||PAGE_MSGS['/'];
  setTimeout(()=>showBubble(msgs[Math.floor(Math.random()*msgs.length)],'speech'),900);

  const orig = window._applyState;
  if(typeof orig==='function'){
    window._applyState=function(s){
      orig(s);
      if     (s.running&&s.fase==='escaneando')  setState('working',    'Escaneando archivos…');
      else if(s.running&&s.fase==='analizando')  setState('thinking',   'Analizando con IA…');
      else if(!s.running&&s.fase==='completado') setState('celebrating','¡Escaneo completado!');
      else if(!s.running&&s.fase==='error')      setState('sad',        'Vaya, algo falló.');
    };
  }

  _lastTs = performance.now();
  requestAnimationFrame(tick);
  scheduleThought();
});

})();
