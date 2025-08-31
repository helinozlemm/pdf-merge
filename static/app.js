const $ = (sel) => document.querySelector(sel);
const filesEl = $('#files');
const btn = $('#btnUpload');
const batchEl = $('#batch'); 
const keysEl = $('#keys');   
const logEl = $('#log');
const bar = $('#bar');
const pct = $('#pct');
const progressWrap = $('#progressWrap');

function humanSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/1024/1024).toFixed(1) + ' MB';
}

filesEl.addEventListener('change', () => {
  const list = Array.from(filesEl.files).map(f => `• ${f.name} (${humanSize(f.size)})`).join('\n');
  $('#selected').innerHTML = list ? `<pre>${list}</pre>` : '';
});

btn.addEventListener('click', async () => {
  const files = filesEl.files;
  if (!files.length) return alert('Please select at least one file.');
  btn.disabled = true; logEl.textContent = ''; if (batchEl) batchEl.textContent = '-'; if (keysEl) keysEl.innerHTML = '';

  const form = new FormData();
  for (const f of files) form.append('files', f);

  progressWrap.style.display = 'block';
  bar.value = 0; pct.textContent = '0';

  try {
    const res = await uploadWithProgress('/merge/from-upload', form, (loaded, total) => {
      const p = total ? Math.round((loaded/total)*100) : 0;
      bar.value = p; pct.textContent = String(p);
    });

    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { throw new Error(`Invalid JSON: ${text}`); }

    if (!res.ok) {
      const msg = data?.detail || `HTTP ${res.status} ${res.statusText}`;
      throw new Error(msg);
    }

    if (data?.url) {
      const a = document.createElement('a');
      a.href = data.url; a.target = '_blank'; a.rel = 'noopener';
      a.textContent = 'Merged PDF (pre-signed) → download';
      logEl.replaceChildren(a);
    } else {
      logEl.textContent = 'Unexpected response: no URL returned.';
    }

    if (Array.isArray(data?.errors) && data.errors.length) {
      const pre = document.createElement('pre');
      pre.textContent = 'Issues:\n' + data.errors.map(e => `- ${(e.file||'file')} → ${(e.reason||'error')}`).join('\n');
      logEl.append('\n', pre);
    }
  } catch (err) {
    logEl.textContent = 'Error: ' + err.message;
  } finally {
    btn.disabled = false;
    setTimeout(() => { progressWrap.style.display = 'none'; }, 600);
  }
});

function uploadWithProgress(url, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.responseType = 'text';
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && typeof onProgress === 'function') {
        onProgress(e.loaded, e.total);
      }
    };
    xhr.onload = () => resolve(new Response(xhr.response, {
      status: xhr.status,
      statusText: xhr.statusText,
      headers: { 'Content-Type': xhr.getResponseHeader('Content-Type') || 'application/json' }
    }));
    xhr.onerror = () => reject(new Error('Network error'));
    xhr.send(formData);
  });
}
