"""Deferred responses must never write one project's metadata into another."""
from pathlib import Path
import subprocess


def test_project_switch_ignores_late_reads_and_save_replies():
    script = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map();
function node(){return {value:'',textContent:'',hidden:false,disabled:false,elements:[],
  replaceChildren(){},append(){},scrollIntoView(){}};}
function get(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}
get('metadata-form').elements=[get('description'),get('notes'),node()];
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const reads=new Map(),writes=[],saved={a:{revision:0,description:'A description',context:{notes:'A notes'}},
 b:{revision:0,description:'B description',context:{notes:'B notes'}}};
let delayedWrite=null;
const response=value=>({ok:true,headers:{get:()=> 'application/json'},json:async()=>value});
const context=vm.createContext({document:{getElementById:get,createElement:node},setInterval(){},
 sessionStorage:{getItem(){return null;},setItem(){},removeItem(){}},
 fetch:async(path,options)=>{
  if(path==='/api/session')return {ok:false,status:401,json:async()=>({})};
  const pid=path.split('/')[3];
  if(path.endsWith('/thread')){
   if(options.method==='PUT'){
    const body=JSON.parse(options.body);writes.push({pid,body});
    assert.equal(body.revision,saved[pid].revision);
    saved[pid]={revision:body.revision+1,description:body.description,context:{notes:body.notes}};
    if(delayedWrite){const hold=delayedWrite;delayedWrite=null;await hold.promise;}
    return response(saved[pid]);
   }
   const hold=reads.get(pid);if(hold){reads.delete(pid);return response(await hold.promise);}
   return response(saved[pid]);
  }
  if(path.endsWith('/status'))return response({state:'metadata_only',required_bytes:0,stored_bytes:0,
   conflict_count:0,missing_files:[],issues:[],offline_enabled:false});
  if(path.endsWith('/metadata/conflicts'))return response({conflicts:[]});
  if(path.endsWith('/files'))return response({files:[]});
  if(path.endsWith('/uploads'))return response({uploads:[]});
  if(path.endsWith('/whiteboard'))return response({entries:[]});
  throw Error('Unexpected request '+path);
 }});
vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const select=pid=>vm.runInContext(`select({id:'${pid}',title:'${pid}'})`,context);
const tick=()=>new Promise(setImmediate);
const submit=()=>get('metadata-form').onsubmit({preventDefault(){}});
(async()=>{
 const first=deferred();reads.set('a',first);const oldA=select('a');
 const second=deferred();reads.set('b',second);const pendingB=select('b');
 assert.equal(get('metadata-form').elements[2].disabled,true);
 submit();await tick();assert.equal(writes.length,0,'loading metadata must not be submitted');
 second.resolve(saved.b);await pendingB;
 first.resolve(saved.a);await oldA;
 assert.equal(get('description').value,'B description');assert.equal(get('notes').value,'B notes');
 submit();await tick();assert.equal(writes[0].pid,'b');assert.equal(writes[0].body.notes,'B notes');
 // A late save reply for B must not replace A's active revision or form state.
 delayedWrite=deferred();const writing=delayedWrite;submit();await tick();
 await select('a');writing.resolve();await tick();
 submit();await tick();assert.equal(writes.at(-1).pid,'a');assert.equal(writes.at(-1).body.notes,'A notes');
 assert.equal(writes.at(-1).body.revision,0);
 // Returning to the same project still invalidates its older read generation.
 const oldest=deferred();reads.set('a',oldest);const oldAgain=select('a');
 await select('b');await select('a');
 oldest.resolve({revision:0,description:'obsolete A',context:{notes:'obsolete A'}});await oldAgain;
 assert.equal(get('description').value,'A description');assert.equal(get('notes').value,'A notes');
 console.log('deferred reads, loading submission, late save and repeated selection protected');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
    source = Path(__file__).resolve().parents[1]/'src/threaddesk/server_sync/web/app.js'
    result = subprocess.run(['node','-e',script,str(source)],capture_output=True,text=True,timeout=15)
    assert result.returncode == 0, result.stderr
    assert 'repeated selection protected' in result.stdout
