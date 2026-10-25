'use strict';
(() => {
  // Only visible cards enter the queue. One transfer per origin serves duplicate links.
  const jobs = new Map(), urls = new Set();
  let observer, queue = [], running = 0, epoch = 0;
  function drain() {
    while (running < 4 && queue.length) {
      const job = queue.shift();
      if (job.epoch !== epoch) { job.resolve(''); continue; }
      running++;
      fetch(job.src, {credentials:'same-origin', signal:AbortSignal.timeout(12000)})
        .then(async response => {
          if (!response.ok || response.status === 204) return '';
          const url = URL.createObjectURL(await response.blob()); urls.add(url); return url;
        }).catch(() => '').then(url => {
          if (job.epoch !== epoch && url) { URL.revokeObjectURL(url); urls.delete(url); url = ''; }
          job.resolve(url);
        }).finally(() => { running--; drain(); });
    }
  }
  function load(img) {
    const origin = img.dataset.iconOrigin;
    if (!jobs.has(origin)) jobs.set(origin, new Promise(resolve => {
      queue.push({src:img.dataset.src, resolve, epoch}); drain();
    }));
    jobs.get(origin).then(url => {
      if (!img.isConnected) return;
      if (url) img.src = url; else img.remove();
    });
  }
  window.NavIcons = {
    refresh() {
      observer?.disconnect();
      observer = new IntersectionObserver(entries => {
        for (const entry of entries) if (entry.isIntersecting) { observer.unobserve(entry.target); load(entry.target); }
      }, {rootMargin:'80px'});
      document.querySelectorAll('img[data-favicon]').forEach(img => observer.observe(img));
    },
    stop() {
      epoch++; observer?.disconnect();
      for (const job of queue) job.resolve('');
      queue = []; jobs.clear(); urls.forEach(url => URL.revokeObjectURL(url)); urls.clear();
    }
  };
})();
