/* Trusted UI code only. Snapshot the existing SVG; never interpolate uploaded text. */
(() => {
  if (window.sheepMobileCharts) { window.sheepMobileCharts.scan(); return; }
  const media = matchMedia('(max-width: 767px)');
  const selector = 'div[class*="st-key-mobile_chart_"]';
  const records = new Map();
  const SVG = 'http://www.w3.org/2000/svg';
  const properties = ['fill','fill-opacity','stroke','stroke-width','stroke-opacity',
    'stroke-dasharray','opacity','font-family','font-size','font-weight','font-style',
    'text-anchor','dominant-baseline','visibility','display'];
  let timer, dialog, enlarged, lastFocus;

  function close() { if (dialog?.open) dialog.close(); }
  function viewer() {
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.className = 'mobile-image-viewer';
    dialog.dataset.mobileOwned = 'true';
    const header = document.createElement('header');
    const title = document.createElement('strong');
    title.textContent = '图表原图'; title.id = 'mobile-image-title';
    dialog.setAttribute('aria-labelledby', title.id);
    const fit = document.createElement('button');
    fit.type = 'button'; fit.textContent = '适应屏幕';
    fit.setAttribute('aria-pressed','false');
    const dismiss = document.createElement('button');
    dismiss.type = 'button'; dismiss.textContent = '关闭';
    dismiss.setAttribute('aria-label','关闭图表原图');
    dismiss.addEventListener('click', close);
    fit.addEventListener('click', () => {
      const fitted = dialog.classList.toggle('is-fitted');
      fit.textContent = fitted ? '查看原尺寸' : '适应屏幕';
      fit.setAttribute('aria-pressed', String(fitted));
    });
    header.append(title,fit,dismiss);
    const note = document.createElement('p');
    note.className = 'mobile-image-note';
    note.textContent = '静态原图 · 可上下左右滑动，不会修改图表';
    const scroller = document.createElement('div');
    scroller.className = 'mobile-image-scroll';
    scroller.tabIndex = 0;
    scroller.setAttribute('aria-label','图表原图，可滚动查看');
    enlarged = document.createElement('img');
    scroller.append(enlarged); dialog.append(header,note,scroller);
    dialog.addEventListener('close', () => { lastFocus?.focus({preventScroll:true}); });
    document.body.append(dialog);
    return dialog;
  }

  function open(record, button) {
    if (!media.matches || !record.url) return;
    const modal = viewer(); lastFocus = button;
    modal.classList.remove('is-fitted');
    const fit = modal.querySelector('header button');
    fit.textContent = '适应屏幕'; fit.setAttribute('aria-pressed','false');
    enlarged.src = record.url; enlarged.alt = record.alt;
    enlarged.style.width = record.width + 'px';
    modal.showModal();
    modal.querySelector('.mobile-image-scroll').scrollTo(0,0);
  }

  function snapshot(root) {
    root.querySelector(':scope > [data-testid="stElementContainer"]')?.setAttribute('inert','');
    const plot = root.querySelector('.js-plotly-plot');
    const layers = plot ? [...plot.querySelectorAll('.svg-container > svg.main-svg')] : [];
    if (!layers.length || !plot.querySelector('.cartesianlayer,.pielayer')) return;
    const width = Number(layers[0].getAttribute('width'));
    const height = Number(layers[0].getAttribute('height'));
    if (!width || !height) return;
    const canvas = document.createElementNS(SVG,'svg');
    canvas.setAttribute('xmlns',SVG);
    canvas.setAttribute('width',width); canvas.setAttribute('height',height);
    canvas.setAttribute('viewBox',`0 0 ${width} ${height}`);
    const background = document.createElementNS(SVG,'rect');
    background.setAttribute('width','100%'); background.setAttribute('height','100%');
    background.setAttribute('fill','#ffffff'); canvas.append(background);
    for (const layer of layers) {
      const clone = layer.cloneNode(true);
      const originalNodes = [layer,...layer.querySelectorAll('*')];
      const clonedNodes = [clone,...clone.querySelectorAll('*')];
      originalNodes.forEach((node,index) => {
        const style = getComputedStyle(node);
        for (const prop of properties) clonedNodes[index].style.setProperty(prop, style.getPropertyValue(prop));
      });
      clone.querySelectorAll('.hoverlayer,.draglayer,script,foreignObject').forEach(e=>e.remove());
      // The existing chart has already escaped labels; image rendering disables links/scripts.
      while (clone.firstChild) canvas.append(clone.firstChild);
    }
    const serialized = new XMLSerializer().serializeToString(canvas);
    let record = records.get(root);
    if (record?.serialized === serialized) return;
    if (!record) {
      record = {};
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'mobile-chart-preview';
      button.dataset.mobileOwned = 'true';
      const image = document.createElement('img');
      image.draggable = false;
      const label = document.createElement('span');
      label.textContent = '⤢ 点击放大查看原图';
      button.append(image,label);
      button.addEventListener('click', () => open(record,button));
      root.append(button); record.button = button; record.image = image;
      records.set(root,record);
    }
    const oldUrl = record.url;
    record.serialized = serialized; record.width = width;
    record.alt = plot.querySelector('.gtitle')?.textContent || '分析图表';
    record.url = URL.createObjectURL(new Blob([serialized],{type:'image/svg+xml;charset=utf-8'}));
    record.image.src = record.url; record.image.alt = record.alt;
    record.button.setAttribute('aria-label', '放大查看' + record.alt);
    root.classList.add('mobile-chart-ready');
    // Keep source geometry measurable, but remove its mobile keyboard/gesture targets.
    root.querySelector(':scope > [data-testid="stElementContainer"]')?.setAttribute('inert','');
    if (oldUrl) URL.revokeObjectURL(oldUrl);
  }

  function scan() {
    clearTimeout(timer);
    timer = setTimeout(() => {
      for (const [root,record] of records) {
        if (!root.isConnected) { URL.revokeObjectURL(record.url); records.delete(root); close(); }
      }
      if (!media.matches) return;
      document.querySelectorAll(selector).forEach(root => {
        try { snapshot(root); } catch (error) { console.warn('Mobile chart preview:',error); }
      });
    },160);
  }
  const observer = new MutationObserver(changes => {
    if (changes.some(change => {
      const target = change.target.nodeType === 1 ? change.target : change.target.parentElement;
      if (target?.closest('[data-mobile-owned]')) return false;
      if (change.type === 'attributes') return !!target?.closest('.js-plotly-plot');
      return !!target?.closest(selector) || [...change.addedNodes].some(n => n.nodeType===1 && (n.matches?.(selector)||n.querySelector?.(selector)));
    })) scan();
  });
  observer.observe(document.body,{childList:true,subtree:true,attributes:true});
  media.addEventListener('change', () => {
    close();
    document.querySelectorAll(selector).forEach(root => {
      const original=root.querySelector(':scope > [data-testid="stElementContainer"]');
      if (!media.matches) original?.removeAttribute('inert');
      else if (records.has(root)) original?.setAttribute('inert','');
    });
    scan();
  });
  window.sheepMobileCharts = {scan};
  scan();
})();
