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
  const steps = $("steps");
  const cropPercent = $("cropPercent");
  const cropVal = $("cropVal");

  const PRESETS = {
    light: { hflip: false, crop: 1, trimStart: 0.3, trimEnd: 0.3, speed: 1.0 },
    medium: { hflip: false, crop: 5, trimStart: 0.8, trimEnd: 0.8, speed: 1.01 },
    strong: { hflip: true, crop: 10, trimStart: 1, trimEnd: 1, speed: 1.02 },
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
      if (r.checked) applyPreset(r.value);
    });
  });
  cropPercent?.addEventListener("input", () => {
    if (cropVal) cropVal.textContent = cropPercent.value;
  });
  applyPreset("strong");

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
  }

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = fileInput?.files?.[0];
    if (!f) {
      showError("Escolha um vídeo.");
      return;
    }
    const mode =
      document.querySelector('input[name="mode"]:checked')?.value || "strong";
    let n = parseInt($("variations")?.value || "1", 10);
    if (isNaN(n) || n < 1) n = 1;
    if (n > 10) n = 10;

    showError("");
    resetSteps();
    resultBox?.classList.remove("is-visible");
    if (resultSummary) resultSummary.textContent = "";
    if (resultList) resultList.innerHTML = "";
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
    setStep("cdn", "active");
    setStep("db", "active");

    const endpoint = "/api/index";

    try {
      const res = await fetch(endpoint, { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        const detail = data.error || data.message || data.type || ("HTTP " + res.status);
        const extra = data.traceback ? "\n" + data.traceback.slice(-400) : "";
        throw new Error(detail + extra);
      }

      setStep("process", "done");
      setStep("cdn", "done");
      setStep("db", "done");

      resultBox?.classList.add("is-visible");

      if (data.items && Array.isArray(data.items)) {
        const ok = data.variations_ok || data.items.filter((i) => i.ok).length;
        const requested = data.variations_requested || n;
        const failed = data.items.length - ok;
        if (resultSummary) {
          resultSummary.textContent = `${ok}/${requested} concluída${ok === 1 ? "" : "s"}`;
        }
        if (resultUrl) {
          resultUrl.textContent = failed
            ? "Algumas variações falharam; confira os detalhes abaixo."
            : "Cada versão abaixo mostra exatamente as microedições aplicadas.";
        }
        if (resultId) {
          resultId.textContent = `Modo ${data.mode || mode} · arquivos enviados para o Supabase Storage`;
        }
        if (resultList) {
          resultList.innerHTML = data.items
            .map((it) => {
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
              const registration = it.media?.id
                ? `<div class="result-media-id">Registrado no Supabase · id ${escapeHtml(it.media.id)}</div>`
                : it.supabase_error
                  ? `<div class="result-media-id">Vídeo salvo no Storage; registro no banco pendente: ${escapeHtml(it.supabase_error)}</div>`
                  : "";
              return `<div class="result-item">
                <div class="result-item-title"><strong>${escapeHtml(it.label || "Variação")}</strong><span>Gerada</span></div>
                <div class="result-changes">${renderChanges(it)}</div>
                ${link}
                ${registration}
              </div>`;
            })
            .join("");
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
