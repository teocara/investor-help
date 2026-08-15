const fs=require('fs');
const src=fs.readFileSync('/home/user/investor-help/investor-dashboard.html','utf8');
function grab(n){const sig='function '+n+'(';const i=src.indexOf(sig);
 if(i<0)throw new Error('missing '+n);
 let p=0,k=i+sig.length-1;
 for(;k<src.length;k++){if(src[k]==='(')p++;else if(src[k]===')'){p--;if(p===0){k++;break;}}}
 const j=src.indexOf('{',k);let d=0;
 for(let m=j;m<src.length;m++){if(src[m]==='{')d++;else if(src[m]==='}'){d--;if(d===0)return src.slice(i,m+1);}}}
const names=['barsPerYear','barsFor','calcSMA','calcEMA','calcRSI','calcMACD','calcBB','calcDonchian',
 'calcStoch','calcATR','calcCCI','calcZScore','calcSuperTrend','calcKeltner','calcParabolicSAR',
 'calcSharpe','calcMaxDD','computeSignals','combineSignals','perfMetrics','calcRealizedVol',
 'toEUR','alignRows','gearingCosts','runRotation'];
fs.writeFileSync(__dirname+'/ladder-lib.js',
  names.map(grab).join('\n')+'\nconst ROT_COST=0.0005;\nmodule.exports={'+names.join(',')+'};');
const L=require('./ladder-lib.js');

const D=JSON.parse(fs.readFileSync('/home/user/investor-help/public/study/leveraged.json','utf8'));
const S={}; for(const k in D) S[k]=Object.fromEntries(D[k].rows.map(r=>[r.t,r.c]));
const mk=m=>Object.entries(m).sort().map(([t,c])=>({time:t,open:c,high:c,low:c,close:c,volume:0}));
const fxRows=mk(S['EURUSD=X']);

function setup(levKey,eurQuote){
  let base=mk(S.QQQ), lev=mk(S[levKey]);
  if(eurQuote) base=L.toEUR(base,fxRows);
  return L.alignRows(base,lev);
}

const row=(nm,r,extra='')=>{
  const rr=r.rungs||{};
  console.log(`${nm.padEnd(38)}`
   +`${r.cagr.toFixed(1).padStart(6)}%`
   +`${('-'+r.maxDD+'%').padStart(9)}`
   +`${String(r.sharpe??'—').padStart(7)}`
   +`${(r.calmar==null?0:r.calmar).toFixed(2).padStart(8)}`
   +`${('x'+(r.finalEq/10000).toFixed(1)).padStart(9)}`
   +`${String(r.trades.length).padStart(5)}`
   +(rr.ladder?`   ${rr.geared.toFixed(0)}/${rr.index.toFixed(0)}/${rr.defensive.toFixed(0)}`:'')
   +extra);
};
const HDR='strategy'.padEnd(38)+'CAGR'.padStart(7)+'MaxDD'.padStart(9)+'Sharpe'.padStart(7)
  +'Calmar'.padStart(8)+'mult'.padStart(9)+'sw'.padStart(5)+'   rungs %';

for(const [levKey,eurQuote,lag,mult,label] of [
      ['TQQQ',false,0,3,'TQQQ 3× (USD)'],
      ['LQQ.PA',true,1,2,'LQQ 2× (EUR, +1d lag)']]){
  const [base,lev]=setup(levKey,eurQuote);
  const opts=n=>Object.assign({cost:0.0005,execLag:lag,levMult:mult},n);
  console.log('\n'+'='.repeat(96));
  console.log(`${label}   ${base[0].time} -> ${base[base.length-1].time}   ${(base.length/252).toFixed(1)} yrs`);
  console.log(HDR); console.log('-'.repeat(96));

  const A='sma_50_200', B='ma_250_trend';
  // binary, cash
  row('binary → cash',        L.runRotation(A,base,lev,null,0.35,null,'none',opts({})));
  // binary, QQQ defensive
  row('binary → QQQ 1×',      L.runRotation(A,base,lev,base,0.35,null,'none',opts({})));
  // combined AND/OR, QQQ defensive
  for(const lg of ['and','or','filter'])
    row(`combine ${lg.toUpperCase().padEnd(6)} → QQQ 1×`, L.runRotation(A,base,lev,base,0.35,B,lg,opts({})));
  // ladder
  row('LADDER → QQQ 1× → cash',  L.runRotation(A,base,lev,null,0.35,B,'none',opts({ladder:true})));
  row('LADDER → QQQ 1× → QQQ 1×',L.runRotation(A,base,lev,base,0.35,B,'none',opts({ladder:true})));
  row('LADDER no vol brake',     L.runRotation(A,base,lev,base,0,   B,'none',opts({ladder:true})));

  // benchmarks
  const bh=L.runRotation(A,base,lev,null,0,null,'none',opts({}));
  console.log('-'.repeat(96));
  console.log(`${'buy & hold geared'.padEnd(38)}${bh.bhCagr.toFixed(1).padStart(6)}%${('-'+bh.bhMaxDD+'%').padStart(9)}`
    +`${''.padStart(7)}${(bh.bhCagr/ +bh.bhMaxDD).toFixed(2).padStart(8)}`);
  console.log(`${'buy & hold QQQ 1×'.padEnd(38)}${bh.baseCagr.toFixed(1).padStart(6)}%${('-'+bh.baseMaxDD+'%').padStart(9)}`);
}

console.log('\n\n=== invariants ===');
let fail=0;
const chk=(n,ok,x)=>{console.log((ok?'  PASS  ':'  FAIL  ')+n+(x?'   '+x:''));if(!ok)fail++;};
const [base,lev]=setup('TQQQ',false);
const o={cost:0.0005,levMult:3};
const lad=L.runRotation('sma_50_200',base,lev,base,0.35,'ma_250_trend','none',Object.assign({ladder:true},o));
chk('ladder reports three rungs', !!lad.rungs && lad.rungs.ladder===true);
chk('rung shares sum to 100%',
    Math.abs(lad.rungs.geared+lad.rungs.index+lad.rungs.defensive-100)<1e-6,
    (lad.rungs.geared+lad.rungs.index+lad.rungs.defensive).toFixed(4));
chk('ladder spends real time on the 1x rung', lad.rungs.index>1, lad.rungs.index.toFixed(1)+'%');
const binNoB=L.runRotation('sma_50_200',base,lev,base,0.35,null,'none',Object.assign({ladder:true},o));
chk('ladder without a 2nd strategy falls back to binary',
    !binNoB.rungs.ladder && binNoB.rungs.index===0);
const z=L.runRotation('sma_50_200',base,lev,base,0.35,'ma_250_trend','none',
                      Object.assign({},o,{ladder:true,cost:0}));
chk('zero cost => no friction drag', Math.abs(z.friction.totalDrag)<1e-9);
chk('geared exposure equals rung-2 share',
    Math.abs(z.exposure-z.rungs.geared)<0.5, `${z.exposure.toFixed(1)} vs ${z.rungs.geared.toFixed(1)}`);
process.exit(fail?1:0);
