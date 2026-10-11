(function () {
  const $ = (id) => document.getElementById(id);
  const form = $("processForm");
  const fileInput = $("file");
  const drop = $("drop");
  const hint = $("hint");
  const previewVideo = $("previewVideo");
  const previewImg = $("previewImg");
  const fileList = $("fileList");
  const batchHint = $("batchHint");
  const errorEl = $("error");
  const submitBtn = $("submit");
  const resultBox = $("result");
  const resultSummary = $("resultSummary");
  const resultList = $("resultList");
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
  let selectedFiles = [];

  cropPercent?.addEventListener("input", () => {
    if (cropVal) cropVal.textContent = cropPercent.value;
  });

  function showError(msg) {
    if (!errorEl) return;
    errorEl.hidden = !msg;
    errorEl.textContent = msg || "";
  }

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

  function startProgress(msg) {
    if (progressTimer) window.clearInterval(progressTimer);
    progressStartedAt = Date.now();
    progressValue = 0;
    if (progressPanel) progressPanel.hidden = false;
    setProgress(5, msg || "Enviando…");
    progressTimer = window.setInterval(() => {
      const elapsed = (Date.now() - progressStartedAt) / 1000;
      setProgress(Math.min(90, 8 + elapsed * 0.6), "Processando…");
    }, 500);
  }

  function stopProgress(success) {
    if (progressTimer) window.clearInterval(progressTimer);
    progressTimer = null;
    if (success && progressPanel) progressPanel.hidden = true;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[c])
    );
  }

  function safeHttpUrl(value) {
    try {
      const url = new URL(String(value || ""), window.location.origin);
      return /^https?:$/.test(url.protocol) ? url.href : "";
    } catch (_) {
      return "";
    }
  }

  function isImageFile(f) {
    return f && (f.type.startsWith("image/") || /\.(jpe?g|png|webp|heic|heif|bmp|tiff?)$/i.test(f.name));
  }

  function isVideoFile(f) {
    return f && (f.type.startsWith("video/") || /\.(mp4|webm|mov|mkv|avi|m4v)$/i.test(f.name));
  }

  function onFiles(files) {
    selectedFiles = Array.from(files || []).slice(0, 30);
    showError("");
    resultBox?.classList.remove("is-visible");
    if (previewVideo) {
      previewVideo.hidden = true;
      previewVideo.removeAttribute("src");
    }
    if (previewImg) {
      previewImg.hidden = true;
      previewImg.removeAttribute("src");
    }
    if (fileList) {
      fileList.hidden = true;
      fileList.innerHTML = "";
    }
    if (batchHint) batchHint.hidden = true;
    if (hint) hint.hidden = selectedFiles.length > 0;

    if (!selectedFiles.length) return;

    const images = selectedFiles.filter(isImageFile);
    const videos = selectedFiles.filter(isVideoFile);

    if (images.length > 1) {
      // Lote de fotos
      if (fileList) {
        fileList.hidden = false;
        fileList.innerHTML = images
          .map((f) => `<li>📷 ${escapeHtml(f.name)}</li>`)
          .join("");
      }
      if (batchHint) {
        batchHint.hidden = false;
        batchHint.textContent = `${images.length} fotos selecionadas — serão processadas em lote (metadados limpos + microedições).`;
      }
    } else if (images.length === 1) {
      const url = URL.createObjectURL(images[0]);
      if (previewImg) {
        previewImg.hidden = false;
        previewImg.src = url;
      }
      if (batchHint) {
        batchHint.hidden = false;
        batchHint.textContent = "1 foto — metadados serão removidos + microedições.";
      }
    } else if (videos.length >= 1) {
      const url = URL.createObjectURL(videos[0]);
      if (previewVideo) {
        previewVideo.hidden = false;
        previewVideo.src = url;
      }
      if (videos.length > 1 && batchHint) {
        batchHint.hidden = false;
        batchHint.textContent = "Vídeo: processa 1 por vez. Só o primeiro será enviado.";
      }
    } else if (hint) {
      hint.hidden = false;
      hint.textContent = selectedFiles[0].name;
    }
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
    const list = e.dataTransfer?.files;
    if (list?.length && fileInput) {
      const dt = new DataTransfer();
      Array.from(list).slice(0, 30).forEach((f) => dt.items.add(f));
      fileInput.files = dt.files;
      onFiles(fileInput.files);
    }
  });
  fileInput?.addEventListener("change", () => onFiles(fileInput.files));

  function renderItems(items) {
    if (!resultList) return;
    resultList.innerHTML = items
      .map((item, i) => {
        const url = safeHttpUrl(item.public_url);
        const name = escapeHtml(item.source_name || item.label || `item ${i + 1}`);
        const ok = item.ok;
        const changes = item.changes || {};
        const metaOk = changes.metadata_removed ? "Metadados removidos" : "";
        return `<div class="result-item ${ok ? "" : "is-failed"}">
          <div class="result-item-title">
            <strong>${name}</strong>
            <span>${ok ? "✓" : "✗"}</span>
          </div>
          ${ok && url ? `<a class="result-link" href="${url}" target="_blank" rel="noopener">${url}</a>` : ""}
          ${ok ? `<div class="result-changes">
            <div class="result-change"><strong>Modo:</strong> ${escapeHtml(changes.mode || "—")}</div>
            <div class="result-change"><strong>Crop:</strong> ${changes.crop_percent ?? "—"}%</div>
            <div class="result-change"><strong>${metaOk || "—"}</strong></div>
          </div>` : `<p style="color:var(--danger)">${escapeHtml(item.error || "Erro")}</p>`}
        </div>`;
      })
      .join("");
  }

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!selectedFiles.length) {
      showError("Escolha pelo menos uma foto ou um vídeo.");
      return;
    }

    const mode = document.querySelector('input[name="mode"]:checked')?.value || "light";
    let n = parseInt($("variations")?.value || "1", 10);
    if (isNaN(n) || n < 1) n = 1;
    if (n > 5) n = 5;

    const images = selectedFiles.filter(isImageFile);
    const videos = selectedFiles.filter(isVideoFile);
    const useBatch = images.length >= 1 && videos.length === 0;

    showError("");
    resetSteps();
    resultBox?.classList.remove("is-visible");
    if (resultSummary) resultSummary.textContent = "";
    if (resultList) resultList.innerHTML = "";

    startProgress(
      useBatch
        ? `Enviando ${images.length} foto(s) em lote…`
        : "Enviando…"
    );
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = useBatch
        ? `Processando ${images.length} foto(s)…`
        : "Processando…";
    }
    setStep("upload", "active");

    try {
      let data;

      if (useBatch) {
        const fd = new FormData();
        images.forEach((f) => fd.append("files", f));
        fd.append("mode", mode === "multi" ? "medium" : mode);
        fd.append("variations", String(n));
        fd.append("crop_percent", cropPercent?.value || "2");
        fd.append("register_supabase", "true");
        fd.append("cdn_prefix", "uploads");
        fd.append("caption", $("caption")?.value || "");

        setStep("upload", "done");
        setStep("process", "active");

        const res = await fetch("/api/process-batch", { method: "POST", body: fd });
        data = await res.json().catch(() => ({}));
        if (!res.ok && !data.items) {
          throw new Error(data.error || `HTTP ${res.status}`);
        }
      } else {
        // Um vídeo (ou 1 arquivo)
        const f = videos[0] || selectedFiles[0];
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
        fd.append("crop_percent", cropPercent?.value || "2");

        setStep("upload", "done");
        setStep("process", "active");

        const res = await fetch("/api/process-and-publish", { method: "POST", body: fd });
        data = await res.json().catch(() => ({}));
        if (!res.ok && !data.items) {
          throw new Error(data.error || `HTTP ${res.status}`);
        }
      }

      setStep("process", "done");
      setStep("cdn", "done");
      setStep("db", "done");
      stopProgress(true);

      const items = data.items || [];
      const okCount = items.filter((i) => i.ok).length;
      if (resultSummary) {
        resultSummary.textContent = `${okCount}/${items.length} ok`;
      }
      renderItems(items);
      resultBox?.classList.add("is-visible");

      if (okCount === 0) {
        showError(data.error || "Nenhum arquivo processado com sucesso.");
      }
    } catch (err) {
      stopProgress(false);
      setStep("process", "fail");
      showError(err.message || String(err));
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Processar e publicar";
      }
    }
  });
})();
