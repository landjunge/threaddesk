'use strict';
const $ = id => document.getElementById(id);
let csrf = '', selected = null, thread = null, editing = null;
let selectionEpoch = 0;
const states = {metadata_only:'Nur Struktur und Metadaten',pending:'Abgleich ausstehend',blocked:'Dateien oder Zuordnungen fehlen',conflict:'Versionskonflikt – alle Fassungen erhalten',ready:'Offline bereit · gemeldeter Bestand geprüft'};
function message(value) {$('message').textContent = value || '';}
async function api(path, method='GET', value) {
  const headers = {'X-ThreadDesk-CSRF':csrf};
  if (value !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {method, headers, body:value === undefined ? undefined : JSON.stringify(value), credentials:'same-origin'});
  if (!response.ok) {
    let detail; try {detail = await response.json();} catch {detail = {};}
    throw Error(detail.detail || detail.error || `HTTP ${response.status}`);
  }
  return response.headers.get('content-type')?.includes('application/json') ? response.json() : response;
}
function endpoint(suffix='') {if (!selected) throw Error('Projekt auswählen'); return '/api/projects/' + selected.id + suffix;}
function el(tag, text) {const node = document.createElement(tag); if(text !== undefined) node.textContent=text; return node;}
function button(text, fn) {const node=el('button',text); node.type='button'; node.onclick=()=>run(fn); return node;}
async function run(fn) {message(''); try {await fn();} catch(error) {message(error.message);}}
async function enter() {$('login').hidden=true; $('desk').hidden=false; $('logout').hidden=false; await listProjects();}
async function listProjects() {
  const value=await api('/api/projects'); $('projects').replaceChildren();
  for(const project of value.projects) $('projects').append(button(project.title,()=>select(project)));
}
async function select(project) {
  const epoch=++selectionEpoch,pid=project.id;
  selected=project; thread=null; editing=null; $('editor').hidden=true;
  for(const control of $('metadata-form').elements) control.disabled=true;
  $('description').value='';$('notes').value='';$('entry-content').value='';
  $('file-path').value='';$('file-upload').value='';$('offline').disabled=true;
  $('files').replaceChildren();$('entries').replaceChildren();$('metadata-conflict-list').replaceChildren();
  $('project').hidden=false; $('project-title').textContent=project.title; $('project-id').textContent=project.id;
  const value=await api('/api/projects/'+pid+'/thread');
  if(selectionEpoch!==epoch||selected?.id!==pid)return;
  thread=value; $('description').value=thread.description; $('notes').value=thread.context.notes;
  for(const control of $('metadata-form').elements) control.disabled=false;
  await refresh();
}
async function status() {
  if(!selected) return;
  const pid=selected.id,epoch=selectionEpoch, value=await api(endpoint('/status'));
  if(selected?.id !== pid||selectionEpoch!==epoch) return;
  $('offline').checked=value.offline_enabled;
  $('offline').disabled=false;
  $('sync').replaceChildren(el('strong',states[value.state] || value.state));
  $('sync').append(el('p',`Noch benötigt: ${(value.required_bytes/1048576).toFixed(2)} MiB · Gespeichert: ${(value.stored_bytes/1048576).toFixed(2)} MiB · Konflikte: ${value.conflict_count+(value.metadata_conflict_count||0)}`));
  if(value.last_sync_at)$('sync').append(el('p','Letzter gemeldeter Abgleich: '+new Date(value.last_sync_at).toLocaleString()));
  if(value.missing_files.length) $('sync').append(el('p','Fehlend: '+value.missing_files.join(', ')));
  for(const issue of value.issues) $('sync').append(el('p',issue));
}
async function refresh() {const epoch=selectionEpoch;await status();if(epoch!==selectionEpoch)return;await showFiles();if(epoch!==selectionEpoch)return;await showEntries();if(epoch!==selectionEpoch)return;await showMetadataConflicts();}
async function showMetadataConflicts() {
  const pid=selected.id,epoch=selectionEpoch,prefix='/api/projects/'+pid;
  const {conflicts}=await api(prefix+'/metadata/conflicts');if(selected?.id!==pid||selectionEpoch!==epoch)return;
  $('metadata-conflicts').hidden=!conflicts.length;$('metadata-conflict-list').replaceChildren();
  if(!conflicts.length)return;
  const {document:doc}=await api(prefix+'/metadata');if(selected?.id!==pid||selectionEpoch!==epoch)return;
  for(const conflict of conflicts) {
    const row=el('div');row.className='file';row.append(el('strong',conflict.path));
    const parts=conflict.path.split('/');let current=doc;
    for(const part of parts)current=current && Object.hasOwn(current,part)?current[part]:{'$missing':true};
    for(const [label,value] of [['Eingehende Fassung verwenden',conflict.incoming],['Gespeicherte Server-Fassung verwenden',conflict.current]]) {
      const detail=el('details');detail.append(el('summary',label),el('pre',JSON.stringify(value,null,2)));row.append(detail);
      if(value && value.$missing === true)continue;
      row.append(button(label,async()=>{
        await api(prefix+'/metadata/resolve','POST',{conflict_id:conflict.id,expected_current:current,chosen_value:value,operation_id:crypto.randomUUID().replaceAll('-','')});
        if(selected?.id===pid)await select(selected);message('Metadatenkonflikt aufgelöst. Vorherige Fassungen bleiben in Momentaufnahmen und Konfliktjournal erhalten.');
      }));
    }
    $('metadata-conflict-list').append(row);
  }
}
async function showFiles() {
  const pid=selected.id,epoch=selectionEpoch, prefix='/api/projects/'+pid;
  const {files}=await api(prefix+'/files'); if(selected?.id!==pid||selectionEpoch!==epoch)return; $('files').replaceChildren();
  for(const file of files) {
    const row=el('div'); row.className='file'; row.append(el('strong',file.path));
    for(const head of file.heads) {
      const version=el('div'); version.append(el('p',`${head.revision.slice(0,12)} · ${head.size} Bytes · SHA256 ${head.sha256.slice(0,16)}…`));
      version.append(button('Herunterladen',async()=>{
        const response=await api(prefix+'/revisions/'+head.revision); const url=URL.createObjectURL(await response.blob());
        const link=el('a'); link.href=url; link.download=file.path.split('/').pop(); link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
      }));
      version.append(button('Text bearbeiten',async()=>{
        if(head.size>1048576) throw Error('Texteditor unterstützt Dateien bis 1 MiB.');
        const response=await api(prefix+'/revisions/'+head.revision);
        const bytes=await response.arrayBuffer(); let content;
        try {content=new TextDecoder('utf-8',{fatal:true}).decode(bytes);} catch {throw Error('Keine UTF-8-Textdatei.');}
        if(content.includes('\0')) throw Error('Binärdatei kann nicht als Text bearbeitet werden.');
        if(selected?.id!==pid)throw Error('Projekt wurde gewechselt.');
        editing={path:file.path,base:head.revision,project:pid}; $('edit-title').textContent=file.path;
        $('edit-content').value=content; $('editor').hidden=false; $('editor').scrollIntoView({behavior:'smooth'});
      }));
      if(file.heads.length>1) version.append(button('Diese Fassung verwenden',async()=>{
        await api(prefix+'/resolve','POST',{path:file.path,expected_heads:file.heads.map(h=>h.revision),chosen_revision:head.revision});
        await declareBrowser(pid); if(selected?.id===pid)await refresh(); message('Konflikt aufgelöst. Frühere Versionen bleiben gespeichert.');
      }));
      row.append(version);
    }
    row.append(button('Frühere Versionen',async()=>{
      const {versions}=await api(prefix+'/history?path='+encodeURIComponent(file.path));
      const history=el('div');
      for(const version of versions) {
        const item=el('p',`${version.revision.slice(0,12)} · ${version.size} Bytes${version.is_head?' · aktuelle Fassung':''} `);
        item.append(button('Fassung laden',async()=>{
          const response=await api(prefix+'/revisions/'+version.revision);const url=URL.createObjectURL(await response.blob());
          const link=el('a');link.href=url;link.download=file.path.split('/').pop()+'.'+version.revision.slice(0,8);link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
        }));history.append(item);
      }
      row.append(history);
    }));
    $('files').append(row);
  }
  const {uploads}=await api(prefix+'/uploads');if(selected?.id!==pid||selectionEpoch!==epoch)return;
  for(const transfer of uploads) {
    const row=el('div');row.className='file';row.append(el('p',`Unfertige Übertragung: ${transfer.path} · ${transfer.next_offset} / ${transfer.size} Bytes`));
    row.append(button('Unfertige Übertragung abbrechen',async()=>{
      await api(prefix+'/uploads/'+transfer.transfer_id+'/abort','POST');if(selected?.id===pid)await refresh();
      message('Reservierung freigegeben. Fertige Fassungen und Originaldateien bleiben erhalten.');
    }));$('files').append(row);
  }
}
async function declareBrowser(pid=selected.id) {
  // Reserved synthetic server view: heads are derived atomically by the server.
  return api('/api/projects/'+pid+'/manifest','POST',{device_id:'browser-server',issues:[],files:[]});
}
async function upload(path,bytes,base,pid=selected.id) {
  if(bytes.byteLength>67108864) throw Error('Maximal 64 MiB pro Datei.');
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  // Persist identity before transfer; a repeated click resumes the same manifest.
  const key=`td-transfer:${pid}:${path}:${hash}:${base || ''}`;
  let transfer=sessionStorage.getItem(key); if(!transfer) {transfer=crypto.randomUUID().replaceAll('-','');sessionStorage.setItem(key,transfer);}
  let uri,progress;
  for(let attempt=0;attempt<2;attempt++) {
    uri='/api/projects/'+pid+'/uploads/'+transfer;
    progress=await api(uri,'POST',{path,size:bytes.byteLength,sha256:hash,base_revision:base});
    if(progress.state!=='aborted') break;
    if(attempt===1) throw Error('Übertragung wurde erneut abgebrochen. Bitte erneut versuchen.');
    transfer=crypto.randomUUID().replaceAll('-','');sessionStorage.setItem(key,transfer);
  }
  if(!['receiving','committed'].includes(progress.state)||!Number.isInteger(progress.next_offset)||progress.next_offset<0||progress.next_offset>bytes.byteLength) throw Error('Ungültiger Übertragungsstatus.');
  for(let offset=progress.next_offset;offset<bytes.byteLength;) {
    const chunk=new Uint8Array(bytes.slice(offset,offset+262144)); let binary='';
    for(let i=0;i<chunk.length;i+=8192) binary+=String.fromCharCode(...chunk.subarray(i,i+8192));
    progress=await api(uri,'PATCH',{offset,data_base64:btoa(binary)});
    if(progress.next_offset!==offset+chunk.length) throw Error('Ungültige Empfangsbestätigung.');
    offset=progress.next_offset;
    message(`Übertragen: ${offset} / ${bytes.byteLength} Bytes`);
  }
  await api(uri+'/commit','POST');sessionStorage.removeItem(key);await declareBrowser(pid);if(selected?.id===pid)await refresh();message('Datei geprüft und versioniert gespeichert.');
}
async function showEntries() {
  const pid=selected.id,epoch=selectionEpoch;
  const {entries}=await api('/api/projects/'+pid+'/whiteboard');if(selected?.id!==pid||selectionEpoch!==epoch)return;$('entries').replaceChildren();
  for(const entry of entries.slice().reverse()) {const row=el('div');row.className='entry';row.append(el('strong',`${entry.entry_type} · ${entry.actor}`),el('p',entry.content));$('entries').append(row);}
}
$('login-form').onsubmit=e=>{e.preventDefault();run(async()=>{const value=await api('/auth/login','POST',{token:$('token').value});csrf=value.csrf;$('token').value='';await enter();});};
$('logout').onclick=()=>run(async()=>{await api('/api/logout','POST');location.reload();});
$('create-form').onsubmit=e=>{e.preventDefault();run(async()=>{const value=await api('/api/projects','POST',{title:$('title').value});$('title').value='';await listProjects();await select(value);});};
$('offline').onchange=()=>run(async()=>{await api(endpoint('/offline'),'PUT',{enabled:$('offline').checked});await status();});
$('refresh').onclick=()=>run(refresh);
$('metadata-form').onsubmit=e=>{e.preventDefault();run(async()=>{if(!thread)throw Error('Projekt wird geladen.');const pid=selected.id,epoch=selectionEpoch;const value=await api('/api/projects/'+pid+'/thread','PUT',{revision:thread.revision,description:$('description').value,notes:$('notes').value});if(selected?.id!==pid||selectionEpoch!==epoch)return;thread=value;message('Gespeichert.');});};
$('entry-form').onsubmit=e=>{e.preventDefault();run(async()=>{const pid=selected.id,epoch=selectionEpoch,content=$('entry-content').value;const key='td-entry:'+pid;let pending=JSON.parse(sessionStorage.getItem(key)||'null');if(!pending||pending.content!==content) {pending={content,external_key:crypto.randomUUID()};sessionStorage.setItem(key,JSON.stringify(pending));}await api('/api/projects/'+pid+'/whiteboard','POST',{...pending,entry_type:$('entry-type').value});sessionStorage.removeItem(key);if(selected?.id!==pid||selectionEpoch!==epoch)return;$('entry-content').value='';await showEntries();});};
$('upload-form').onsubmit=e=>{e.preventDefault();run(async()=>{const pid=selected.id,path=$('file-path').value,input=$('file-upload').files[0];const {files}=await api('/api/projects/'+pid+'/files');const file=files.find(f=>f.path===path);if(file?.heads.length>1)throw Error('Zuerst den Versionskonflikt auflösen.');if(input.size>67108864)throw Error('Maximal 64 MiB pro Datei.');const bytes=await input.arrayBuffer();await upload(path,bytes,file?.heads[0]?.revision||null,pid);});};
$('editor').onsubmit=e=>{e.preventDefault();run(async()=>{const edit=editing;if(edit.project!==selected.id)throw Error('Projekt wurde gewechselt.');await upload(edit.path,new TextEncoder().encode($('edit-content').value).buffer,edit.base,edit.project);if(editing===edit){$('editor').hidden=true;editing=null;}});};
$('edit-close').onclick=()=>{$('editor').hidden=true;editing=null;};
run(async()=>{try {const value=await api('/api/session');csrf=value.csrf;await enter();} catch {}});
setInterval(()=>{if(selected)run(status);},10000);
