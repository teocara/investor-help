/* Cross-check the browser rotation engine against the Python study by feeding
   it the same actual TQQQ/QQQ daily bars and comparing headline metrics. */
const fs=require('fs');
const src=fs.readFileSync('/home/user/investor-help/investor-dashboard.html','utf8');
function grab(name){
  const sig='function '+name+'(';
  const i=src.indexOf(sig); if(i<0)throw new Error('missing '+name);
  /* skip the parameter list first — a destructured param like ({a,b}) would
     otherwise be mistaken for the function body */
  let p=0,k=i+sig.length-1;
  for(;k<src.length;k++){
    if(src[k]==='(')p++;else if(src[k]===')'){p--;if(p===0){k++;break;}}
  }
  const j=src.indexOf('{',k); let d=0;
  for(let m=j;m<src.length;m++){
    if(src[m]==='{')d++;else if(src[m]==='}'){d--;if(d===0)return src.slice(i,m+1);}
  }
  throw new Error('unbalanced '+name);
}
const names=['barsPerYear','barsFor','calcSMA','calcEMA','calcRSI','calcMACD','calcBB',
 'calcDonchian','calcStoch','calcATR','calcCCI','calcZScore','calcSuperTrend','calcKeltner',
 'calcParabolicSAR','calcSharpe','calcMaxDD','computeSignals','combineSignals',
 'perfMetrics','runBacktest','calcRealizedVol','alignRows','runRotation','fmtAnnual'];
const code=names.map(grab).join('\n')+'\nconst ROT_COST=0.0005;\n'
  +'module.exports={'+names.join(',')+'};';
fs.writeFileSync(__dirname+'/rot-lib.js',code);
const L=require('./rot-lib.js');

const raw=JSON.parse(fs.readFileSync('/home/user/investor-help/public/study/leveraged.json','utf8'));
const toRows=k=>raw[k].rows.map(r=>({time:r.t,open:r.c,high:r.c,low:r.c,close:r.c,volume:0}));
const [base,lev]=L.alignRows(toRows('QQQ'),toRows('TQQQ'));
console.log(`aligned ${base.length} daily bars  ${base[0].time} -> ${base[base.length-1].time}`);
console.log(`barsPerYear detected: ${L.barsPerYear(base)}`);

const show=(name,r)=>console.log(
  `${name.padEnd(42)}CAGR ${String(r.cagr==null?'—':r.cagr.toFixed(1)+'%').padStart(7)}`
  +`  MaxDD ${('-'+r.maxDD+'%').padStart(8)}`
  +`  Sharpe ${String(r.sharpe??'—').padStart(5)}`
  +`  Calmar ${String(r.calmar==null?'—':r.calmar.toFixed(2)).padStart(5)}`
  +`  Expo ${r.exposure.toFixed(0).padStart(3)}%`
  +`  sw ${String(r.trades.length).padStart(3)}`
  +`  x${(r.finalEq/10000).toFixed(1)}`);

console.log('\n--- rotation engine (JS, in-app) ---');
for(const [nm,def,vol] of [
  ['200d trend -> cash',            null,'cash',   0],
  ['200d trend -> QQQ',             'q', 'qqq',    0],
  ['200d trend + vol<35% -> cash',  null,'cash',0.35],
  ['200d trend + vol<25% -> cash',  null,'cash',0.25],
]){}
const cases=[
  ['ma_250_trend','cash',0,     '250d trend -> cash'],
  ['sma_50_200','cash',0,       'golden cross -> cash'],
  ['sma_50_200','QQQ',0,        'golden cross -> QQQ 1x'],
  ['sma_50_200','cash',0.35,    'golden cross + vol<35% -> cash'],
  ['sma_50_200','cash',0.25,    'golden cross + vol<25% -> cash'],
  ['ma_250_trend','cash',0.35,  '250d trend + vol<35% -> cash'],
];
for(const [strat,def,vol,nm] of cases){
  const r=L.runRotation(strat,base,lev,def==='QQQ'?base:null,vol,null,'none');
  show(nm,r);
}

console.log('\n--- benchmarks embedded in the result ---');
const r=L.runRotation('sma_50_200',base,lev,null,0.35,null,'none');
console.log(`TQQQ buy&hold : ${r.bhReturn}%  CAGR ${r.bhCagr.toFixed(1)}%  MaxDD -${r.bhMaxDD}%`);
console.log(`QQQ  buy&hold : ${r.baseReturn}%  CAGR ${r.baseCagr.toFixed(1)}%  MaxDD -${r.baseMaxDD}%`);
console.log(`python study   : TQQQ 39.6% / -81.7%   QQQ 18.8% / -35.1%`);

console.log('\n--- invariants ---');
let bad=[];
for(const [strat,def,vol,nm] of cases){
  const x=L.runRotation(strat,base,lev,def==='QQQ'?base:null,vol,null,'none');
  if(!isFinite(x.finalEq)||x.finalEq<=0)bad.push(nm+': finalEq');
  if(x.exposure<0||x.exposure>100.01)bad.push(nm+': exposure '+x.exposure);
  if(x.equity.length!==base.length)bad.push(nm+': equity len '+x.equity.length+' vs '+base.length);
  if(def==='QQQ'&&x.exposure<99&&Math.abs(x.exposure-100)<0.001)bad.push(nm+': expo');
}
console.log(bad.length?('FAIL: '+bad.join(' | ')):'all invariants hold');
