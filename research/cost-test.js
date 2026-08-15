const fs=require('fs');
const src=fs.readFileSync('/home/user/investor-help/investor-dashboard.html','utf8');
function grab(name){
  const sig='function '+name+'(';
  const i=src.indexOf(sig); if(i<0)throw new Error('missing '+name);
  let p=0,k=i+sig.length-1;
  for(;k<src.length;k++){if(src[k]==='(')p++;else if(src[k]===')'){p--;if(p===0){k++;break;}}}
  const j=src.indexOf('{',k); let d=0;
  for(let m=j;m<src.length;m++){if(src[m]==='{')d++;else if(src[m]==='}'){d--;if(d===0)return src.slice(i,m+1);}}
  throw new Error('unbalanced '+name);
}
const names=['barsPerYear','barsFor','calcSMA','calcEMA','calcRSI','calcMACD','calcBB',
 'calcDonchian','calcStoch','calcATR','calcCCI','calcZScore','calcSuperTrend','calcKeltner',
 'calcParabolicSAR','calcSharpe','calcMaxDD','computeSignals','combineSignals',
 'perfMetrics','calcRealizedVol','alignRows','gearingCosts','runRotation'];
fs.writeFileSync(__dirname+'/cost-lib.js',
  names.map(grab).join('\n')+'\nconst ROT_COST=0.0005;\nmodule.exports={'+names.join(',')+'};');
const L=require('./cost-lib.js');

const raw=JSON.parse(fs.readFileSync('/home/user/investor-help/public/study/leveraged.json','utf8'));
const toRows=k=>raw[k].rows.map(r=>({time:r.t,open:r.c,high:r.c,low:r.c,close:r.c,volume:0}));
const [base,lev]=L.alignRows(toRows('QQQ'),toRows('TQQQ'));

const c=L.gearingCosts(base.map(r=>r.close),lev.map(r=>r.close),252);
console.log('=== gearing cost decomposition, QQQ/TQQQ 2010-2026 ===');
console.log(`window                ${c.yrs.toFixed(1)} yrs, realized sigma ${c.sigma.toFixed(1)}%`);
console.log(`QQQ 1x                ${c.baseGrowth.toFixed(1)}x   CAGR ${c.baseCagr.toFixed(2)}%`);
console.log(`3x, no daily reset    ${c.frictionlessGrowth.toFixed(0)}x   CAGR ${c.frictionlessCagr.toFixed(2)}%   (reference)`);
console.log(`daily-reset, no fees  ${c.decayGrowth.toFixed(1)}x   CAGR ${c.decayCagr.toFixed(2)}%   decay ${c.decayDrag.toFixed(2)} pts/yr`);
console.log(`actual TQQQ           ${c.actualGrowth.toFixed(1)}x   CAGR ${c.actualCagr.toFixed(2)}%   fees ${c.feeDrag.toFixed(2)} pts/yr`);
console.log(`total wrapper drag    ${c.totalDrag.toFixed(2)} pts/yr`);
console.log(`textbook -3*sigma^2   ${c.theoryDecay.toFixed(2)} pts/yr  (vs measured ${c.decayDrag.toFixed(2)})`);

console.log('\n--- cross-checks ---');
let fail=0;
const chk=(n,ok,x)=>{console.log((ok?'  PASS  ':'  FAIL  ')+n+(x?'   '+x:''));if(!ok)fail++;};
// decay + fees should compose to the total (in CAGR space, additively by construction)
chk('decay matches -3*sigma^2 theory within 1.5 pts',
    Math.abs(c.decayDrag-c.theoryDecay)<1.5, `measured ${c.decayDrag.toFixed(2)} vs theory ${c.theoryDecay.toFixed(2)}`);
const comp=((1+c.decayDrag/100)*(1+c.feeDrag/100)-1)*100;
chk('decay x fees compose to total (multiplicative)',
    Math.abs(comp-c.totalDrag)<1e-6, `${comp.toFixed(4)} vs ${c.totalDrag.toFixed(4)}`);
// actual TQQQ CAGR must match the earlier python calibration (43.26%)
chk('actual TQQQ CAGR ~ 43.3% (python: 43.26%)', Math.abs(c.actualCagr-43.26)<0.15, c.actualCagr.toFixed(2)+'%');
// fee drag should land near the -4.81%/yr measured in the study
chk('fee+financing drag ~ study figure', c.feeDrag<0 && c.feeDrag>-8, c.feeDrag.toFixed(2)+' pts/yr');
// decay must be negative and larger in magnitude at higher vol
chk('decay is a cost (negative)', c.decayDrag<0, c.decayDrag.toFixed(2));

console.log('\n--- friction attribution across cost/tax settings ---');
console.log('cost  tax   netCAGR  tradeDrag   taxDrag  totalDrag   $cost    $tax  switches');
for(const [cost,tax] of [[0,0],[0.0005,0],[0.002,0],[0.005,0],[0.0005,0.26],[0.0005,0.45]]){
  const r=L.runRotation('sma_50_200',base,lev,null,0.25,null,'none',{cost,taxRate:tax});
  const f=r.friction;
  console.log(
    `${(cost*1e4).toFixed(0).padStart(3)}bp ${(tax*100).toFixed(0).padStart(3)}%  `
    +`${f.netCagr.toFixed(2).padStart(7)}%  `
    +`${(f.tradeDrag==null?'—':f.tradeDrag.toFixed(2)).padStart(8)}  `
    +`${(f.taxDrag==null?'—':f.taxDrag.toFixed(2)).padStart(8)}  `
    +`${f.totalDrag.toFixed(2).padStart(8)}  `
    +`${('$'+Math.round(f.costPaid)).padStart(7)} ${('$'+Math.round(f.taxPaid)).padStart(7)}  ${String(f.switches).padStart(4)}`);
}

console.log('\n--- invariants ---');
const a=L.runRotation('sma_50_200',base,lev,null,0.25,null,'none',{cost:0,taxRate:0});
chk('zero cost => zero drag', Math.abs(a.friction.totalDrag)<1e-9, a.friction.totalDrag.toFixed(6));
chk('zero cost => $0 paid', a.friction.costPaid<1e-6 && a.friction.taxPaid<1e-6);
const b=L.runRotation('sma_50_200',base,lev,null,0.25,null,'none',{cost:0.005,taxRate:0});
chk('higher cost => lower net CAGR', b.friction.netCagr<a.friction.netCagr,
    `${b.friction.netCagr.toFixed(2)}% < ${a.friction.netCagr.toFixed(2)}%`);
const t=L.runRotation('sma_50_200',base,lev,null,0.25,null,'none',{cost:0.0005,taxRate:0.45});
chk('tax reduces net CAGR further', t.friction.netCagr<b.friction.netCagr||t.friction.taxDrag<0,
    `taxDrag ${t.friction.taxDrag.toFixed(2)}`);
const fc=((1+t.friction.tradeDrag/100)*(1+(t.friction.taxDrag||0)/100)-1)*100;
chk('friction components compose to total',
    Math.abs(fc-t.friction.totalDrag)<1e-6,
    `${fc.toFixed(4)} vs ${t.friction.totalDrag.toFixed(4)}`);
process.exit(fail?1:0);
