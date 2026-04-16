(() => {
  const ACG = {};

  const qs = new URLSearchParams(location.search);

  function fetchJson(path) {
    return fetch(path, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`${path} → ${r.status}`);
        return r.json();
      });
  }

  function secToHms(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  function fmtDate(iso) {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      if (isNaN(d)) return iso;
      const pad = (n) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    } catch {
      return iso;
    }
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function highlight(text, needle) {
    const safe = escapeHtml(text);
    if (!needle) return safe;
    const n = needle.trim();
    if (!n) return safe;
    try {
      const re = new RegExp(n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
      return safe.replace(re, (m) => `<mark>${m}</mark>`);
    } catch {
      return safe;
    }
  }

  ACG.renderStreamerIndex = function () {
    const listEl = document.getElementById("streamer-list");
    const metaEl = document.getElementById("meta");
    const emptyEl = document.getElementById("empty");

    fetchJson("index.json")
      .then((idx) => {
        metaEl.textContent = `총 ${idx.total_streamers}명 · VOD ${idx.total_vods}편 · 생성 ${fmtDate(idx.generated_at)}`;
        if (!idx.streamers || idx.streamers.length === 0) {
          emptyEl.hidden = false;
          return;
        }
        listEl.innerHTML = idx.streamers
          .map((s) => `
<li class="streamer-card">
  <a href="streamer.html?s=${encodeURIComponent(s.streamer_id)}">
    <div class="name">${escapeHtml(s.streamer_name || s.streamer_id)}</div>
    <div class="meta">${escapeHtml(s.platform)} · VOD ${s.vod_count}편</div>
  </a>
</li>`)
          .join("");
      })
      .catch((e) => {
        metaEl.textContent = "";
        emptyEl.hidden = false;
        emptyEl.textContent = `인덱스 로딩 실패: ${e.message}`;
      });
  };

  ACG.renderStreamerDetail = function () {
    const sid = qs.get("s");
    const nameEl = document.getElementById("streamer-name");
    const metaEl = document.getElementById("streamer-meta");
    const listEl = document.getElementById("vod-list");
    const emptyEl = document.getElementById("empty");

    if (!sid) {
      nameEl.textContent = "스트리머가 지정되지 않았다";
      emptyEl.hidden = false;
      return;
    }

    fetchJson(`streamers/${encodeURIComponent(sid)}/index.json`)
      .then((doc) => {
        const s = doc.streamer;
        nameEl.textContent = s.streamer_name || s.streamer_id;
        metaEl.textContent = `${s.platform} · VOD ${s.vod_count}편`;
        if (!doc.vods || doc.vods.length === 0) {
          emptyEl.hidden = false;
          return;
        }
        listEl.innerHTML = doc.vods
          .map((v) => `
<li class="vod-row">
  <a href="vod.html?v=${encodeURIComponent(v.video_no)}&s=${encodeURIComponent(sid)}">
    <div class="title">${escapeHtml(v.title || "(제목 없음)")}</div>
    <div class="meta">
      <span>${escapeHtml(fmtDate(v.published_at))}</span>
      <span>${escapeHtml(secToHms(v.duration_sec))}</span>
      ${v.platform_category ? `<span>${escapeHtml(v.platform_category)}</span>` : ""}
      <span>채팅 ${Number(v.stats?.total_chats || 0).toLocaleString()}</span>
      <span>하이라이트 ${Number(v.stats?.highlight_count || 0)}</span>
    </div>
  </a>
</li>`)
          .join("");
      })
      .catch((e) => {
        nameEl.textContent = "스트리머 로딩 실패";
        emptyEl.hidden = false;
        emptyEl.textContent = e.message;
      });
  };

  ACG.renderVodDetail = function () {
    const vno = qs.get("v");
    const sid = qs.get("s") || "";
    const titleEl = document.getElementById("vod-title");
    const metaEl = document.getElementById("vod-meta");
    const frameEl = document.getElementById("report-frame");
    const emptyEl = document.getElementById("empty");
    const backEl = document.getElementById("backlink");

    if (sid) {
      backEl.href = `streamer.html?s=${encodeURIComponent(sid)}`;
      backEl.textContent = "← 스트리머 페이지";
    }

    if (!vno) {
      titleEl.textContent = "VOD 가 지정되지 않았다";
      emptyEl.hidden = false;
      frameEl.hidden = true;
      return;
    }

    fetchJson(`vods/${encodeURIComponent(vno)}/index.json`)
      .then((rec) => {
        titleEl.textContent = rec.title || `VOD ${vno}`;
        metaEl.innerHTML = `
          <span class="streamer-chip">${escapeHtml(rec.streamer_name || rec.streamer_id)}</span>
          ${escapeHtml(fmtDate(rec.published_at))} ·
          ${escapeHtml(secToHms(rec.duration_sec))}
          ${rec.platform_category ? ` · ${escapeHtml(rec.platform_category)}` : ""}
        `;
        frameEl.src = rec.summary_html_path;
        if (!sid && rec.streamer_id) {
          backEl.href = `streamer.html?s=${encodeURIComponent(rec.streamer_id)}`;
          backEl.textContent = `← ${rec.streamer_name || rec.streamer_id}`;
        }
      })
      .catch((e) => {
        titleEl.textContent = "VOD 로딩 실패";
        frameEl.hidden = true;
        emptyEl.hidden = false;
        emptyEl.textContent = e.message;
      });
  };

  let _searchCache = null;
  function loadSearchIndex() {
    if (_searchCache) return Promise.resolve(_searchCache);
    return fetchJson("search-index.json").then((rows) => {
      _searchCache = rows;
      return rows;
    });
  }

  function runSearch(query) {
    const q = (query || "").trim().toLowerCase();
    const resEl = document.getElementById("search-results");
    const metaEl = document.getElementById("search-meta");
    resEl.innerHTML = "";

    if (!q) {
      metaEl.textContent = "검색어를 입력하라.";
      return;
    }

    loadSearchIndex().then((rows) => {
      const hits = rows.filter((r) => {
        const hay = `${r.streamer_name || ""} ${r.title || ""} ${r.search_text || ""}`.toLowerCase();
        return hay.includes(q);
      });
      metaEl.textContent = `"${query}" 에 대해 ${hits.length}건.`;
      resEl.innerHTML = hits
        .map((r) => `
<li class="vod-row">
  <a href="vod.html?v=${encodeURIComponent(r.video_no)}&s=${encodeURIComponent(r.streamer_id)}">
    <div class="title">${highlight(r.title || "(제목 없음)", query)}</div>
    <div class="meta">
      <span class="streamer-chip">${escapeHtml(r.streamer_name || r.streamer_id)}</span>
      <span>${escapeHtml(fmtDate(r.published_at))}</span>
    </div>
  </a>
</li>`)
        .join("");
    }).catch((e) => {
      metaEl.textContent = `검색 인덱스 로딩 실패: ${e.message}`;
    });
  }

  ACG.renderSearch = function () {
    const input = document.getElementById("search-input");
    const form = document.getElementById("search-form");
    const initial = qs.get("q") || "";
    if (initial) input.value = initial;

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const v = input.value;
      const url = new URL(location.href);
      url.searchParams.set("q", v);
      history.replaceState(null, "", url);
      runSearch(v);
    });

    input.addEventListener("input", () => {
      runSearch(input.value);
    });

    if (initial) runSearch(initial);
  };

  window.ACG = ACG;
})();
