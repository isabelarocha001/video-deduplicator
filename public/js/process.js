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

    showError("");
    resetSteps();
    resultBox?.classList.remove("is-visible");
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Processando…";
    }
    setStep("upload", "active");

    const fd = new FormData();
    fd.append("file", f);
    fd.append("mode", mode);
    fd.append("subtle", "true");
    fd.append("remove_metadata", "true");
    fd.append("register_supabase", "true");
    fd.append("cdn_prefix", "uploads");
    fd.append("caption", $("caption")?.value || "");
    fd.append("hflip", $("hflip")?.checked ? "true" : "false");
    fd.append("crop_percent", cropPercent?.value || "10");
    fd.append("trim_start", $("trimStart")?.value || "1");
    fd.append("trim_end", $("trimEnd")?.value || "1");
    fd.append("speed", $("speed")?.value || "1.02");
    fd.append("crf", "20");
    fd.append("preset", "medium");

    setStep("upload", "done");
    setStep("process", "active");
    setStep("cdn", "active");
    setStep("db", "active");

    try {
      const res = await fetch("/api/process-and-publish", { method: "POST", body: fd });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) throw new Error(data.error || "HTTP " + res.status);

      setStep("process", "done");
      setStep("cdn", "done");
      if (data.supabase_error) {
        setStep("db", "fail");
        showError("CDN ok, Supabase: " + data.supabase_error);
      } else setStep("db", "done");

      const url = data.public_url || data.media?.public_url || "";
      resultBox?.classList.add("is-visible");
      if (resultUrl) {
        resultUrl.innerHTML = url
          ? 'URL: <a href="' + url + '" target="_blank" rel="noopener">' + url + "</a>"
          : "Sem URL";
      }
      if (resultId) {
        resultId.textContent =
          (data.mode ? "modo=" + data.mode + " · " : "") +
          (data.media?.id ? "id " + data.media.id : data.remote || "");
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
