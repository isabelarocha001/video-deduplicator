/**
 * Lux social UI — offline / demo mode
 * (Supabase temporariamente indisponível: exceed_db_size_quota até ~12 out)
 */
(function () {
  const THEME_KEY = "lux-theme";

  function getPreferredTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "dark" ? "#000000" : "#ffffff";
    localStorage.setItem(THEME_KEY, theme);
  }
  applyTheme(getPreferredTheme());
  document.getElementById("themeToggle")?.addEventListener("click", () => {
    applyTheme(
      document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark"
    );
  });

  // Demo profile
  const profileUsername = document.getElementById("profileUsername");
  const profileDisplayName = document.getElementById("profileDisplayName");
  const profileBio = document.getElementById("profileBio");
  const statPosts = document.getElementById("statPosts");

  if (profileUsername) profileUsername.textContent = "sofiarivera";
  if (profileDisplayName) profileDisplayName.textContent = "Sofia Rivera";
  if (profileBio) {
    profileBio.innerHTML =
      "Criadora de conteúdo · lifestyle &amp; viagens<br />📍 São Paulo<br /><span class=\"bio-link\">Modo demo — Supabase volta após a cota</span>";
  }

  // Hide auth-only controls if present
  ["btnOpenUpload", "btnLogout", "btnAuth", "authModal", "uploadModal"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.hidden = true;
  });
  const follow = document.getElementById("btnFollow");
  if (follow) {
    follow.hidden = false;
    follow.addEventListener("click", () => {
      const on = follow.classList.toggle("is-following");
      follow.textContent = on ? "Seguindo" : "Seguir";
    });
  }

  const POSTS = [
    { src: "https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=600&h=600&fit=crop", likes: "12,4 mil", comments: "218" },
    { src: "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=600&h=600&fit=crop", likes: "8.902", comments: "94" },
    { src: "https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=600&h=600&fit=crop", likes: "5.331", comments: "61" },
    { src: "https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?w=600&h=600&fit=crop", likes: "19,1 mil", comments: "402" },
    { src: "https://images.unsplash.com/photo-1469474968028-56623f02e42e?w=600&h=600&fit=crop", likes: "7.120", comments: "88" },
    { src: "https://images.unsplash.com/photo-1483985988355-763728e1935b?w=600&h=600&fit=crop", likes: "11,2 mil", comments: "156" },
    { src: "https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=600&h=600&fit=crop", likes: "4.887", comments: "43" },
    { src: "https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?w=600&h=600&fit=crop", likes: "9.014", comments: "112" },
    { src: "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=600&h=600&fit=crop", likes: "15,6 mil", comments: "290" },
  ];

  const grid = document.getElementById("postsGrid");
  const empty = document.getElementById("emptyState");
  if (empty) empty.hidden = true;
  if (statPosts) statPosts.textContent = String(POSTS.length);
  if (grid) {
    grid.innerHTML = POSTS.map(
      (p) => `
      <article class="grid-item">
        <img src="${p.src}" alt="Publicação" loading="lazy" />
        <div class="grid-meta">
          <span>♥ ${p.likes}</span>
          <span>💬 ${p.comments}</span>
        </div>
      </article>`
    ).join("");
  }

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => {
        t.classList.toggle("is-active", t === tab);
      });
    });
  });

  // Create button → soft notice
  function demoNotice() {
    alert("Upload e login voltam quando a cota do Supabase liberar (por volta de 12 de outubro). Por enquanto é só o visual demo.");
  }
  document.getElementById("navCreate")?.addEventListener("click", demoNotice);
  document.getElementById("btnOpenUpload")?.addEventListener("click", demoNotice);
})();
