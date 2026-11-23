# open-podcast-kit

**给访谈类播客的 AI 工具包：录制前帮你做嘉宾功课、出好问题，剪完后帮你检查成片。**

[English](README.en.md)

这套工具来自一档真实在更新的中文职业访谈视频播客。它不是从零设想出来的：手卡上的每一条规则，都是 AI 出稿、主持人亲手改了几十轮之后，把"主持人每次都要改的地方"收成的标准。

它以 [Claude Code](https://claude.com/claude-code) 的 skill 形式运行：装好之后，你用自然语言说"帮我准备一下这位嘉宾的采访"，Claude 就会按这套流程做。

![网页版手卡编辑器：逐题改写、删除、调顺序，保存时自动检查](docs/editor.png)

## 30 秒试一下

不用装 Claude Code，只要 Python 3.9 或更新版本，Mac 上装过 git 就已经有了。下面用仓库自带的虚构嘉宾：

```bash
git clone https://github.com/coachbhuang/open-podcast-kit.git
cd open-podcast-kit
python3 skills/interview-prep/scripts/check_prep_card.py examples/demo-guest/prep_v1.md --config kit.example.toml
python3 skills/interview-prep/scripts/prep_card_serve.py demo-guest --guests examples --config kit.example.toml --open
```

第一条检查手卡，第二条打开上图的编辑器。装了 [ffmpeg](https://ffmpeg.org) 的话，再测一下你自己节目的响度：

```bash
python3 skills/normalize-loudness/scripts/loudness.py measure 你的成片.mp4
```

## 里面有什么

### 录制前：访谈准备

| skill | 你说 | 它做 |
|---|---|---|
| `guest-research` | "研究一下这位嘉宾" | 汇总嘉宾公开资料；拉取 Ta 上过的其他播客 / 视频访谈逐字稿，找出已经被问烂的角度和没人追问过的点 |
| `interview-prep` | "给 xx 出一份访谈手卡" | 出个性化手卡：嘉宾速览、行业黑话速查、开场白备选、分段题目、录前消息；机器自查后导出给嘉宾勾选的题单 PDF |
| `guest-outreach` | "帮我邀请 xx 上节目" | 写邀约和跟进消息终稿，维护一张跟进表，到期提醒你跟进 |

手卡的几个特点：

- **题目不干巴巴**：每道题按"织进简历硬数字 / 挑衅前提 / 情绪探针 / 听众视角 / 先破再问"叠两三层。
- **发给嘉宾的部分绝对干净**：题单只取提纲区，内部战术备注（哪里要逼具体、哪里是短视频素材）物理上进不去；机器自查会拦住任何泄漏。
- **有机器自查**：问号数、每段题数、薪酬题位置、第三人称、黑话条数、开场白备选数……交稿前一条命令查完。
- **有节奏母版**：90 分钟五段结构，硬信息和情绪题交替，段与段之间有自然的过渡。
- **网页版编辑器**：不用在文本编辑器里改 markdown。浏览器里逐题删掉、降为可选、改写、批注、加题、上下挪（可跨段）；保存永远存成新版本，删掉的题进文末备查区随时捞回，存完自动跑一遍自查。

  ```bash
  python3 skills/interview-prep/scripts/prep_card_serve.py --open
  ```

### 剪完后：成片检查

| skill | 你说 | 它做 |
|---|---|---|
| `normalize-loudness` | "这期声音好小" / "上传前查一下音频" | 测响度、真峰值和底噪；不达标就用"固定增益 + 限制器"校正（不会让声音忽大忽小），视频画面不重压；分段检查拼接处有没有突然变小声 |
| `review-cut` | "帮我审一下成片" | 查规格、字幕乱序与缺失、响度、长静音；按 30 秒网格和每个剪辑点抽帧拼成大图，Claude 逐张看有没有黑屏、贴错的画面、字幕和说话人对不上 |

## 快速开始

需要：[Claude Code](https://claude.com/claude-code)、Python 3.9 或更新版本、[ffmpeg](https://ffmpeg.org)（审片和响度工具用）。导出题单 PDF 可选装 Playwright。

**1. 安装**

在 Claude Code 里：

```
/plugin install open-podcast-kit --marketplace coachbhuang/open-podcast-kit
```

Claude Code 版本较旧时分两步：先 `/plugin marketplace add coachbhuang/open-podcast-kit`，再 `/plugin install open-podcast-kit`。

或者把 `skills/` 下的文件夹复制到你播客工作目录的 `.claude/skills/` 里。

**2. 填你的节目档案**

把 `kit.example.toml` 复制到你的播客工作目录，改名 `kit.toml`，填上节目名、主持人、受众、开场白、嘉宾权益和内容红线。所有工具都从这里读，别处不用改。

**3. 开始用**

把嘉宾简历丢给 Claude，说："帮我准备一下这位嘉宾的访谈手卡。"

想先看效果：`examples/demo-guest/` 里有一位虚构嘉宾的简历和对应的第一版手卡。

## 换成你自己的节目形式

自带的题库是"职业访谈"预设（`presets/career/`）：五段结构，围绕入行、日常、薪酬、求职、未来展开。做别的访谈形式（创业者、学者、读书……）时：

1. 照着 `presets/career/question-bank.md` 写一份你自己的题库；
2. 在 `kit.toml` 里把 `[prep].question_bank` 指向它；
3. 不需要"薪酬题必须在第二段"这条检查的，把 `[prep.money].enabled` 设成 `false`；角度标签清单也可以改。

## 隐私

- 嘉宾资料默认放在工作目录的 `guests/` 下，`.gitignore` 已排除，别提交到公开仓库。
- 所有工具在你自己的电脑上运行，不会把嘉宾资料发到任何第三方（Claude 本身的对话除外）。
- 邀约和录前消息只出草稿，发送永远由你本人完成。

## 致谢

嘉宾调研推荐的逐字稿工具 [podcast-transcript-txt-skill](https://github.com/KingJing1/podcast-transcript-txt-skill) 由 @一龙小包子 开发（MIT 许可）。

## 许可

[MIT](LICENSE)
