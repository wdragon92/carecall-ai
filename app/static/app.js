// stage 0 placeholder
fetch('/health')
  .then((r) => r.json())
  .then((d) => {
    const el = document.getElementById('health');
    if (el) el.textContent = JSON.stringify(d, null, 2);
  })
  .catch((e) => {
    const el = document.getElementById('health');
    if (el) el.textContent = 'health error: ' + e;
  });
