function setupSearch() {
  const box = document.getElementById('lead-search');
  if(!box) return;
  let timeout = null;
  box.addEventListener('input', function(e){
    clearTimeout(timeout);
    const q = e.target.value.trim();
    timeout = setTimeout(()=>{
      fetch('/api/leads?q=' + encodeURIComponent(q))
        .then(r => r.json())
        .then(data => {
          // simple client-side redraw of leads table
          const tbody = document.getElementById('leads-tbody');
          if(!tbody) return;
          tbody.innerHTML = '';
          data.items.forEach(lead => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td>${lead.id}</td><td>${lead.name||''}</td><td>${lead.email||''}</td><td>${lead.phone||''}</td><td>${lead.verified}</td><td>${lead.enriched_company||''}</td><td>${lead.source||''}</td>`;
            tbody.appendChild(tr);
          });
        }).catch(()=>{});
    }, 300);
  });
}
window.addEventListener('load', setupSearch);

function setupCampaignForm(){
  const form = document.querySelector('form[action="/campaigns/create"]');
  if(!form) return;
  form.addEventListener('submit', function(e){
    e.preventDefault();
    const formData = new FormData(form);
    const progress = document.getElementById('campaign-progress');
    progress.textContent = 'Creating campaign...';
    fetch(form.action, {method: 'POST', body: formData, headers: {'X-Requested-With':'XMLHttpRequest'}}).then(r=>r.json()).then(data=>{
      if(data && data.campaign_id){
        progress.textContent = 'Campaign created — sending...';
        // ensure shared socket exists
        if(!window.__campaignSocket || window.__campaignSocket.readyState !== 1){
          initCampaignSocket();
        }
        const socket = window.__campaignSocket;
        const handler = function(event){
          try{
            const payload = JSON.parse(event.data);
            if(payload.campaign_id !== data.campaign_id) return;
            const row = document.querySelector(`#campaign-row-${payload.campaign_id}`);
            if(row){
              row.querySelector('.campaign-status').textContent = payload.status;
              row.querySelector('.campaign-sent').textContent = payload.sent_count || 0;
            }
            if(['sent','partial','failed'].includes(payload.status)){
              progress.textContent = 'Campaign ' + payload.status;
              socket.removeEventListener('message', handler);
            }
          }catch(err){ }
        };
        socket.addEventListener('message', handler);
        socket.addEventListener('error', () => { progress.textContent = 'Realtime updates unavailable'; });
      }
    }).catch(err=>{progress.textContent='Failed'; setTimeout(()=>progress.textContent='',3000)});
  });
}
window.addEventListener('load', setupCampaignForm);

// simple pagination support hooks - assumes server-side endpoints
function setupPagination(){
  const leadsContainer = document.getElementById('leads-tbody');
  const leadsPager = document.getElementById('leads-pagination');
  const campaignsContainer = document.getElementById('campaigns-tbody');
  const campaignsPager = document.getElementById('campaigns-pagination');
  if(leadsContainer && leadsPager){
    let current = 1;
    function renderLeadsPage(page){
      fetch(`/api/leads?page=${page}&per_page=25`).then(r=>r.json()).then(data=>{
        leadsContainer.innerHTML = '';
        data.items.forEach(lead=>{
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${lead.id}</td><td>${lead.name||''}</td><td>${lead.email||''}</td><td>${lead.phone||''}</td><td>${lead.verified}</td><td>${lead.enriched_company||''}</td><td>${lead.source||''}</td>`;
          leadsContainer.appendChild(tr);
        });
        const pages = Math.max(1, Math.ceil(data.total / data.per_page));
        leadsPager.innerHTML = '';
        for(let p=1;p<=pages && p<=10;p++){
          const btn = document.createElement('button'); btn.textContent = p; btn.className = (p===page? 'btn active':'btn');
          btn.addEventListener('click', ()=>{ renderLeadsPage(p); });
          leadsPager.appendChild(btn);
        }
      }).catch(()=>{});
    }
    renderLeadsPage(current);
  }
  if(campaignsContainer && campaignsPager){
    function renderCampaignsPage(page){
      fetch(`/api/campaigns?page=${page}&per_page=25`).then(r=>r.json()).then(data=>{
        campaignsContainer.innerHTML = '';
        data.items.forEach(c=>{
          const tr = document.createElement('tr');
          tr.id = `campaign-row-${c.id}`;
          tr.innerHTML = `<td><a href="/campaigns/${c.id}/view">${c.id}</a></td><td>${c.subject}</td><td class="campaign-status">${c.status}</td><td>${c.recipient_count}</td><td class="campaign-sent">${c.sent_count||0}</td><td>-</td><td>${c.created_at}</td>`;
          campaignsContainer.appendChild(tr);
        });
        const pages = Math.max(1, Math.ceil(data.total / data.per_page));
        campaignsPager.innerHTML = '';
        for(let p=1;p<=pages && p<=10;p++){
          const btn = document.createElement('button'); btn.textContent = p; btn.className = (p===page? 'btn active':'btn');
          btn.addEventListener('click', ()=>{ renderCampaignsPage(p); });
          campaignsPager.appendChild(btn);
        }
      }).catch(()=>{});
    }
    renderCampaignsPage(1);
  }
}

function setupCampaignWebSocket(){
  initCampaignSocket();
}
function initCampaignSocket(){
  if(window.__campaignSocket && window.__campaignSocket.readyState === 1) return;
  const socket = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws/campaigns');
  window.__campaignSocket = socket;
  socket.addEventListener('open', ()=>{ console.info('Campaign socket open'); });
  socket.addEventListener('message', event => {
    try{
      const payload = JSON.parse(event.data);
      if(payload.type === 'ping'){
        socket.send(JSON.stringify({type:'pong'}));
        return;
      }
      const row = document.querySelector(`#campaign-row-${payload.campaign_id}`);
      if(row){
        const statusCell = row.querySelector('.campaign-status');
        const sentCell = row.querySelector('.campaign-sent');
        if(statusCell) statusCell.textContent = payload.status;
        if(sentCell) sentCell.textContent = payload.sent_count || 0;
      }
    }catch(err){ }
  });
  socket.addEventListener('close', ()=>{ console.info('Campaign socket closed'); });
  socket.addEventListener('error', (e)=>{ console.warn('Campaign websocket failed', e); });
  // send periodic pongs if not responding to server pings
  socket.__pongInterval = setInterval(()=>{ try{ if(socket.readyState===1) socket.send(JSON.stringify({type:'pong'})); }catch(e){} }, 30000);
}
window.addEventListener('load', setupPagination);
window.addEventListener('load', setupCampaignWebSocket);

// CSV preview handler
function setupImportPreview(){
  const btn = document.getElementById('preview-button');
  if(!btn) return;
  btn.addEventListener('click', function(){
    const fileInput = document.getElementById('preview-file');
    if(!fileInput || !fileInput.files || !fileInput.files[0]){ alert('Select a CSV file first'); return; }
    const fd = new FormData(); fd.append('file', fileInput.files[0]);
    fetch('/leads/import/preview', { method:'POST', body: fd }).then(r=>r.json()).then(data=>{
      const el = document.getElementById('import-preview');
      el.innerHTML = '';
      const table = document.createElement('table');
      const cols = data.columns || Object.keys(data.sample[0]||{});
      table.innerHTML = '<thead><tr>' + cols.map(k=>`<th>${k}</th>`).join('') + '<th>Duplicate</th></tr></thead>';
      const tbody = document.createElement('tbody');
      data.sample.forEach((row, idx)=>{
        const tr = document.createElement('tr');
        Object.values(row).forEach(v=>{ tr.innerHTML += `<td>${v||''}</td>` });
        tr.innerHTML += `<td>${data.duplicates[idx] ? 'Yes' : 'No'}</td>`;
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      el.appendChild(table);
      // build mapping UI
      const mapEl = document.getElementById('import-mapping');
      mapEl.innerHTML = '';
      const fields = ['name','email','phone','address','source'];
      const form = document.createElement('form'); form.id = 'import-mapping-form';
      cols.forEach(col=>{
        const row = document.createElement('div'); row.className = 'form-row';
        const label = document.createElement('label'); label.textContent = `Map column '${col}' to:`;
        const sel = document.createElement('select'); sel.name = col;
        const empty = document.createElement('option'); empty.value=''; empty.textContent='-- ignore --'; sel.appendChild(empty);
        fields.forEach(f=>{ const opt = document.createElement('option'); opt.value = f; opt.textContent = f; sel.appendChild(opt); });
        row.appendChild(label); row.appendChild(sel); form.appendChild(row);
      });
      const importBtn = document.createElement('button'); importBtn.type='button'; importBtn.className='btn'; importBtn.textContent='Import with mapping';
      importBtn.addEventListener('click', function(){
        const file = document.getElementById('preview-file').files[0];
        if(!file){ alert('Missing file'); return; }
        const mapping = {};
        const elements = form.querySelectorAll('select');
        elements.forEach(s=>{ if(s.value) mapping[s.name]=s.value; });
        const fd2 = new FormData(); fd2.append('file', file); fd2.append('mapping', JSON.stringify(mapping));
        fetch('/leads/import', { method:'POST', body: fd2 }).then(r=>r.json()).then(res=>{ alert('Imported: '+ (res.added||0)); mapEl.innerHTML=''; el.innerHTML=''; }).catch(e=>alert('Import failed'));
      });
      form.appendChild(importBtn);
      mapEl.appendChild(form);
    }).catch(err=>alert('Preview failed'));
  });
}
window.addEventListener('load', setupImportPreview);
