(function () {
  "use strict";
  const T = window.PrepTool;
  const $ = (id) => document.getElementById(id);
  const STORE_KEY = "prep-check-draft-v1";
  const SAMPLE = `# 林一舟 访谈手卡

## 嘉宾速览
- 履历：统计学本科，咨询分析师，现在做增长产品经理
- 战术备注：第 2 段要逼具体，追到第一年到手多少

## 分段提纲
### #1 你是谁，你每天在做什么
1. 先跟听众做个自我介绍吧，从大学学统计讲到现在。
　　追问：能不能用一句大白话解释你现在具体在做什么？
2. 学统计的人大多留在分析岗，你为什么要转产品？当时怕不怕？家里人怎么看？后来后悔过吗？
【内部：这题是短视频时刻，嘉宾一说“拍板”就追问】
3. 带我们过一遍你最近一个普通工作日，从起床到睡觉。

### #2 增长这一行，他们看不到的部分
1. 很多同学最好奇钱。刚入行的产品经理，第一年的薪酬结构大概是什么样的？
2. 新客 7 日留存从 18% 提到 26%，这个切片你们具体是怎么做到的？
3. 〔可选〕你的老板对他这套打法满意吗？

## 录前消息
林老师你好，先跟你确认一下录制时间和称呼。
`;

  let currentSheet = null;
  let currentLeaks = [];
  let timer = null;

  function words() {
    return $("words").value.split(/[,，、\n]/).map((w) => w.trim()).filter(Boolean);
  }

  function options() {
    const marks = Number($("max-marks").value);
    return {
      maxQuestionMarks: Number.isInteger(marks) && marks > 0 ? marks : 2,
      tacticWords: words(),
      checkCounts: $("check-counts").checked,
      checkMoney: $("check-money").checked,
    };
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function jumpToLine(line) {
    const area = $("card");
    const rows = area.value.split("\n");
    const start = rows.slice(0, line - 1).reduce((sum, row) => sum + row.length + 1, 0);
    const end = start + (rows[line - 1] || "").length;
    area.focus();
    area.setSelectionRange(start, end);
    const style = getComputedStyle(area);
    const lineHeight = parseFloat(style.lineHeight) || 24;
    area.scrollTop = Math.max(0, (line - 3) * lineHeight);
    if (window.matchMedia("(max-width: 860px)").matches) area.scrollIntoView({ block: "center" });
  }

  function renderSummary(fails, warns, questionCount, hasText) {
    const box = $("summary");
    box.className = "summary";
    box.replaceChildren();
    if (!hasText) {
      box.classList.add("idle");
      box.append(element("strong", "", "粘贴题目后自动检查"), element("span", "", "没有题目也可以先点“填入示例”看看效果。"));
    } else if (questionCount === 0) {
      box.classList.add("warn");
      box.append(element("strong", "", "还没识别到题目"), element("span", "", "每道题单独一行，前面写编号，或以问号结尾。"));
    } else if (fails > 0) {
      box.classList.add("fail");
      box.append(element("strong", "", `有 ${fails} 处需要改`), element("span", "", warns ? `另有 ${warns} 处建议看一眼。点一条可跳到原文。` : "点一条可跳到原文。"));
    } else if (warns > 0) {
      box.classList.add("warn");
      box.append(element("strong", "", "可以发，建议再看一眼"), element("span", "", `有 ${warns} 处提醒，不改也能导出。`));
    } else {
      box.classList.add("ok");
      box.append(element("strong", "", "可以发给嘉宾了"), element("span", "", "去“嘉宾题单”复制或存成 PDF。"));
    }
  }

  function renderStats(card, questionCount) {
    const followups = card.segments.reduce((sum, s) => sum + s.questions.reduce((n, q) => n + q.followups.length, 0), 0);
    const rows = [["段落", card.segments.filter((s) => s.questions.length).length], ["题目", questionCount], ["追问", followups], ["拦下备注", card.internalRemoved]];
    $("stats").replaceChildren(...rows.map(([label, value]) => {
      const cell = element("div");
      cell.append(element("dt", "", label), element("dd", "", String(value)));
      return cell;
    }));
  }

  function renderFindings(items) {
    $("findings").replaceChildren(...items.map((item) => {
      const li = element("li");
      const button = element("button", `finding ${item.level}`);
      button.type = "button";
      button.append(element("span", "tag", item.level === "fail" ? "要改" : "提醒"), element("span", "where", item.where), element("span", "message", item.message));
      button.addEventListener("click", () => jumpToLine(item.line));
      li.append(button);
      return li;
    }));
  }

  function renderSheet(sheet) {
    const root = $("sheet");
    const nodes = [element("h3", "", sheet.title), element("p", "sheet-intro", sheet.intro)];
    sheet.segments.forEach((segment) => {
      const block = element("section");
      block.append(element("h4", "", segment.heading));
      const list = element("ul");
      segment.questions.forEach((q) => {
        const li = element("li");
        li.append(element("span", "box", "☐"));
        const body = element("div");
        body.append(element("p", "", `${q.number}. ${q.optional ? "（可选）" : ""}${q.text}`));
        q.followups.forEach((f) => body.append(element("p", "followup", `${f.optional ? "可选追问" : "追问"}：${f.text}`)));
        li.append(body);
        list.append(li);
      });
      block.append(list);
      nodes.push(block);
    });
    if (!sheet.segments.length) nodes.push(element("p", "sheet-empty", "题目会显示在这里。"));
    root.replaceChildren(...nodes);
  }

  function updateGate() {
    const blocked = currentLeaks.length > 0 && !$("leak-ok").checked;
    const empty = !currentSheet || !currentSheet.segments.length;
    ["copy", "print", "download"].forEach((id) => { $(id).disabled = blocked || empty; });
    $("sheet").classList.toggle("blocked", blocked);
  }

  function render() {
    const text = $("card").value;
    const card = T.parseCard(text);
    const items = T.checkCard(card, options());
    const fails = items.filter((i) => i.level === "fail").length;
    const warns = items.length - fails;
    const questionCount = card.segments.reduce((sum, s) => sum + s.questions.length, 0);
    const shown = text.trim() ? items : [];
    renderSummary(fails, shown.length - fails, questionCount, Boolean(text.trim()));
    renderStats(card, questionCount);
    renderFindings(shown);

    if (!$("guest").value.trim() && card.guest) $("guest").placeholder = card.guest;
    else if (!card.guest) $("guest").placeholder = "比如：林老师";
    currentSheet = T.buildSheet(card, { guest: $("guest").value, includeFollowups: $("followups").checked });
    renderSheet(currentSheet);

    const leakWords = [...new Set(items.filter((i) => i.code === "leak").map((i) => (i.message.match(/「(.+?)」/) || [])[1]).filter(Boolean))];
    const changed = leakWords.join("|") !== currentLeaks.join("|");
    currentLeaks = leakWords;
    if (changed) $("leak-ok").checked = false;
    $("leak-gate").hidden = leakWords.length === 0;
    $("leak-text").textContent = leakWords.length ? `题单里还有内部词：${leakWords.join("、")}。建议先改掉。` : "";
    updateGate();
    save();
    return warns;
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(render, 120);
  }

  // Session storage survives a refresh and clears when the tab closes.
  function save() {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify({ card: $("card").value, guest: $("guest").value }));
    } catch (error) { /* Private mode can block storage. The tool still works. */ }
  }

  function restore() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null");
      if (saved) {
        $("card").value = saved.card || "";
        $("guest").value = saved.guest || "";
      }
    } catch (error) { /* Start empty if storage is unavailable or damaged. */ }
  }

  function selectTab(name) {
    const isCheck = name === "check";
    $("tab-check").setAttribute("aria-selected", String(isCheck));
    $("tab-sheet").setAttribute("aria-selected", String(!isCheck));
    $("tab-check").tabIndex = isCheck ? 0 : -1;
    $("tab-sheet").tabIndex = isCheck ? -1 : 0;
    $("view-check").hidden = !isCheck;
    $("view-sheet").hidden = isCheck;
  }

  function status(message) {
    $("copy-status").textContent = message;
    clearTimeout(status.timer);
    status.timer = setTimeout(() => { $("copy-status").textContent = ""; }, 2600);
  }

  function fallbackCopy(text) {
    const area = element("textarea", "offscreen");
    area.value = text;
    document.body.append(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (error) { ok = false; }
    area.remove();
    return ok;
  }

  async function copySheet() {
    const text = currentSheet.text;
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch (error) {
      ok = fallbackCopy(text);
    }
    status(ok ? "已复制，可以直接粘贴给嘉宾。" : "复制失败，请用“下载文本”。");
  }

  function downloadSheet() {
    const url = URL.createObjectURL(new Blob([currentSheet.text], { type: "text/plain;charset=utf-8" }));
    const link = element("a");
    link.href = url;
    link.download = `${currentSheet.title.replace(/[\\/:*?"<>|]/g, "")}.txt`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status("已下载。");
  }

  $("words").value = T.DEFAULT_TACTIC_WORDS.join("，");
  restore();
  ["card", "guest", "words", "max-marks"].forEach((id) => $(id).addEventListener("input", schedule));
  ["check-counts", "check-money", "followups"].forEach((id) => $(id).addEventListener("change", render));
  $("leak-ok").addEventListener("change", updateGate);
  $("sample").addEventListener("click", () => {
    $("card").value = SAMPLE;
    $("guest").value = "";
    selectTab("check");
    render();
    $("card").scrollTop = 0;
  });
  $("clear").addEventListener("click", () => {
    $("card").value = "";
    $("guest").value = "";
    selectTab("check");
    render();
    $("card").focus();
  });
  $("tab-check").addEventListener("click", () => selectTab("check"));
  $("tab-sheet").addEventListener("click", () => selectTab("sheet"));
  document.querySelector(".tabs").addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const next = $("tab-check").getAttribute("aria-selected") === "true" ? "sheet" : "check";
    selectTab(next);
    $(`tab-${next}`).focus();
  });
  $("copy").addEventListener("click", copySheet);
  $("download").addEventListener("click", downloadSheet);
  $("print").addEventListener("click", () => window.print());
  // The browser uses the page title as the PDF's file name and print header.
  const pageTitle = document.title;
  window.addEventListener("beforeprint", () => { if (currentSheet) document.title = currentSheet.title; });
  window.addEventListener("afterprint", () => { document.title = pageTitle; });
  render();
})();
