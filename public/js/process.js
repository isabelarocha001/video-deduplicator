(function () {
  const $ = (id) => document.getElementById(id);
  const form = $("processForm");
  const fileInput = $("file");
  const drop = $("drop");
  const hint = $("hint");
  const previewVideo = $("previewVideo");
  const previewImg = $("previewImg");
  const errorEl = $("error");
  const submitBtn = $("submit");
  const resultBox = $("result");
  const resultUrl = $("resultUrl");
  const resultId = $("resultId");
  const resultSummary = $("resultSummary");
  const resultList = $("resultList");
  const metadataPanel = $("metadataPanel");
  const metadataContent = $("metadataContent");
  const qualityPanel = $("qualityPanel");
  const qualityContent = $("qualityContent");
  const steps = $("steps");
  const cropPercent = $("cropPercent");
  const cropVal = $("cropVal");
  const progressPanel = $("progressPanel");
  const progressBar = $("progressBar");
  const progressPercent = $("progressPercent");
  const progressMessage = $("progressMessage");
  const progressElapsed = $("progressElapsed");
  const progressTrack = progressPanel?.querySelector('[role="progressbar"]');
  let progressTimer = null;
  let progressStartedAt = 0;
  let progressValue = 0;
  let metadataRequestId = 0;
  let qualityRequestId = 0;

  const PRESETS = {
    light: { hflip: false, crop: 1, trimStart: 0.3, trimEnd: 0.3, speed: 1.0 },
    medium: { hflip: false, crop: 5, trimStart: 0.8, trimEnd: 0.8, speed: 1.01 },
    strong: { hflip: true, crop: 10, trimStart: 1, trimEnd: 1, speed: 1.02 },
    heavy: { hflip: true, crop: 18, trimStart: 1.5, trimEnd: 1.5, speed: 1.04 },
    multi: { hflip: true, crop: 18, trimStart: 0, trimEnd: 0, speed: 1.04 },
  };

  function applyPreset(mode) {
    const p = PRESETS[mode] || PRESETS.strong;
    if ($("hflip")) $("hflip").checked = p.hflip;
    if (cropPercent) cropPercent.value = p.crop;
    if (cropVal) cropVal.textContent = String(p.crop);
    if ($("trimStart")) $("trimStart").value = p.trimStart;
    if ($("trimEnd")) $("trimEnd").value = p.trimEnd;
    if ($("speed")) $("speed").value = p.speed;
  }

  document.querySelectorAll('input[name="mode"]').forEach((r) => {
    r.addEventListener("change", () => {
      if (r.checked) {
        applyPreset(r.value);
        if (r.value === "multi") {
          if ($("variations")) $("variations").value = "3";
          if ($("muteAudio")) $("muteAudio").checked = true;
        }
      }
    });
  });
  cropPercent?.addEventListener("input", () => {
    if (cropVal) cropVal.textContent = cropPercent.value;
  });
  applyPreset("multi");

  function setStep(name, state) {
    steps?.querySelectorAll("li").forEach((li) => {
      if (li.getAttribute("data-step") === name) {
        li.classList.remove("is-active", "is-done", "is-fail");
        if (state) li.classList.add("is-" + state);
      }
    });
  }
  function resetSteps() {
    steps?.querySelectorAll("li").forEach((li) =>
      li.classList.remove("is-active", "is-done", "is-fail")
    );
  }
  function showError(msg) {
    if (!errorEl) return;
    errorEl.hidden = !msg;
    errorEl.textContent = msg || "";
  }

  function formatElapsed(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    const minutes = Math.floor(total / 60);
    const rest = String(total % 60).padStart(2, "0");
    return `${minutes}:${rest}`;
  }

  function setProgress(value, message) {
    progressValue = Math.max(progressValue, Math.min(100, Math.round(value)));
    if (progressBar) progressBar.style.width = `${progressValue}%`;
    if (progressPercent) progressPercent.textContent = `${progressValue}%`;
    if (progressMessage && message) progressMessage.textContent = message;
    if (progressTrack) progressTrack.setAttribute("aria-valuenow", String(progressValue));
    if (progressElapsed && progressStartedAt) {
      progressElapsed.textContent = `Tempo decorrido: ${formatElapsed((Date.now() - progressStartedAt) / 1000)}`;
    }
  }

  function startProgress(variations) {
    if (progressTimer) window.clearInterval(progressTimer);
    progressStartedAt = Date.now();
    progressValue = 0;
    if (progressPanel) progressPanel.hidden = false;
    setProgress(5, `Enviando vídeo e preparando ${variations} variação${variations === 1 ? "" : "ões"}…`);
    progressTimer = window.setInterval(() => {
      const elapsed = (Date.now() - progressStartedAt) / 1000;
      const estimated = Math.min(90, 8 + elapsed * 0.7);
      const message = elapsed < 4
        ? "Enviando vídeo…"
        : "Aplicando microedições e salvando o resultado…";
      setProgress(estimated, message);
    }, 500);
  }

  function stopProgress(success, message) {
    if (progressTimer) window.clearInterval(progressTimer);
    progressTimer = null;
    if (success) {
      // O resultado já chegou: não faça o usuário esperar a animação terminar.
      if (progressPanel) progressPanel.hidden = true;
      return;
    }
    setProgress(100, message || "Processamento encerrado com erro.");
  }

  function attachFullscreenButtons() {
    resultList?.querySelectorAll("[data-preview]").forEach((button) => {
      button.addEventListener("click", async () => {
        const video = document.getElementById(button.getAttribute("data-preview"));
        if (!video) return;
        try {
          if (video.requestFullscreen) await video.requestFullscreen();
          else if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
        } catch (_) {
          // Some mobile browsers only allow their native fullscreen control.
        }
      });
    });
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    })[char]);
  }

  function numberPt(value, digits = 2) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return number.toLocaleString("pt-BR", { maximumFractionDigits: digits });
  }

  function yesNo(value) {
    return value ? "Sim" : "Não";
  }

  function safeHttpUrl(value) {
    try {
      const url = new URL(String(value || ""), window.location.origin);
      return /^https?:$/.test(url.protocol) ? url.href : "";
    } catch (_) {
      return "";
    }
  }

  function metadataEntries(snapshot) {
    if (!snapshot || !snapshot.available) return [];
    const entries = [];
    Object.entries(snapshot.tags || {}).forEach(([key, value]) => {
      entries.push({ scope: "Contêiner", key, value });
    });
    (snapshot.streams || []).forEach((stream) => {
      const scope = `Stream ${stream.index ?? "?"} (${stream.codec_type || "stream"})`;
      Object.entries(stream.tags || {}).forEach(([key, value]) => {
        entries.push({ scope, key, value });
      });
    });
    (snapshot.chapters || []).forEach((chapter) => {
      const scope = `Capítulo ${chapter.id ?? "?"}`;
      Object.entries(chapter.tags || {}).forEach(([key, value]) => {
        entries.push({ scope, key, value });
      });
    });
    return entries;
  }

  function renderMetadataSnapshot(snapshot) {
    if (!snapshot || !snapshot.available) {
      return `<p class="metadata-muted">${escapeHtml(snapshot?.error || "Não foi possível ler os metadados neste ambiente.")}</p>`;
    }
    const entries = metadataEntries(snapshot);
    const tags = entries.length
      ? `<ul class="metadata-list">${entries.map((entry) =>
          `<li><strong>${escapeHtml(entry.scope)} · ${escapeHtml(entry.key)}:</strong> ${escapeHtml(entry.value)}</li>`
        ).join("")}</ul>`
      : `<p class="metadata-muted">Nenhuma tag de metadado foi encontrada.</p>`;
    const format = snapshot.format || {};
    const technical = [
      ["Formato", format.format_name],
      ["Duração", format.duration ? `${numberPt(format.duration, 2)} s` : ""],
      ["Tamanho", format.size ? `${numberPt(Number(format.size) / 1024 / 1024, 2)} MB` : ""],
      ["Bitrate", format.bit_rate ? `${numberPt(Number(format.bit_rate) / 1000, 0)} kbps` : ""],
    ].filter(([, value]) => value !== undefined && value !== null && value !== "");
    const technicalHtml = technical.length
      ? `<h3>Informações técnicas detectadas</h3><ul class="metadata-list">${technical.map(([label, value]) =>
          `<li><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</li>`
        ).join("")}</ul>`
      : "";
    return `<h3>Tags encontradas no arquivo original</h3>${tags}${technicalHtml}`;
  }

  function renderRemovedMetadata(item) {
    const removed = item.metadata_removed_details || [];
    const removedHtml = removed.length
      ? `<ul class="metadata-list">${removed.map((entry) =>
          `<li><strong>${escapeHtml(entry.scope)} · ${escapeHtml(entry.key)}:</strong> ${escapeHtml(entry.value)}</li>`
        ).join("")}</ul>`
      : `<p class="metadata-muted">Nenhuma tag de origem foi identificada para remoção.</p>`;
    const output = item.metadata_after && item.metadata_after.available
      ? `<details class="metadata-output"><summary>Metadados detectados no arquivo processado</summary>${renderMetadataSnapshot(item.metadata_after)}</details>`
      : "";
    return `<div class="metadata-removed"><h3>Metadados removidos nesta versão</h3>${removedHtml}${output}</div>`;
  }

  async function inspectFileMetadata(file) {
    const requestId = ++metadataRequestId;
    if (metadataPanel) metadataPanel.hidden = false;
    if (metadataContent) metadataContent.innerHTML = `<p class="metadata-muted">Lendo os metadados do vídeo…</p>`;
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch("/api/inspect", { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));
      if (requestId !== metadataRequestId) return;
      if (!res.ok || !data.ok) {
        throw new Error(data.error || `Não foi possível ler os metadados (HTTP ${res.status}).`);
      }
      if (metadataContent) metadataContent.innerHTML = renderMetadataSnapshot(data.metadata);
    } catch (err) {
      if (requestId !== metadataRequestId) return;
      if (metadataContent) metadataContent.innerHTML = `<p class="metadata-muted">${escapeHtml(err.message || String(err))}</p>`;
    }
  }

  function waitForVideoEvent(video, eventName) {
    return new Promise((resolve, reject) => {
      const onEvent = () => {
        cleanup();
        resolve();
      };
      const onError = () => {
        cleanup();
        reject(new Error("Não foi possível ler os quadros do vídeo."));
      };
      const cleanup = () => {
        video.removeEventListener(eventName, onEvent);
        video.removeEventListener("error", onError);
      };
      video.addEventListener(eventName, onEvent, { once: true });
      video.addEventListener("error", onError, { once: true });
    });
  }

  function seekVideo(video, time) {
    return new Promise((resolve) => {
      const target = Math.max(0, Math.min(Number(time) || 0, video.duration || 0));
      if (Math.abs(video.currentTime - target) < 0.05) {
        resolve();
        return;
      }
      const onSeeked = () => {
        video.removeEventListener("seeked", onSeeked);
        resolve();
      };
      video.addEventListener("seeked", onSeeked, { once: true });
      video.currentTime = target;
    });
  }

  async function inspectQrCode(file) {
    const requestId = ++qualityRequestId;
    if (qualityPanel) qualityPanel.hidden = false;
    if (qualityContent) qualityContent.innerHTML = `<p class="metadata-muted">Verificando alguns quadros em busca de QR Code…</p>`;

    if (!file.type.startsWith("video/")) {
      if (qualityContent) qualityContent.innerHTML = `<p class="metadata-muted">A verificação de QR Code está disponível para vídeos.</p>`;
      return;
    }
    if (!("BarcodeDetector" in window)) {
      if (qualityContent) qualityContent.innerHTML = `<p class="metadata-muted">Este navegador não oferece leitura automática de QR Code. Confira o vídeo original antes de publicar.</p>`;
      return;
    }

    let detector;
    try {
      detector = new window.BarcodeDetector({ formats: ["qr_code"] });
    } catch (_) {
      if (qualityContent) qualityContent.innerHTML = `<p class="metadata-muted">A leitura automática de QR Code não está disponível neste navegador.</p>`;
      return;
    }

    const video = document.createElement("video");
    const objectUrl = URL.createObjectURL(file);
    video.preload = "metadata";
    video.muted = true;
    video.playsInline = true;
    video.src = objectUrl;
    try {
      await waitForVideoEvent(video, "loadedmetadata");
      const canvas = document.createElement("canvas");
      const maxDimension = 1280;
      const scale = Math.min(1, maxDimension / Math.max(video.videoWidth, video.videoHeight));
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      const context = canvas.getContext("2d", { willReadFrequently: true });
      const duration = Number.isFinite(video.duration) ? video.duration : 0;
      const sampleTimes = duration > 0
        ? [0, duration * 0.25, duration * 0.5, duration * 0.75, Math.max(0, duration - 0.1)]
        : [0];
      let found = false;
      for (const time of sampleTimes) {
        await seekVideo(video, time);
        if (!context) continue;
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const codes = await detector.detect(canvas);
        if (codes && codes.length) {
          found = true;
          break;
        }
      }
      if (requestId !== qualityRequestId) return;
      if (qualityContent) {
        qualityContent.innerHTML = found
          ? `<p class="quality-warning">QR Code detectado em um dos quadros. Use o arquivo original sem QR Code ou remova-o no projeto antes de publicar.</p>`
          : `<p class="quality-ok">Nenhum QR Code foi detectado nos quadros analisados. Isso não substitui uma conferência visual completa.</p>`;
      }
    } catch (err) {
      if (requestId === qualityRequestId && qualityContent) {
        qualityContent.innerHTML = `<p class="metadata-muted">Não foi possível verificar o QR Code automaticamente: ${escapeHtml(err.message || String(err))}</p>`;
      }
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  }

  function renderChanges(item) {
    const changes = item.changes || item.params || {};
    const rows = [
      ["Modo", changes.mode || "—"],
      ["Crop", `${numberPt(changes.crop_percent)}%`],
      ["Espelhamento", yesNo(changes.hflip)],
      ["Corte inicial", `${numberPt(changes.trim_start)} s`],
      ["Corte final", `${numberPt(changes.trim_end)} s`],
      ["Velocidade", `${numberPt(changes.speed, 4)}x`],
      ["Áudio original", changes.audio_removed ? "Removido" : "Mantido"],
      ["Metadados", changes.metadata_removed ? "Removidos" : "Mantidos"],
    ];
    return rows.map(([label, value]) =>
      `<div class="result-change"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(value)}</div>`
    ).join("");
  }

  drop?.addEventListener("click", () => fileInput?.click());
  ["dragenter", "dragover"].forEach((ev) =>
    drop?.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.add("is-drag");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    drop?.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.remove("is-drag");
    })
  );
  drop?.addEventListener("drop", (e) => {
    const f = e.dataTransfer?.files?.[0];
    if (f && fileInput) {
      const dt = new DataTransfer();
      dt.items.add(f);
      fileInput.files = dt.files;
      onFile(f);
    }
  });
  fileInput?.addEventListener("change", () => {
    const f = fileInput.files?.[0];
    if (f) onFile(f);
  });

  function onFile(f) {
    showError("");
    if (progressTimer) window.clearInterval(progressTimer);
    progressTimer = null;
    if (progressPanel) progressPanel.hidden = true;
    if (metadataPanel) metadataPanel.hidden = false;
    if (metadataContent) metadataContent.innerHTML = `<p class="metadata-muted">Lendo os metadados do vídeo…</p>`;
    if (qualityPanel) qualityPanel.hidden = false;
    if (qualityContent) qualityContent.innerHTML = `<p class="metadata-muted">Preparando a verificação do vídeo…</p>`;
    resultBox?.classList.remove("is-visible");
    if (hint) hint.hidden = true;
    if (previewVideo) {
      previewVideo.hidden = true;
      previewVideo.removeAttribute("src");
    }
    if (previewImg) {
      previewImg.hidden = true;
      previewImg.removeAttribute("src");
    }
    const url = URL.createObjectURL(f);
    if (f.type.startsWith("video/") && previewVideo) {
      previewVideo.hidden = false;
      previewVideo.src = url;
    } else if (f.type.startsWith("image/") && previewImg) {
      previewImg.hidden = false;
      previewImg.src = url;
    } else if (hint) {
      hint.hidden = false;
      hint.textContent = f.name;
    }
    inspectFileMetadata(f);
    inspectQrCode(f);
  }

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = fileInput?.files?.[0];
    if (!f) {
      showError("Escolha um vídeo.");
      return;
    }
    const mode =
      document.querySelector('input[name="mode"]:checked')?.value || "multi";
    let n = parseInt($("variations")?.value || "1", 10);
    if (isNaN(n) || n < 1) n = 1;
    if (n > 10) n = 10;

    showError("");
    resetSteps();
    resultBox?.classList.remove("is-visible");
    if (resultSummary) resultSummary.textContent = "";
    if (resultList) resultList.innerHTML = "";
    startProgress(n);
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = n > 1 ? `Gerando ${n} variações…` : "Processando…";
    }
    setStep("upload", "active");

    const fd = new FormData();
    fd.append("file", f);
    fd.append("action", n > 1 ? "process-variations" : "process-and-publish");
    fd.append("variations", String(n));
    fd.append("mode", mode);
    fd.append("subtle", "true");
    fd.append("remove_metadata", "true");
    fd.append("register_supabase", "true");
    fd.append("cdn_prefix", "uploads");
    fd.append("caption", $("caption")?.value || "");
    fd.append("hflip", $("hflip")?.checked ? "true" : "false");
    fd.append("mute_audio", $("muteAudio")?.checked ? "true" : "false");
    fd.append("crop_percent", cropPercent?.value || "10");
    fd.append("trim_start", $("trimStart")?.value || "1");
    fd.append("trim_end", $("trimEnd")?.value || "1");
    fd.append("speed", $("speed")?.value || "1.02");
    fd.append("crf", "20");
    fd.append("preset", "medium");
    fd.append("seed", String(Date.now() % 100000));

    setStep("upload", "done");
    setStep("process", "active");

    const endpoint = "/api/index";

    try {
      const res = await fetch(endpoint, { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));
      const hasItems = Array.isArray(data.items);
      if ((!res.ok || data.ok === false) && !hasItems) {
        const detail = data.error || data.message || data.type || ("HTTP " + res.status);
        const extra = data.traceback ? "\n" + data.traceback.slice(-400) : "";
        throw new Error(detail + extra);
      }

      const okCount = hasItems ? data.items.filter((item) => item.ok).length : 1;
      const stepState = okCount > 0 ? "done" : "fail";
      setStep("process", stepState);
      setStep("cdn", stepState);
      setStep("db", stepState);
      stopProgress(okCount > 0, okCount > 0 ? "Processamento concluído." : "Nenhuma variação foi gerada.");

      resultBox?.classList.add("is-visible");

      if (data.items && Array.isArray(data.items)) {
        const ok = data.variations_ok || data.items.filter((i) => i.ok).length;
        const requested = data.variations_requested || n;
        const failed = data.items.length - ok;
        if (resultSummary) {
          resultSummary.textContent = `${ok}/${requested} concluída${ok === 1 ? "" : "s"}`;
        }
        if (resultUrl) {
          resultUrl.textContent = ok === 0
            ? "Nenhuma versão foi gerada. O erro detalhado de cada tentativa está abaixo."
            : failed
              ? "Algumas variações falharam; confira os detalhes abaixo."
            : "Cada versão abaixo mostra exatamente as microedições aplicadas.";
        }
        if (resultId) {
          resultId.textContent = ok === 0
            ? `Modo ${data.mode || mode} · nenhum arquivo foi salvo`
            : `Modo ${data.mode || mode} · arquivos enviados para o Supabase Storage`;
        }
        if (resultList) {
          resultList.innerHTML = data.items
            .map((it, index) => {
              if (!it.ok) {
                return `<div class="result-item is-failed">
                  <div class="result-item-title"><strong>${escapeHtml(it.label || "Variação")}</strong><span>Falhou</span></div>
                  <div style="margin-top:8px;color:var(--danger)">${escapeHtml(it.error || "Não foi possível gerar esta versão.")}</div>
                </div>`;
              }
              const url = safeHttpUrl(it.public_url);
              const link = url
                ? `<a class="result-link" href="${escapeHtml(url)}" target="_blank" rel="noopener">Abrir vídeo processado</a>`
                : "Link indisponível";
              const previewId = `result-preview-${index}`;
              const preview = url
                ? `<div class="result-preview-wrap">
                    <video class="result-preview" id="${previewId}" controls playsinline preload="metadata" src="${escapeHtml(url)}"></video>
                    <button type="button" class="preview-fullscreen" data-preview="${previewId}">Tela cheia</button>
                  </div>`
                : "";
              const registration = it.media?.id
                ? `<div class="result-media-id">Registrado no Supabase · id ${escapeHtml(it.media.id)}</div>`
                : it.supabase_error
                  ? `<div class="result-media-id">Vídeo salvo no Storage; registro no banco pendente: ${escapeHtml(it.supabase_error)}</div>`
                  : "";
              return `<div class="result-item">
                <div class="result-item-title"><strong>${escapeHtml(it.label || "Variação")}</strong><span>Gerada</span></div>
                <div class="result-changes">${renderChanges(it)}</div>
                ${preview}
                ${link}
                ${renderRemovedMetadata(it)}
                ${registration}
              </div>`;
            })
            .join("");
          attachFullscreenButtons();
        }
      } else {
        const url = data.public_url || data.media?.public_url || "";
        if (resultUrl) {
          const safeUrl = safeHttpUrl(url);
          resultUrl.innerHTML = safeUrl
            ? '<a class="result-link" href="' + escapeHtml(safeUrl) + '" target="_blank" rel="noopener">Abrir vídeo processado</a>'
            : "Link indisponível";
        }
        if (resultId) {
          resultId.textContent = data.mode
            ? `Modo ${data.mode} · arquivo enviado para o Supabase Storage`
            : "Arquivo enviado para o Supabase Storage";
        }
        if (resultSummary) resultSummary.textContent = url ? "1/1 concluída" : "Sem arquivo";
      }
    } catch (err) {
      stopProgress(false, "Falha no processamento.");
      setStep("process", "fail");
      setStep("cdn", "fail");
      setStep("db", "fail");
      showError(err.message || String(err));
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Processar e publicar";
      }
    }
  });
})();
