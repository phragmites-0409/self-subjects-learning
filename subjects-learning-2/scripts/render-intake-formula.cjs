// A bounded, local renderer shared by formula verification and PDF printing.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const repository=path.resolve(__dirname,'../..');
const runtimeConfig=JSON.parse(fs.readFileSync(path.join(repository,'runtime.json'),'utf8'));
const runtime=path.resolve(process.env.SUBJECTS_LEARNING_RUNTIME||path.join(repository,runtimeConfig.root));
const deps=path.join(runtime,'document-renderer/node_modules');
const katex=require(deps+'/katex');require(deps+'/katex/dist/contrib/mhchem.js');
const {mathjax}=require(deps+'/mathjax-full/js/mathjax.js');
const {TeX}=require(deps+'/mathjax-full/js/input/tex.js');
const {SVG}=require(deps+'/mathjax-full/js/output/svg.js');
const {liteAdaptor}=require(deps+'/mathjax-full/js/adaptors/liteAdaptor.js');
const {RegisterHTMLHandler}=require(deps+'/mathjax-full/js/handlers/html.js');
require(deps+'/mathjax-full/js/input/tex/ams/AmsConfiguration.js');
require(deps+'/mathjax-full/js/input/tex/mhchem/MhchemConfiguration.js');
require(deps+'/mathjax-full/js/input/tex/textmacros/TextMacrosConfiguration.js');
const {Resvg}=require(deps+'/@resvg/resvg-js');
let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',chunk=>{input+=chunk;if(input.length>16000)throw Error('Oversized renderer input')});
process.stdin.on('end',()=>{try{
 const {formula}=JSON.parse(input);
 if(typeof formula!=='string'||formula.length>3500||/\\(?:href|url|includegraphics|html|require|def|gdef|newcommand|renewcommand|input|write|catcode)\b/.test(formula))throw Error('Unsupported formula commands');
 katex.renderToString(formula,{throwOnError:true,trust:false,strict:'ignore',displayMode:false,maxExpand:1000});
 const adaptor=liteAdaptor();RegisterHTMLHandler(adaptor);
 const tex=new TeX({packages:['base','ams','mhchem','textmacros'],maxBuffer:8000,maxMacros:1000});
 const document=mathjax.document('',{InputJax:tex,OutputJax:new SVG({fontCache:'none'})});
 const container=document.convert(formula,{display:false,em:16,ex:8,containerWidth:1400});
 if(adaptor.tags(container,'mjx-merror').length || adaptor.outerHTML(container).includes('data-mjx-error'))throw Error('Formula did not render');
 const svg=adaptor.tags(container,'svg')[0];if(!svg)throw Error('No formula SVG');
 const toPx=value=>value.endsWith('ex')?parseFloat(value)*8:value.endsWith('em')?parseFloat(value)*16:parseFloat(value);
 const width=toPx(adaptor.getAttribute(svg,'width')),height=toPx(adaptor.getAttribute(svg,'height'));
 if(!(width>0&&height>0&&width<8000&&height<2000))throw Error('Invalid formula size');
 adaptor.setAttribute(svg,'width',String(width));adaptor.setAttribute(svg,'height',String(height));
 const markup=adaptor.outerHTML(svg),digest=crypto.createHash('sha256').update('intake-renderer-v1\0'+formula).digest('hex');
 const directory=path.join(runtime,'cache/formula-render');fs.mkdirSync(directory,{recursive:true});
 const file=path.join(directory,digest+'.png');let result;
 if(!fs.existsSync(file)){result=new Resvg(markup,{fitTo:{mode:'zoom',value:220/96},font:{loadSystemFonts:true}}).render();fs.writeFileSync(file,result.asPng());}
 console.log(JSON.stringify({path:file,width_css:width,height_css:height,scale:220/96,valid:true}));
 }catch(error){console.log(JSON.stringify({valid:false,error:error.message}));process.exitCode=1;}});
