(function(){
'use strict';

const $=id=>document.getElementById(id);
let busy=false,firstLoad=true,stream=null,fallback=null,lastUpdate=0;
// One in-memory copy of each guild; no localStorage or stale persistent state.
const guildCache=new Map();
let metaCache={};
let uptimeBase=0,uptimeReceived=0;
function fmtUptime(seconds){
  const days=Math.floor(seconds/86400),hours=Math.floor(seconds%86400/3600);
  const minutes=Math.floor(seconds%3600/60),secs=seconds%60;
  const parts=[];
  if(days)parts.push(days+'d');
  if(hours||days)parts.push(hours+'h');
  if(minutes||hours||days)parts.push(minutes+'m');
  parts.push(secs+'s');
  return parts.join(' ');
}
function tickUptime(){
  if(!uptimeReceived)return;
  const seconds=uptimeBase+Math.floor((Date.now()-uptimeReceived)/1000);
  $('h-uptime').textContent=fmtUptime(Math.max(0,seconds));
}
setInterval(tickUptime,1000);
function markUpdated(){
  lastUpdate=Date.now();firstLoad=false;
  $('h-refresh').textContent='Live · '+new Date().toLocaleTimeString();
}
function renderMeta(m){
  metaCache={...metaCache,...m};
  const d=metaCache;
  $('h-guilds').textContent=d.guild_count??guildCache.size;
  $('sec-lbl').textContent='Servers ('+(d.guild_count??guildCache.size)+')';
  const dot=$('h-ll-dot'),lbl=$('h-ll-lbl'),ap=$('h-ll-addr-pill');
  if(d.lavalink_connected){
    dot.className='dot g pulse';lbl.textContent='Connected';
    $('h-ll-addr').textContent=d.lavalink_host+':'+d.lavalink_port;
    ap.style.display='';
  }else{
    dot.className='dot r';lbl.textContent='Disconnected';ap.style.display='none';
  }
}
function renderGuild(id){
  const data=guildCache.get(id),grid=$('grid');
  const old=Array.from(grid.children).find(el=>el.dataset&&el.dataset.guildId===id);
  if(!data){if(old)old.remove();return;}
  const replacement=card(data);
  replacement.dataset.guildId=id;
  if(old)old.replaceWith(replacement);
  else grid.appendChild(replacement);
}
function renderEmpty(){
  if(!guildCache.size){
    $('grid').innerHTML='<div class="empty"><div class="e-ico">🎵</div><p class="e-txt">No servers yet.</p></div>';
  }else{
    const empty=$('grid').querySelector('.empty,.loading');
    if(empty)empty.remove();
  }
}
function applySnapshot(d){
  uptimeBase=d.uptime_seconds;
  uptimeReceived=Date.now();tickUptime();
  metaCache={};
  guildCache.clear();
  for(const g of d.guilds)guildCache.set(String(g.id),g);
  $('grid').replaceChildren();
  for(const id of guildCache.keys())renderGuild(id);
  renderEmpty();
  renderMeta(d);
  markUpdated();
}
function applyDelta(d){
  // A delta changes only specified fields; all other cached fields are retained.
  for(const id of d.removed||[])guildCache.delete(String(id));
  for(const [id,changes] of Object.entries(d.guilds||{})){
    guildCache.set(id,{...(guildCache.get(id)||{id}),...changes});
  }
  for(const id of d.removed||[])renderGuild(String(id));
  for(const id of Object.keys(d.guilds||{}))renderGuild(id);
  renderEmpty();
  if(d.meta)renderMeta(d.meta);
  else if((d.removed||[]).length||Object.keys(d.guilds||{}).length){
    renderMeta({guild_count:guildCache.size});
  }
  markUpdated();
}
function startFallback(){
  if(fallback)return;
  $('h-refresh').textContent='Reconnecting…';
  refresh();fallback=setInterval(refresh,15000);
}
function stopFallback(){if(fallback){clearInterval(fallback);fallback=null;}}
function startStream(){
  if(!window.EventSource){startFallback();return;}
  stream=new EventSource('/api/events');
  stream.addEventListener('snapshot',e=>{
    try{applySnapshot(JSON.parse(e.data));stopFallback();}
    catch(err){console.error('Invalid dashboard snapshot',err);}
  });
  stream.addEventListener('delta',e=>{
    try{applyDelta(JSON.parse(e.data));stopFallback();}
    catch(err){console.error('Invalid dashboard delta',err);refresh();}
  });
  stream.addEventListener('unauthorized',()=>{stream.close();location.href='/login';});
  stream.onopen=()=>stopFallback();
  stream.onerror=()=>startFallback();
}

// Full snapshots are also used as a safe fallback when SSE is unavailable.
async function refresh(){
  if(busy)return;busy=true;
  try{
    const r=await fetch('/api/stats',{cache:'no-store'});
    if(r.status===401){location.href='/login';return;}
    if(!r.ok)throw new Error('HTTP '+r.status);
    applySnapshot(await r.json());
  }catch(e){
    if(firstLoad){guildCache.clear();$('grid').replaceChildren();renderEmpty();}
    notify('⚠️ '+e.message,'error');
  }finally{busy=false;}
}

// ── Card ──────────────────────────────────────────────────────────────────────
function card(g){
  const el=document.createElement('div');
  el.className='card'+(g.is_paused?' paused':g.is_playing?' playing':'');

  const iconHtml=g.icon_url
    ?`<img class="c-icon" src="${safeUrl(g.icon_url)}" alt="" loading="lazy">`
    :`<div class="c-icon-ph">🎵</div>`;

  const sBadge=g.is_paused
    ?'<span class="sbadge sb-pause">⏸ Paused</span>'
    :g.is_playing
      ?'<span class="sbadge sb-play">▶ Playing</span>'
      :'<span class="sbadge sb-idle">⏸ Idle</span>';

  let npHtml;
  if(g.now_playing){
    const href=g.now_playing_url?`href="${safeUrl(g.now_playing_url)}" target="_blank" rel="noopener"`:'';
    npHtml=`<a class="np-track" ${href}>${x(g.now_playing)}</a>
            ${g.is_paused ? '' : '<div class="eq"><span></span><span></span><span></span><span></span><span></span></div>'}`;
  }else{
    npHtml='<span class="np-none">Nothing playing</span>';
  }

  const voiceTxt=g.voice_channel
    ?`<b>${g.voice_members}</b> listener${g.voice_members!==1?'s':''} · <b>#${x(g.voice_channel)}</b>`
    :'Not in voice';

  let badges='';
  if(g.stay_247)badges+='<span class="badge b247">24/7</span>';
  if(g.has_dj_role)badges+='<span class="badge bdj">🎧 DJ Role</span>';
  if(g.setup_channel)badges+=`<span class="badge bch">#${x(g.setup_channel)}</span>`;
  if(!badges)badges='<span class="no-b">No special modes active</span>';

  const lastTxt=g.last_played_at?fmtRel(g.last_played_at):'never';
  const ltHtml=g.last_track
    ?`<div class="lt">
        <div class="lt-lbl">Last played · ${lastTxt}</div>
        <div class="lt-name">${x(g.last_track)}</div>
      </div>`
    :`<div class="lt"></div>`;

  el.innerHTML=`
    <div class="c-head">
      ${iconHtml}
      <div class="c-meta">
        <div class="c-name">${x(g.name)}</div>
        <div class="c-members">👥 ${fmt(g.member_count)} members</div>
      </div>
      ${sBadge}
    </div>

    <div class="np">
      <div class="np-lbl">Now Playing</div>
      ${npHtml}
    </div>

    <div class="c-stats">
      <div class="si"><span class="si-ico">🎤</span><span class="si-txt">${voiceTxt}</span></div>
      <div class="si"><span class="si-ico">📋</span><span class="si-txt"><b>${g.queue_length}</b> in queue</span></div>
      <div class="si"><span class="si-ico">⏱️</span><span class="si-txt"><b>${g.total_playtime_formatted}</b> total play</span></div>
      <div class="si"><span class="si-ico">🎵</span><span class="si-txt"><b>${fmt(g.total_tracks_played)}</b> tracks played</span></div>
      <div class="si"><span class="si-ico">📅</span><span class="si-txt">Joined <b>${g.joined_at?fmtDate(g.joined_at):'unknown'}</b></span></div>
      <div class="si"><span class="si-ico">🕐</span><span class="si-txt">Last active <b>${lastTxt}</b></span></div>
    </div>

    <div class="c-badges">${badges}</div>

    <div class="c-foot">
      ${ltHtml}
      <button class="btn-leave" data-gid="${attr(g.id)}" data-gname="${attr(g.name)}">
        🚪 Leave
      </button>
    </div>`;
  return el;
}

// ── Actions ───────────────────────────────────────────────────────────────────
async function leaveServer(id,name,btn){
  if(!confirm('Leave "'+name+'"?\\n\\nThe bot will disconnect from voice and the queue will be cleared.'))return;
  btn.disabled=true;btn.textContent='⌛ Leaving…';
  try{
    const r=await fetch('/api/leave/'+encodeURIComponent(id),{method:'POST',headers:{'X-CSRF-Token':document.querySelector('meta[name=csrf-token]').content}});
    const d=await r.json();
    if(d.success){notify('✅ Left '+name);setTimeout(refresh,1200);}
    else{notify('❌ '+(d.error||'Unknown error'),'error');btn.disabled=false;btn.textContent='🚪 Leave';}
  }catch(e){
    notify('❌ '+e.message,'error');btn.disabled=false;btn.textContent='🚪 Leave';
  }
};

// ── Utils ─────────────────────────────────────────────────────────────────────
function x(s){const d=document.createElement('div');d.appendChild(document.createTextNode(String(s)));return d.innerHTML;}
function attr(s){return x(s).replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function safeUrl(value){
  try{const u=new URL(String(value),location.href);
      return ['https:','http:'].includes(u.protocol)?attr(u.href):'';}
  catch{return '';}
}
function fmt(n){return(n??0).toLocaleString();}
function fmtDate(iso){
  try{return new Date(iso).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});}
  catch{return '–';}
}
function fmtRel(iso){
  try{
    const diff=(Date.now()-new Date(iso))/1000;
    if(diff<60)return 'just now';
    if(diff<3600)return Math.floor(diff/60)+'m ago';
    if(diff<86400)return Math.floor(diff/3600)+'h ago';
    return Math.floor(diff/86400)+'d ago';
  }catch{return '–';}
}
function notify(msg,type='success'){
  const n=$('notif');n.textContent=msg;n.className='show '+type;
  clearTimeout(n._t);n._t=setTimeout(()=>{n.className='';},3500);
}

// ── Init ──────────────────────────────────────────────────────────────────────
// Delegated click handler — avoids all inline-onclick escaping issues
document.addEventListener('click',function(e){
  const btn=e.target.closest('.btn-leave');
  if(!btn||btn.disabled)return;
  leaveServer(btn.dataset.gid,btn.dataset.gname,btn);
});
startStream();
window.addEventListener('beforeunload',()=>{if(stream)stream.close();stopFallback();});
})();
