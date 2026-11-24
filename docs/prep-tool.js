/* Reads a pasted interview outline, checks it, and builds a clean guest sheet.
   Runs only in the browser. Anything it cannot recognize stays out of the sheet. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PrepTool = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const DEFAULT_TACTIC_WORDS = ["短视频时刻", "逼具体", "装傻", "翻译时刻", "切片", "呼吸口", "情绪探针",
    "出口桥", "入口桥", "完播率", "hook", "金句卡", "留扣子", "扣子"];
  const DEFAULT_OPTIONS = {
    maxQuestionMarks: 2,
    maxQuestionLength: 100,
    tacticWords: DEFAULT_TACTIC_WORDS,
    checkCounts: false,
    minPerSegment: 8,
    maxPerSegment: 10,
    checkMoney: false,
    moneySegment: 2,
    moneyWithinFirst: 2,
    moneyPattern: "薪酬|聊钱|多少钱|bonus|收入|到手",
  };

  // Same third-person rule as check_prep_card.py.
  const THIRD_PERSON = /(?<![其])[她他]们?(?![的]?[人们])/;
  const INTERNAL_SECTION = /^(?:嘉宾速览|行业黑话速查|行业黑话|黑话速查|开场白|录前消息|题目角度标签|角度标签|修订记录|内部备注|内部|战术备注|战术|主持人备注|回拉句)(?:[\s（(：:].*)?$/;
  const OUTLINE_SECTION = /分段提纲|访谈提纲|嘉宾题单|^提纲$|^题单$/;
  const PLAIN_INTERNAL_HEADING = /^[【\[〔(（]?\s*(?:内部备注|主持人备注|战术备注|嘉宾速览|行业黑话速查|黑话速查|录前消息|修订记录|题目角度标签)\s*[】\]〕)）]?\s*[:：]?\s*$/;
  const INTERNAL_LINE = /^[-*•·]?\s*(?:[【\[〔]\s*(?:内部|备注|主持人备注|战术)|[（(]\s*(?:内部备注|内部|备注|主持人备注|战术备注|战术)\s*[:：）)]|(?:内部备注|内部|备注|注|主持人备注|主持人注|战术备注|战术|回拉句|回拉|note|tactic)\s*[:：])/i;
  const INLINE_INTERNAL = /[【\[〔]\s*(?:内部|备注|主持人备注|战术)[^】\]〕]*[】\]〕]|[（(]\s*(?:内部备注|内部|备注|主持人备注|战术备注|战术)\s*(?:[:：][^）)]*)?[）)]/g;
  const TRAILING_INTERNAL = /\s*(?:\/\/|——|--)\s*(?:内部|备注|战术)\s*[:：].*$/;
  const MD_HEADING = /^(#{1,6})\s+(.+?)\s*#*$/;
  const HASH_SEGMENT = /^#(\d+)\s*(.*)$/;
  const CN_SEGMENT = /^(第[一二三四五六七八九十\d]+(?:段|部分|节|章|幕))[\s：:、.．-]*(.*)$/;
  const PART_SEGMENT = /^part\s*\d+[\s:：.．-]*(.*)$/i;
  const CN_NUM_SEGMENT = /^[一二三四五六七八九十]+[、．.]\s*(.+)$/;
  const BOLD_LINE = /^\*\*([^*]+)\*\*[:：]?$/;
  const FOLLOWUP = /^[-*•·↳→]?\s*\*?(?:followup|follow-up|follow up|追问|跟进)\s*(（可选）|\(可选\))?\s*[:：]\*?\s*(.+)$/i;
  const NUMBERED = /^(?:\*\*)?(?:[Qq]|问题?\s*)?(\d{1,3})(?:\*\*)?\s*(?:[.．](?!\d)|[、:：）)])\s*(?:\*\*)?\s*(.+)$/;
  const PAREN_NUMBERED = /^[（(](\d{1,3})[）)]\s*(.+)$/;
  const BULLET = /^[-*•·]\s+(.+)$/;
  const OPTIONAL_PREFIX = /^[〔【\[（(]\s*可选\s*[〕】\]）)]\s*/;
  const CN_DIGITS = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"];

  const stripMarkdown = (s) => s.replace(/\*\*/g, "").replace(/(^|\s)\*(\S[^*]*)\*/g, "$1$2").trim();
  const cleanInline = (s) => s.replace(INLINE_INTERNAL, "").replace(TRAILING_INTERNAL, "");
  const countMarks = (s) => (s.match(/[？?]/g) || []).length;

  function parseOptional(text) {
    const optional = OPTIONAL_PREFIX.test(text);
    return { text: stripMarkdown(text.replace(OPTIONAL_PREFIX, "")), optional };
  }

  function readHeading(line) {
    const md = line.match(MD_HEADING);
    if (md) return { level: md[1].length, title: stripMarkdown(md[2].replace(/^#\d+\s*/, "")) };
    const hash = line.match(HASH_SEGMENT);
    if (hash) return { level: 3, title: stripMarkdown(hash[2]) };
    if (countMarks(line) > 0) return null;
    const cn = line.match(CN_SEGMENT);
    if (cn) return { level: 0, title: stripMarkdown(cn[2] || cn[1]) };
    const part = line.match(PART_SEGMENT);
    if (part) return { level: 0, title: stripMarkdown(part[1] || line) };
    const cnNum = line.match(CN_NUM_SEGMENT);
    if (cnNum && countMarks(cnNum[1]) === 0) return { level: 0, title: stripMarkdown(cnNum[1]) };
    const bold = line.match(BOLD_LINE);
    if (bold && countMarks(bold[1]) === 0) return { level: 0, title: stripMarkdown(bold[1]) };
    return null;
  }

  function parseCard(input) {
    const lines = String(input || "").replace(/^﻿/, "").replace(/[​-‍⁠]/g, "")
      .replace(/\r\n?/g, "\n").split("\n");
    const card = { guest: "", segments: [], ignored: [], internalRemoved: 0 };
    let segment = null;
    let question = null;
    let skipLevel = null;

    const openSegment = (title, lineNo) => {
      segment = { title, line: lineNo, questions: [] };
      card.segments.push(segment);
      question = null;
    };
    const addQuestion = (raw, lineNo, number) => {
      if (!segment) openSegment("", lineNo);
      const parsed = parseOptional(raw);
      question = { number, text: parsed.text, optional: parsed.optional, line: lineNo, followups: [] };
      segment.questions.push(question);
    };
    const addFollowup = (raw, optional, lineNo) => {
      const parsed = parseOptional(raw);
      question.followups.push({ text: parsed.text, optional: optional || parsed.optional, line: lineNo });
    };

    lines.forEach((rawLine, index) => {
      const lineNo = index + 1;
      const trimmed = rawLine.replace(/^[\s　]+|[\s　]+$/g, "");
      if (!trimmed) return;

      const heading = readHeading(trimmed);
      if (heading) {
        if (skipLevel !== null) {
          const ends = heading.level > 0 ? heading.level <= skipLevel : skipLevel === 7;
          if (!ends) { card.internalRemoved += 1; return; }
          skipLevel = null;
        }
        if (heading.level === 1) {
          const named = heading.title.match(/^(.+?)\s*(?:访谈手卡|访谈提纲|手卡|提纲)/);
          if (named) card.guest = named[1].trim();
          question = null;
          if (INTERNAL_SECTION.test(heading.title) && !named) skipLevel = 1;
          return;
        }
        if (heading.level > 0 && OUTLINE_SECTION.test(heading.title)) { segment = null; question = null; return; }
        if (INTERNAL_SECTION.test(heading.title)) {
          skipLevel = heading.level > 0 ? heading.level : 7;
          question = null;
          card.internalRemoved += 1;
          return;
        }
        openSegment(heading.title, lineNo);
        return;
      }

      if (skipLevel !== null) { card.internalRemoved += 1; return; }
      if (PLAIN_INTERNAL_HEADING.test(trimmed)) {
        skipLevel = 7;
        question = null;
        card.internalRemoved += 1;
        return;
      }
      if (INTERNAL_LINE.test(trimmed)) { card.internalRemoved += 1; return; }

      const cleaned = cleanInline(trimmed).trim();
      if (cleaned !== trimmed) card.internalRemoved += 1;
      if (!cleaned) return;

      const followup = cleaned.match(FOLLOWUP);
      if (followup) {
        if (question) addFollowup(followup[2], Boolean(followup[1]), lineNo);
        else card.ignored.push({ line: lineNo, text: cleaned, reason: "追问前面没有题目" });
        return;
      }

      const indented = /^[\s　]{2,}|^\t/.test(rawLine);
      const numbered = cleaned.match(NUMBERED) || cleaned.match(PAREN_NUMBERED);
      if (numbered && !indented) { addQuestion(numbered[2], lineNo, Number(numbered[1])); return; }
      if (indented && question && (countMarks(cleaned) > 0 || BULLET.test(cleaned))) {
        const bullet = cleaned.match(BULLET);
        addFollowup(bullet ? bullet[1] : cleaned, false, lineNo);
        return;
      }
      const bullet = cleaned.match(BULLET);
      if (bullet && !indented) { addQuestion(bullet[1], lineNo, null); return; }
      if (/[？?]\s*$/.test(cleaned)) { addQuestion(cleaned, lineNo, null); return; }
      card.ignored.push({ line: lineNo, text: cleaned, reason: "看不出是题目" });
    });

    card.segments = card.segments.filter((s) => s.questions.length > 0 || s.title);
    return card;
  }

  function hasWord(text, word) {
    if (!word) return false;
    if (/^[\x21-\x7e]+$/.test(word)) {
      const escaped = word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      return new RegExp(`(^|[^A-Za-z0-9])${escaped}($|[^A-Za-z0-9])`, "i").test(text);
    }
    return text.includes(word);
  }

  function checkCard(card, userOptions) {
    const options = { ...DEFAULT_OPTIONS, ...(userOptions || {}) };
    const items = [];
    const add = (level, code, where, line, message) => items.push({ level, code, where, line, message });
    const short = (s) => (s.length > 34 ? `${s.slice(0, 34)}…` : s);
    const scanLeaks = (text, where, line) => {
      options.tacticWords.forEach((word) => {
        if (hasWord(text, word)) add("fail", "leak", where, line, `出现内部词「${word}」，嘉宾会看到。请改掉或移到内部备注：${short(text)}`);
      });
    };

    let total = 0;
    card.segments.forEach((segment, si) => {
      const segNo = si + 1;
      if (segment.title) {
        scanLeaks(segment.title, `第 ${segNo} 段标题`, segment.line);
        if (THIRD_PERSON.test(segment.title)) {
          add("fail", "third-person-title", `第 ${segNo} 段标题`, segment.line, `段标题会发给嘉宾，别用第三人称，改成“你”或去掉：${short(segment.title)}`);
        }
      }
      if (options.checkCounts && (segment.questions.length < options.minPerSegment || segment.questions.length > options.maxPerSegment)) {
        add("warn", "count", `第 ${segNo} 段`, segment.line, `这段有 ${segment.questions.length} 道题，第一版建议 ${options.minPerSegment} 到 ${options.maxPerSegment} 道`);
      }
      const numbers = segment.questions.map((q) => q.number).filter((n) => n !== null);
      if (numbers.length && numbers.some((n, i) => n !== i + 1)) {
        add("warn", "numbering", `第 ${segNo} 段`, segment.line, "编号不连续，导出题单时会自动重新编号");
      }
      segment.questions.forEach((q, qi) => {
        total += 1;
        const where = `第 ${segNo} 段第 ${qi + 1} 题`;
        const marks = countMarks(q.text);
        if (marks > options.maxQuestionMarks) {
          add("fail", "question-marks", where, q.line, `一题问了 ${marks} 个问号，嘉宾只记得住最后一个。上限 ${options.maxQuestionMarks} 个，多的拆成追问`);
        }
        scanLeaks(q.text, where, q.line);
        if (THIRD_PERSON.test(q.text)) add("warn", "third-person", where, q.line, `出现第三人称，确认不是在说嘉宾：${short(q.text)}`);
        if ((q.text.match(/“/g) || []).length >= 2) add("warn", "quotes", where, q.line, "装饰性引号偏多，能去就去");
        if (q.text.length > options.maxQuestionLength) {
          add("warn", "too-long", where, q.line, `题面 ${q.text.length} 个字，念出来太长，铺垫尽量压到两句`);
        }
        q.followups.forEach((f) => {
          const fm = countMarks(f.text);
          if (fm > options.maxQuestionMarks) {
            add("fail", "question-marks", `${where}的追问`, f.line, `追问有 ${fm} 个问号，上限 ${options.maxQuestionMarks} 个，再拆一层`);
          }
          scanLeaks(f.text, `${where}的追问`, f.line);
        });
      });
    });

    if (options.checkMoney) {
      const pattern = new RegExp(options.moneyPattern);
      let hit = null;
      card.segments.forEach((segment, si) => segment.questions.forEach((q, qi) => {
        if (!hit && pattern.test(q.text)) hit = { seg: si + 1, q: qi + 1, line: q.line };
      }));
      if (!hit) add("warn", "money", "全卡", 1, "没找到薪酬题，确认是不是嘉宾不愿聊");
      else if (hit.seg !== options.moneySegment || hit.q > options.moneyWithinFirst) {
        add("fail", "money", `第 ${hit.seg} 段第 ${hit.q} 题`, hit.line, `薪酬题建议放在第 ${options.moneySegment} 段前 ${options.moneyWithinFirst} 题`);
      }
    }

    if (total === 0) add("warn", "empty", "全卡", 1, "还没识别到题目。每道题单独一行，前面写编号，或以问号结尾");
    card.ignored.forEach((row) => add("warn", "ignored", `第 ${row.line} 行`, row.line, `${row.reason}，不会进嘉宾题单：${short(row.text)}`));
    const rank = { fail: 0, warn: 1 };
    return items.sort((a, b) => rank[a.level] - rank[b.level] || a.line - b.line);
  }

  const segmentNumber = (i) => (i < CN_DIGITS.length - 1 ? CN_DIGITS[i + 1] : String(i + 1));

  function buildSheet(card, sheetOptions) {
    const options = { guest: "", includeFollowups: true, ...(sheetOptions || {}) };
    const guest = (options.guest || card.guest || "").trim();
    const title = guest ? `${guest} 访谈提纲` : "访谈提纲";
    const intro = "挑你最想聊的打勾，不想聊的可以跳过，不用提前准备答案。";
    const segments = card.segments.filter((s) => s.questions.length).map((segment, i) => ({
      heading: `${segmentNumber(i)}、${segment.title || `第 ${i + 1} 部分`}`,
      questions: segment.questions.map((q, qi) => ({
        number: qi + 1,
        text: q.text,
        optional: q.optional,
        followups: options.includeFollowups ? q.followups.map((f) => ({ text: f.text, optional: f.optional })) : [],
      })),
    }));
    const out = [title, intro];
    segments.forEach((segment) => {
      out.push("", segment.heading);
      segment.questions.forEach((q) => {
        out.push(`☐ ${q.number}. ${q.optional ? "（可选）" : ""}${q.text}`);
        q.followups.forEach((f) => out.push(`    ${f.optional ? "可选追问" : "追问"}：${f.text}`));
      });
    });
    return { title, intro, segments, text: `${out.join("\n")}\n` };
  }

  return { DEFAULT_OPTIONS, DEFAULT_TACTIC_WORDS, parseCard, checkCard, buildSheet };
});
