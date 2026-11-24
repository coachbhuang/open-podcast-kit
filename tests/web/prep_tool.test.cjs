const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const T = require("../../docs/prep-tool.js");

const root = path.resolve(__dirname, "../..");
const demo = fs.readFileSync(path.join(root, "examples/demo-guest/prep_v1.md"), "utf8");
const codes = (text, options) => T.checkCard(T.parseCard(text), options).map((item) => item.code);

test("demo card has no required fixes", () => {
  const card = T.parseCard(demo);
  assert.equal(card.segments.length, 5);
  assert.deepEqual(T.checkCard(card).filter((item) => item.level === "fail"), []);
});

test("internal sections and notes never reach the sheet", () => {
  const card = T.parseCard(`# 林一舟 访谈手卡
## 嘉宾速览
1. 这是内部题，不能发吗？
战术备注：要逼具体
## 分段提纲
### #1 开场
1. 自我介绍一下吧。【内部：这里是短视频时刻】
【内部：追到几点下班】
备注：这句不能发
2. 工作累吗？ // 内部：继续追问
一段看不出是什么的主持人笔记
## 录前消息
3. 这也不能发吗？
## 修订记录
4. 这还是不能发吗？`);
  const sheet = T.buildSheet(card).text;
  assert.equal(card.guest, "林一舟");
  assert.equal(card.segments[0].questions.length, 2);
  for (const leaked of ["内部题", "短视频", "几点下班", "这句不能发", "继续追问", "主持人笔记", "这也不能发", "这还是不能发"]) {
    assert.equal(sheet.includes(leaked), false, leaked);
  }
  assert.equal(card.ignored.length, 1);
});

test("common pasted formats are recognized", () => {
  const card = T.parseCard(`第一段：入行
1、你怎么入行的？
   追问：当时几岁？
（2）第一份工作是什么？
Q3: 带我们过一遍一天。
第二部分 薪酬
- 第一年赚多少？
你满意吗？`);
  assert.deepEqual(card.segments.map((s) => s.title), ["入行", "薪酬"]);
  assert.deepEqual(card.segments.map((s) => s.questions.length), [3, 2]);
  assert.equal(card.segments[0].questions[0].followups.length, 1);
});

test("decimal numbers are not mistaken for question numbers", () => {
  const card = T.parseCard("### 数字\n1. 留存提高了 3.5 倍吗？\n3.5 倍是怎么来的？");
  assert.equal(card.segments[0].questions[1].text, "3.5 倍是怎么来的？");
  assert.equal(card.segments[0].questions[1].number, null);
});

test("checks match the prep card rules", () => {
  assert.ok(codes("### 段\n1. 一？二？三？").includes("question-marks"));
  assert.ok(codes("### 段\n1. 一?二?三?").includes("question-marks"));
  assert.ok(codes("### 段\n1. 这个切片怎么做？").includes("leak"));
  assert.ok(codes("### 他们的故事\n1. 你好吗？").includes("third-person-title"));
  assert.ok(codes("### 段\n1. 他为什么走？").includes("third-person"));
  assert.equal(codes("### 段\n1. 这个 webhook 怎么用？").includes("leak"), false);
  assert.ok(codes("### 段\n1. 这个 Hook 怎么写？").includes("leak"));
});

test("optional checks stay off until selected", () => {
  const text = "### 一\n1. 你好吗？\n### 二\n1. 你好吗？\n2. 第一年到手多少？\n3. 还好吗？";
  assert.equal(codes(text).includes("count"), false);
  assert.ok(codes(text, { checkCounts: true }).includes("count"));
  assert.equal(codes(text).includes("money"), false);
  assert.equal(codes(text, { checkMoney: true }).includes("money"), false);
  assert.ok(codes("### 一\n1. 第一年到手多少？", { checkMoney: true }).includes("money"));
});

test("sheet renumbers and can omit follow-ups", () => {
  const card = T.parseCard("### 开场\n3. 〔可选〕你好吗？\n　　追问：真的吗？\n9. 最近忙吗？");
  const withFollowups = T.buildSheet(card, { guest: "林老师" }).text;
  assert.match(withFollowups, /林老师 访谈提纲/);
  assert.match(withFollowups, /☐ 1\. （可选）你好吗？/);
  assert.match(withFollowups, /☐ 2\. 最近忙吗？/);
  assert.match(withFollowups, /追问：真的吗？/);
  assert.equal(T.buildSheet(card, { includeFollowups: false }).text.includes("真的吗"), false);
});

test("real topics that resemble note labels are kept", () => {
  const card = T.parseCard("### 内部创业这件事\n1. 第一节课你学了什么？\n2. 你做过（内部创业）项目吗？\n第一节课后你改变了吗？");
  assert.equal(card.segments[0].title, "内部创业这件事");
  assert.equal(card.segments[0].questions.length, 3);
  assert.match(card.segments[0].questions[1].text, /内部创业/);
  assert.equal(card.internalRemoved, 0);
});
