// Tweet Workshop: ideas the drafter saved from Slack, and the team's work on Studio's drafts.
(function () {
  const TABS = [
    ["new", "New"],
    ["workshopping", "Workshopping"],
    ["waiting", "Needs material"],
    ["ready", "Ready to post"],
    ["posted", "Posted"],
    ["skipped", "Skipped"],
  ];
  const COLORS = ["#97630C", "#D26645", "#0B292B", "#492222", "#4B4C08", "#2F4F6B", "#6B2F5A"];
  const REWORKS = {
    shorter: "Make it shorter and punchier.",
    playful: "Make it more playful.",
    concrete: "Make it more concrete and specific.",
  };

  let data = null;
  let tab = "new";
  let selected = null;
  let reworkOpen = null;
  let working = null;
  let saveTimer = null;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const linkify = (s) => esc(s).replace(/(https?:\/\/[^\s|>]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
  // Slack writes links as <url> or <url|label>; show them as plain urls.
  const slackText = (s) => s.replace(/<(https?:[^|>]+)(\|[^>]*)?>/g, "$1");
  const me = () => $("me").value.trim() || "someone";
  const avatar = (name, small) => {
    let h = 0;
    for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return `<span class="avatar${small ? " small" : ""}" style="background:${COLORS[h % COLORS.length]}" title="${esc(name)}">${esc(name[0] || "?").toUpperCase()}</span>`;
  };
  const shortDate = (iso) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const ideas = () => (data ? data.ideas : []);
  const idea = () => ideas().find((i) => i.id === selected);

  function toast(msg) {
    const t = $("toast");
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => (t.hidden = true), 2200);
  }

  async function api(method, path, body) {
    const res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || `Request failed (${res.status})`);
    return json;
  }

  async function load() {
    data = await api("GET", "/api/ideas");
    if (!selected || !idea()) {
      const first = ideas().find((i) => i.workshop.status === tab);
      selected = first ? first.id : null;
    }
    renderHeader();
    render();
  }

  async function save(i) {
    clearTimeout(saveTimer);
    const updated = await api("PUT", `/api/ideas/${i.id}/workshop`, i.workshop);
    data.ideas = ideas().map((x) => (x.id === updated.id ? updated : x));
  }

  function saveSoon(i) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => save(i).catch((e) => toast(e.message)), 600);
  }

  function renderHeader() {
    const channel = data.channel_name ? `#${esc(data.channel_name)}` : "Slack";
    const channelLink = data.channel_url ? `<a href="${esc(data.channel_url)}" target="_blank" rel="noopener">${channel}</a>` : channel;
    const guide = data.voice_guide.url
      ? `<a href="${esc(data.voice_guide.url)}" target="_blank" rel="noopener">voice guide</a>`
      : "voice guide";
    const posting = data.post_to_slack ? "drafts are also replied in Slack" : "drafts stay here, nothing is posted to Slack";
    $("sources").innerHTML = `Ideas from ${channelLink}<span class="sep">&middot;</span>Written to the ${guide}<span class="sep">&middot;</span>${posting}`;
    const missing = [];
    if (!data.channel_name && !data.channel_url) missing.push("which Slack channel to read ideas from");
    if (!data.voice_guide.stored) missing.push("a link to your voice guide");
    $("setup").hidden = !missing.length;
    $("setup").innerHTML = missing.length
      ? `<b>Not set up yet.</b> Studio needs ${missing.join(" and ")} before it can draft anything. Ask Studio in a chat to set up Tweet Workshop.`
      : "";
  }

  function renderTabs() {
    $("tabs").innerHTML = TABS.map(([key, label]) => {
      const n = ideas().filter((i) => i.workshop.status === key).length;
      return `<button class="tab${key === tab ? " active" : ""}" data-tab="${key}">${label}<span class="count">${n || ""}</span></button>`;
    }).join("");
  }

  function renderList() {
    const rows = ideas().filter((i) => i.workshop.status === tab);
    if (!rows.length) {
      const where = data && data.channel_name ? `#${esc(data.channel_name)}` : "the ideas channel";
      const empty = {
        posted: "Nothing posted yet. When a tweet goes out, paste its link on the idea and it lands here.",
        new: `No new ideas. Anything posted in ${where} shows up here with drafts within about 10 minutes.`,
      }[tab] || "Nothing here right now.";
      $("idea-list").innerHTML = `<li class="empty">${empty}</li>`;
      return;
    }
    $("idea-list").innerHTML = rows
      .map((i) => {
        const n = i.workshop.drafts.length;
        const c = i.workshop.comments.length;
        return `<li class="idea-row${i.id === selected ? " selected" : ""}" data-id="${i.id}">
          <div class="who">${avatar(i.author, true)} ${esc(i.author)} <span>&middot; ${shortDate(i.when)}</span></div>
          <div class="snippet">${esc(slackText(i.text) || (i.link ? slackText(i.link.desc || i.link.title) : ""))}</div>
          <div class="meta">${n ? `${n} draft${n > 1 ? "s" : ""}` : "no drafts"}${c ? ` &middot; ${c} comment${c > 1 ? "s" : ""}` : ""}</div>
        </li>`;
      })
      .join("");
  }

  function draftHtml(d, idx) {
    const text = d.versions[d.versions.length - 1];
    const over = text.length > 280;
    const versionNote =
      d.versions.length > 1
        ? `<span class="version">version ${d.versions.length} of ${d.versions.length} &middot; <button class="textlink" data-act="undo" data-i="${idx}">go back</button></span>`
        : "";
    const rework =
      reworkOpen === idx
        ? `<div class="rework-menu">
            <button class="btn" data-act="rw" data-kind="shorter" data-i="${idx}">Shorter</button>
            <button class="btn" data-act="rw" data-kind="playful" data-i="${idx}">More playful</button>
            <button class="btn" data-act="rw" data-kind="concrete" data-i="${idx}">More concrete</button>
            <input id="rw-input" placeholder="Or tell Studio what to change">
            <button class="btn" data-act="rw" data-kind="custom" data-i="${idx}">Rewrite</button>
          </div>`
        : "";
    const body =
      working === idx
        ? `<div class="working">Studio is rewriting this draft...</div>`
        : `<textarea data-i="${idx}" rows="3">${esc(text)}</textarea>`;
    return `<div class="draft${d.picked ? " picked" : ""}">
      ${body}
      <div class="draft-foot">
        <span class="chars${over ? " over" : ""}" id="chars-${idx}">${text.length}/280</span>
        <span class="grow"></span>
        ${versionNote}
        <button class="btn" data-act="rework" data-i="${idx}" ${working !== null ? "disabled" : ""}>Rework</button>
        <button class="btn${d.picked ? " primary" : ""}" data-act="pick" data-i="${idx}">${d.picked ? "Picked" : "Pick this one"}</button>
      </div>
      ${rework}
    </div>`;
  }

  function renderDetail() {
    const i = idea();
    if (!i) {
      $("detail").innerHTML = `<div class="empty">${ideas().length ? "Pick an idea on the left." : ""}</div>`;
      return;
    }
    const w = i.workshop;
    const where = data.channel_name ? `#${esc(data.channel_name)}` : "Slack";
    const sources = [
      `<a class="textlink" href="/api/ideas/${i.id}/record" target="_blank" rel="noopener">View saved record</a>`,
      i.source_url ? `<a class="textlink" href="${esc(i.source_url)}" target="_blank" rel="noopener">Open in Slack</a>` : "",
    ].join(" ");
    const link = i.link
      ? `<a class="linkcard" href="${esc(i.link.url)}" target="_blank" rel="noopener"><div class="host">${esc(i.link.host)}</div><div><b>${esc(i.link.title)}</b></div><div class="desc">${esc(slackText(i.link.desc))}</div></a>`
      : "";
    const note = [
      i.angle ? `<b>Angle:</b> ${esc(i.angle)}` : "",
      i.needs ? `<b>Would help:</b> ${esc(i.needs)}` : "",
    ].filter(Boolean).join("<br>");
    const picked = w.drafts.find((d) => d.picked);

    let actions = "";
    if (w.status === "ready" && picked) {
      actions = `<h3>Ready to post</h3>
        <div class="ready-box">
          <div class="final">${esc(picked.versions[picked.versions.length - 1])}</div>
          <div class="actionbar" style="border:none;margin-top:12px;padding-top:0">
            <button class="btn primary" data-act="copy">Copy text</button>
            <a class="btn" href="https://x.com/compose/post" target="_blank" rel="noopener" style="text-decoration:none;color:inherit">Open X</a>
            <span class="grow"></span>
            <button class="btn" data-act="back">Back to workshopping</button>
          </div>
          <input id="posted-url" placeholder="Posted it? Paste the tweet link here and press Enter to file it under Posted">
        </div>`;
    } else if (w.status === "posted") {
      actions = `<h3>Posted</h3><div class="ready-box"><div class="final">${esc(picked ? picked.versions[picked.versions.length - 1] : "")}</div>
        ${w.posted_url ? `<p><a href="${esc(w.posted_url)}" target="_blank" rel="noopener">${esc(w.posted_url)}</a></p>` : ""}</div>
        <div class="actionbar"><button class="btn" data-act="back">Back to workshopping</button></div>`;
    } else if (w.status === "skipped") {
      actions = `<div class="note">${esc(w.skip_reason || "Skipped.")}</div><div class="actionbar"><button class="btn" data-act="restore">${w.drafts.length ? "Bring it back" : "Draft tweets for this"}</button></div>`;
    } else {
      actions = `<div class="actionbar">
          <button class="btn primary" data-act="ready" ${picked ? "" : 'disabled title="Pick a draft first"'}>Mark ready to post</button>
          <button class="btn" data-act="more" ${working !== null ? "disabled" : ""}>Draft 2 more</button>
          ${w.status !== "waiting" ? '<button class="btn" data-act="wait">Needs material</button>' : ""}
          <span class="grow"></span>
          <button class="btn" data-act="skip">Skip idea</button>
        </div>`;
    }

    const comments = `<h3>Discussion</h3><div class="comments">${
      w.comments.length
        ? w.comments
            .map((c) => `<div class="comment">${avatar(c.by, true)}<div class="body"><span class="name">${esc(c.by)}</span><span class="when">${shortDate(c.when)}</span><div>${esc(c.text)}</div></div></div>`)
            .join("")
        : '<div class="empty" style="padding:4px 0">No comments yet.</div>'
    }</div>
      <div class="comment-box"><input id="comment-input" placeholder="Leave a note for the team"><button class="btn" data-act="comment">Comment</button></div>`;

    $("detail").innerHTML = `<div class="detail-inner">
      <div class="idea-head">${avatar(i.author, true)} <span>${esc(i.author)} posted in ${where} &middot; ${shortDate(i.when)}</span><span class="grow"></span>${sources}</div>
      <div class="idea-text">${linkify(slackText(i.text))}</div>
      ${link}
      ${note ? `<div class="note">${note}</div>` : ""}
      ${w.drafts.length ? `<h3>Studio's drafts</h3>${w.drafts.map(draftHtml).join("")}` : ""}
      ${w.status === "skipped" ? "" : comments}
      ${actions}
    </div>`;
  }

  function render() {
    renderTabs();
    renderList();
    renderDetail();
  }

  async function move(i, status, msg) {
    i.workshop.status = status;
    tab = status;
    reworkOpen = null;
    render();
    try {
      await save(i);
      toast(msg);
    } catch (e) {
      toast(e.message);
    }
    render();
  }

  async function ask(i, idx, call) {
    working = idx;
    reworkOpen = null;
    renderDetail();
    try {
      await call();
      if (i.workshop.status === "new") i.workshop.status = "workshopping";
      await save(i);
    } catch (e) {
      toast(e.message);
    }
    working = null;
    render();
  }

  document.addEventListener("click", (e) => {
    const tabBtn = e.target.closest("[data-tab]");
    if (tabBtn) {
      tab = tabBtn.dataset.tab;
      const first = ideas().find((i) => i.workshop.status === tab);
      selected = first ? first.id : null;
      reworkOpen = null;
      render();
      return;
    }
    const row = e.target.closest(".idea-row[data-id]");
    if (row) {
      selected = row.dataset.id;
      reworkOpen = null;
      render();
      return;
    }
    const btn = e.target.closest("[data-act]");
    if (!btn || btn.disabled) return;
    const i = idea();
    if (!i) return;
    const w = i.workshop;
    const idx = Number(btn.dataset.i);
    switch (btn.dataset.act) {
      case "pick":
        w.drafts.forEach((d, n) => (d.picked = n === idx ? !d.picked : false));
        if (w.status === "new") w.status = "workshopping";
        render();
        save(i).catch((err) => toast(err.message));
        break;
      case "rework":
        reworkOpen = reworkOpen === idx ? null : idx;
        renderDetail();
        break;
      case "rw": {
        const instruction = btn.dataset.kind === "custom" ? (($("rw-input") || {}).value || "").trim() : REWORKS[btn.dataset.kind];
        if (!instruction) return;
        ask(i, idx, async () => {
          const res = await api("POST", `/api/ideas/${i.id}/rewrite`, { draft_index: idx, instruction });
          w.drafts[idx].versions.push(res.text);
        });
        break;
      }
      case "undo":
        w.drafts[idx].versions.pop();
        renderDetail();
        save(i).catch((err) => toast(err.message));
        break;
      case "more":
        ask(i, -1, async () => {
          const res = await api("POST", `/api/ideas/${i.id}/more`);
          res.drafts.forEach((d) => w.drafts.push({ versions: [d], picked: false }));
          toast(`Studio added ${res.drafts.length} more drafts`);
        });
        break;
      case "comment": {
        const v = $("comment-input").value.trim();
        if (!v) return;
        w.comments.push({ by: me(), when: new Date().toISOString(), text: v });
        render();
        save(i).catch((err) => toast(err.message));
        break;
      }
      case "ready":
        move(i, "ready", "Moved to Ready to post");
        break;
      case "wait":
        move(i, "waiting", "Moved to Needs material");
        break;
      case "skip":
        w.skip_reason = `Skipped by ${me()}.`;
        move(i, "skipped", "Skipped");
        break;
      case "restore":
        if (!w.drafts.length) {
          ask(i, -1, async () => {
            const res = await api("POST", `/api/ideas/${i.id}/more`);
            res.drafts.forEach((d) => w.drafts.push({ versions: [d], picked: false }));
          }).then(() => move(i, "workshopping", "Studio drafted it"));
        } else {
          move(i, "new", "Back in New");
        }
        break;
      case "back":
        move(i, "workshopping", "Back to workshopping");
        break;
      case "copy": {
        const picked = w.drafts.find((d) => d.picked);
        navigator.clipboard.writeText(picked.versions[picked.versions.length - 1]).then(
          () => toast("Copied"),
          () => toast("Couldn't copy; select the text instead"),
        );
        break;
      }
    }
  });

  document.addEventListener("input", (e) => {
    if (e.target.matches("textarea[data-i]")) {
      const i = idea();
      const idx = Number(e.target.dataset.i);
      const d = i.workshop.drafts[idx];
      d.versions[d.versions.length - 1] = e.target.value;
      const c = $("chars-" + idx);
      c.textContent = `${e.target.value.length}/280`;
      c.classList.toggle("over", e.target.value.length > 280);
      saveSoon(i);
    } else if (e.target.id === "me") {
      localStorage.setItem("tweet-workshop-name", e.target.value.trim());
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.id === "posted-url" && e.target.value.trim()) {
      const i = idea();
      i.workshop.posted_url = e.target.value.trim();
      move(i, "posted", "Filed under Posted");
    }
    if (e.key === "Enter" && e.target.id === "comment-input") document.querySelector('[data-act="comment"]').click();
  });

  // Pick up ideas the drafter saved while the window sat in the background.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && working === null && !document.activeElement.matches("textarea, input")) {
      load().catch((err) => toast(err.message));
    }
  });

  $("me").value = localStorage.getItem("tweet-workshop-name") || "";
  load().catch((err) => {
    $("idea-list").innerHTML = `<li class="empty">Couldn't load ideas: ${esc(err.message)}</li>`;
  });
})();
