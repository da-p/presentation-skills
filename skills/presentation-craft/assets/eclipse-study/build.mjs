import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
const {Presentation, PresentationFile} = await import(process.env.PRESENTATION_ARTIFACT_MODULE || '@oai/artifact-tool');

const root=path.dirname(fileURLToPath(import.meta.url));
const mode=process.argv[2]||'deck';
const C={bg:'#101722',ink:'#F3EDDF',muted:'#A9B7C6',sun:'#FFD68B',earth:'#5D98BC',moon:'#060B12',line:'#354553',shadow:'#03070D',plane:'#1D354B',orbit:'#8CD3E2'};
const P=Presentation.create({slideSize:{width:1280,height:720}});
const checks=[];
const SKILL=process.env.PRESENTATION_TECHNICAL_SKILL;


function box(s,x,y,w,h,fill,geometry='rect',stroke='none',sw=0){return s.shapes.add({geometry,position:{left:x,top:y,width:w,height:h},fill,line:{fill:stroke,width:sw,style:'solid'}});}
function txt(s,v,x,y,w,h,size=24,color=C.ink,bold=false,font='Arial'){const t=box(s,x,y,w,h,'none','textbox');t.text=v;t.text.style={fontSize:size,typeface:font,color,bold,verticalAlignment:'top',insets:0,autoFit:'none',wrap:'square'};return t;}
function route(s,pts,color=C.line,sw=1,fill='none',close=false){const xs=pts.map(a=>a[0]),ys=pts.map(a=>a[1]),x=Math.min(...xs),y=Math.min(...ys),w=Math.max(...xs)-x||.01,h=Math.max(...ys)-y||.01;return s.shapes.add({geometry:'custom',position:{left:x,top:y,width:w,height:h},fill,line:{fill:color,width:sw,style:'solid'},customPaths:[{width:w,height:h,commands:[{moveTo:{x:pts[0][0]-x,y:pts[0][1]-y}},...pts.slice(1).map(a=>({lineTo:{x:a[0]-x,y:a[1]-y}})),...(close?[{close:{}}]:[])]}]});}
const poly=(s,p,f)=>route(s,p,'none',0,f,true);
const line=(s,x1,y1,x2,y2,c=C.line,w=1)=>route(s,[[x1,y1],[x2,y2]],c,w);
const disc=(s,x,y,r,c,stroke='none',sw=0)=>box(s,x-r,y-r,r*2,r*2,c,'ellipse',stroke,sw);
const add=(a,b)=>[a[0]+b[0],a[1]+b[1]], sub=(a,b)=>[a[0]-b[0],a[1]-b[1]], mul=(a,k)=>[a[0]*k,a[1]*k], dot=(a,b)=>a[0]*b[0]+a[1]*b[1];
function mix(a,b,t){const n=h=>[1,3,5].map(i=>parseInt(h.slice(i,i+2),16));const A=n(a),B=n(b);return '#'+A.map((v,i)=>Math.round(v+(B[i]-v)*t).toString(16).padStart(2,'0')).join('');}
function dashed(s,a,b,c,w=1,dash=7,gap=6){const v=sub(b,a),L=Math.hypot(...v),u=mul(v,1/L);for(let d=0;d<L;d+=dash+gap)route(s,[add(a,mul(u,d)),add(a,mul(u,Math.min(L,d+dash)))],c,w);}
function arc(s,c,r,a,b,color,width=1,n=40){route(s,Array.from({length:n+1},(_,i)=>[c[0]+r*Math.cos(a+(b-a)*i/n),c[1]+r*Math.sin(a+(b-a)*i/n)]),color,width);}

function base(n,title,subtitle='',footer='Размеры и расстояния условны. Схемы показывают пространственные отношения.'){const s=P.slides.add();s.background.fill=C.bg;txt(s,`0${n}`,1183,27,50,28,18,C.muted);txt(s,title,48,83,1184,114,46,C.ink,false,'Georgia');if(subtitle)txt(s,subtitle,48,199,1184,70,24,C.muted);line(s,48,669,1232,669);txt(s,footer,48,683,1184,22,13,C.muted);s.speakerNotes.text='Источники: https://science.nasa.gov/eclipses/types/ ; https://science.nasa.gov/eclipses/geometry/ . Проверены 17.11.2026. Авторские условные схемы, без соблюдения астрономического масштаба. Касательные вычислены по окружностям; корона — схематическая белая неоднородная атмосфера. Все тексты и фигуры редактируются.';return s;}

// Общие внешние касательные к Солнцу и Луне. Каждая граница тени
// является тем же прямым лучом, без перелома на поверхности Луны.
function tangentGeometry(S,R,M,r,E,Re){const v=sub(M,S),D=Math.hypot(...v),u=mul(v,1/D),perp=[-u[1],u[0]],k=(R-r)/D,h=Math.sqrt(1-k*k);const apex=add(S,mul(u,R*D/(R-r)));const rays=[-1,1].map(sign=>{const normal=add(mul(u,k),mul(perp,sign*h));const sun=add(S,mul(normal,R)),moon=add(M,mul(normal,r));const d=mul(sub(apex,moon),1/Math.hypot(...sub(apex,moon)));const q=sub(moon,E),B=2*dot(q,d),A=dot(q,q)-Re*Re,disc=B*B-4*A;let hit=null;if(disc>=0){const ts=[(-B-Math.sqrt(disc))/2,(-B+Math.sqrt(disc))/2].filter(t=>t>=0);if(ts.length)hit=add(moon,mul(d,Math.min(...ts)));}return{normal,sun,moon,hit};});return{S,R,M,r,E,Re,D,u,apex,rays};}
function geometryCheck(g,name,shouldHit){const errors=g.rays.map(q=>({sunRadiusError:Math.abs(Math.hypot(...sub(q.sun,g.S))-g.R),moonRadiusError:Math.abs(Math.hypot(...sub(q.moon,g.M))-g.r),tangencyDot:Math.abs(dot(sub(q.moon,q.sun),q.normal))}));const earthAxis=dot(sub(g.E,g.S),g.u),apexAxis=dot(sub(g.apex,g.S),g.u);const pass=errors.every(e=>Object.values(e).every(v=>v<1e-7)) && (shouldHit?g.rays.every(r=>r.hit && Math.hypot(...sub(r.hit,r.moon)) < Math.hypot(...sub(g.apex,r.moon)))&&apexAxis>earthAxis-g.Re:g.rays.every(r=>!r.hit));checks.push({name,expected:shouldHit?'umbra reaches Earth':'shadow misses Earth',sun:g.S,sunRadius:g.R,moon:g.M,moonRadius:g.r,earth:g.E,earthRadius:g.Re,apex:g.apex,earthNearAxis:earthAxis-g.Re,apexAxis,errors,pass});if(!pass)throw Error('Geometry verification failed: '+name);}
function verifyPenumbraMiss(g){const k=(g.R+g.r)/g.D,h=Math.sqrt(1-k*k),perp=[-g.u[1],g.u[0]],q=sub(g.E,g.M),t=dot(q,g.u),w=Math.abs(dot(q,perp)),clearance=h*w-k*t-g.r-g.Re;const pass=clearance>0;checks.push({name:'slide 3: penumbra also misses Earth',penumbraClearance:clearance,pass});if(!pass)throw Error('Penumbra intersects Earth in the no-eclipse scene');}
function shadowScene(s,{S,R,M,r,E,Re,light=false,name='scene',hit=true,observer=false}){const g=tangentGeometry(S,R,M,r,E,Re);geometryCheck(g,name,hit);if(!hit)verifyPenumbraMiss(g);const sun=light?'#C88729':C.sun,moon=light?'#1D2E3F':C.moon,shadow=light?'#BBC5CC':C.shadow;
  const ends=g.rays.map(q=>q.hit??g.apex);
  poly(s,[g.rays[0].moon,ends[0],ends[1],g.rays[1].moon],shadow);
  g.rays.forEach((q,i)=>route(s,[q.sun,ends[i]],light?'#A27B48':'#B49869',1.3));
  disc(s,...S,R,sun);disc(s,...M,r,moon,light?'#708394':'#697E8D',.8);disc(s,...E,Re,C.earth);
  if(hit){const angs=g.rays.map(q=>Math.atan2(q.hit[1]-E[1],q.hit[0]-E[0]));let a=angs[0],b=angs[1];if(a<0)a+=Math.PI*2;if(b<0)b+=Math.PI*2;arc(s,E,Re,Math.min(a,b),Math.max(a,b),moon,4);if(observer)disc(s,E[0]-Re,E[1],4,light?'#FFF6DC':C.ink);}
  return g;
}

// Корона: вложенные некруговые контуры с плавным спадом яркости.
// Солнечный диск под Луной не рисуется, жёлтой каймы нет.
function corona(s,x,y,r,bg=C.bg){const f=a=>.24+.32*Math.pow(Math.cos(a-.18),8)+.17*Math.pow(Math.cos(a+1.2),12)+.065*Math.sin(7*a+.7)+.045*Math.sin(13*a+1.1)+.025*Math.sin(23*a);for(let j=44;j>=1;j--){const t=j/44;const pts=Array.from({length:240},(_,i)=>{const a=i*Math.PI*2/240,rr=r*(1+t*Math.max(.15,f(a)));return[x+rr*Math.cos(a),y+rr*Math.sin(a)];});poly(s,pts,mix(bg,'#FFFFFF',Math.pow(1-t,2.9)*.91));}disc(s,x,y,r,C.moon);}
function eclipse(s,x,y,r,kind){if(kind==='total'){corona(s,x,y,r);return;}disc(s,x,y,r,C.sun);disc(s,x+(kind==='partial'?r*.7:0),y-(kind==='partial'?r*.30:0),r*(kind==='annular'?.79:1.02),C.moon);}

function first(light=false){const s=light?P.slides.add():base(1,'Луна закрывает Солнце\nдля части Земли','В новолуние Луна находится между Солнцем и Землёй.\nЗатмение видно там, куда попадает её тень.','Показана полная тень. Размеры небесных тел и расстояния условны.');const ink=light?'#24374B':C.ink,muted=light?'#526578':C.muted;if(light){s.background.fill='#F3EAD9';txt(s,'АСТРОНОМИЧЕСКИЙ АТЛАС',48,29,1100,24,14,muted,true);txt(s,'Луна закрывает Солнце\nдля части Земли',48,83,1184,114,46,ink,false,'Georgia');txt(s,'В новолуние Луна находится между Солнцем и Землёй.\nЗатмение видно там, куда попадает её тень.',48,199,1184,70,24,muted);}
  const S=[145,426],M=[650,426],E=[1060,426];shadowScene(s,{S,R:78,M,r:38,E,Re:78,light,name:light?'atlas':'slide 1',observer:true});
  txt(s,'Солнце',74,319,180,34,26,ink);txt(s,'Луна',610,348,160,32,25,ink);txt(s,'Земля',1012,319,190,34,26,ink);
  txt(s,'Полная тень',745,456,230,34,22,muted);
  route(s,[[E[0]-78,E[1]],[930,553],[750,553]],muted,1.1);txt(s,'Наблюдатель здесь видит\nполное затмение',750,573,460,65,25,ink);
  txt(s,'Свет идёт по прямой.\nЛуна преграждает ему путь.',48,566,590,68,25,ink);
  if(light){line(s,48,669,1232,669,'#C4BAA8');txt(s,'Показана полная тень. Размеры небесных тел и расстояния условны.',48,683,1184,22,13,muted);}
  return s;
}
function second(){const s=base(2,'Три вида затмения с Земли','Вид зависит от положения наблюдателя и видимого размера Луны.','Три вида показаны для сравнения; это не последовательность фаз одного затмения.');const xs=[226,640,1054];xs.forEach((x,i)=>{eclipse(s,x,370,88,['partial','total','annular'][i]);});
  const names=['Частное','Полное','Кольцеобразное'];const text=['Луна закрывает\nчасть солнечного диска.','Солнечный диск скрыт.\nВокруг видна белая корона —\nвнешняя атмосфера Солнца.','Луна дальше от Земли\nи выглядит меньше Солнца.\nВиден край солнечного диска.'];
  [430,850].forEach(x=>line(s,x,286,x,621,C.line));
  for(let i=0;i<3;i++){txt(s,names[i],xs[i]-170,498,360,46,30,i===1?C.ink:C.sun,true);txt(s,text[i],xs[i]-170,553,360,94,22,C.ink);}
  txt(s,'корона',700,258,140,25,17,C.muted);line(s,712,285,704,303,C.muted);txt(s,'солнечный диск',1043,263,185,25,17,C.sun);line(s,1103,291,1091,300,C.sun);
  return s;
}

// Ортографическая проекция двух реальных плоскостей с углом 5°.
// Второй рисунок показывает тот же угол сбоку без перспективы.
function planes(s){const center=[330,411],a=30*Math.PI/180,e=20*Math.PI/180,inc=5*Math.PI/180;const project=(X,Y,Z)=>[center[0]+X*Math.cos(a)+Y*Math.sin(a),center[1]-X*Math.sin(a)*Math.sin(e)+Y*Math.cos(a)*Math.sin(e)-Z*Math.cos(e)];const moonPoint=(X,Y)=>project(X,Y*Math.cos(inc),Y*Math.sin(inc));const corners=[[-275,-160],[275,-160],[275,160],[-275,160]];poly(s,corners.map(([x,y])=>project(x,y,0)),C.plane);poly(s,corners.map(([x,y])=>moonPoint(x,y)),'#293737');
  const N1=project(-235,0,0),N2=project(235,0,0);dashed(s,project(-300,0,0),project(300,0,0),'#E5C47D',1.4,8,6);
  route(s,Array.from({length:121},(_,i)=>{const t=i*2*Math.PI/120;return moonPoint(235*Math.cos(t),235*Math.sin(t));}),C.orbit,2.4);
  disc(s,...center,29,C.earth);disc(s,...N1,5.5,C.sun);disc(s,...N2,5.5,C.sun);
  const lunarPosition=moonPoint(0,-235);disc(s,...lunarPosition,11,C.moon,C.orbit,1);txt(s,'Луна',254,324,95,26,18,C.orbit);line(s,256,347,lunarPosition[0]+11,lunarPosition[1]-1,C.orbit,1);
  txt(s,'Орбита Луны',58,277,260,30,21,C.orbit,true);route(s,[[202,309],moonPoint(-155,-175)],C.orbit,1);
  txt(s,'Плоскость земной орбиты',50,488,390,32,20,C.muted);route(s,[[421,507],project(210,146,0)],C.muted,1);
  txt(s,'Земля',342,438,130,28,19,C.ink);
  txt(s,'Узлы — точки пересечения орбиты Луны\nс плоскостью земной орбиты.',58,523,560,52,19,C.sun);
  // Сечение сбоку, угол ровно пять градусов.
  const O=[74,637],L=460;line(s,O[0],O[1],O[0]+L,O[1], '#577B99',1.5);line(s,O[0],O[1],O[0]+L*Math.cos(inc),O[1]-L*Math.sin(inc),C.orbit,1.8);arc(s,O,175,-inc,0,C.sun,2);txt(s,'≈ 5°',280,578,130,36,28,C.sun,false,'Georgia');txt(s,'Вид сбоку',58,592,180,22,16,C.muted);line(s,304,614,249,629,C.sun,1);checks.push({name:'angle between orbital planes',angleDegrees:Math.acos(Math.cos(inc))*180/Math.PI,pass:Math.abs(Math.acos(Math.cos(inc))*180/Math.PI-5)<1e-10});
}
function third(){const s=base(3,'Почему затмение бывает не каждый месяц?','Лунная орбита наклонена к плоскости земной орбиты примерно на 5°.','Размеры тел и расстояния условны. В двух схемах справа сохранён одинаковый масштаб.');planes(s);line(s,654,281,654,632,C.line);
  txt(s,'Обычно в новолуние',706,278,520,32,25,C.ink,true);
  shadowScene(s,{S:[748,390],R:25,M:[963,344],r:14,E:[1177,390],Re:25,name:'slide 3 miss',hit:false});
  txt(s,'Тень проходит выше или ниже Земли.',706,430,520,58,21,C.muted);
  txt(s,'Новолуние около узла',706,499,520,32,25,C.ink,true);
  shadowScene(s,{S:[748,574],R:25,M:[963,574],r:14,E:[1177,574],Re:25,name:'slide 3 hit',hit:true});
  txt(s,'Тень может попасть на Землю.',706,616,520,30,21,C.sun);
  return s;
}

await fs.mkdir(path.join(root,'.tmp'),{recursive:true});
if(mode==='compare'){first();first(true);}else{first();second();third();}
const out=path.join(root,mode==='compare'?'.tmp/Исправленные опорные':'Слайды');await fs.mkdir(out,{recursive:true});
for(let i=0;i<P.slides.items.length;i++){const b=await P.export({slide:P.slides.items[i],format:'png',scale:1.5});await fs.writeFile(path.join(out,`Слайд ${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await b.arrayBuffer()));}
const candidate=path.join(root,'.tmp',mode==='compare'?'Сравнение.pptx':'Кандидат.pptx');await(await PresentationFile.exportPptx(P)).save(candidate);
await fs.writeFile(path.join(root,'.tmp','Проверка геометрии.json'),JSON.stringify(checks,null,2));
if(mode==='final'){
  if(!SKILL) throw Error('Set PRESENTATION_TECHNICAL_SKILL to the available presentation tool directory, or use deck mode.');
  const {finalizePresentation}=await import(pathToFileURL(path.join(SKILL,'container_tools/artifact_tool_utils.mjs')).href);
  const final=path.join(root,'Презентация',process.argv[3]||'Солнечное затмение.pptx');await fs.mkdir(path.dirname(final),{recursive:true});
  const result=await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:final,pythonExecutable:process.env.PRESENTATION_PYTHON || 'python3',integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],explicitTotalSlideCount:3,requiredNativeTableOwnerSlides:[],fontPolicy:{basis:'design',families:['Arial','Georgia']},verifyArtifactToolImport:true,receiptPath:path.join(root,'.tmp','validation.json')});
  console.log(JSON.stringify(result));
}
console.log(JSON.stringify({slides:P.slides.items.length,images:out,geometryChecks:checks.map(x=>({name:x.name,pass:x.pass,apex:x.apex}))}));
