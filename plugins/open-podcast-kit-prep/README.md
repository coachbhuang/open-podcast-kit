# Open Podcast Kit Interview Prep

Prepare better interview podcasts with Claude. This plugin helps you research a guest, write a personalized question card, and draft invitation and follow-up messages. It comes from a real Chinese-language career interview podcast, and its rules were shaped by dozens of rounds of a host rewriting AI drafts.

**Language:** the instructions, question bank and sample wording are Chinese-first. Claude can still answer in another language if you ask.

## What's inside

| Skill | Try saying | What you get |
|---|---|---|
| `guest-research` | "Research this guest" / "研究一下这位嘉宾" | A sourced guest brief, including stories already told in past interviews and angles worth exploring |
| `interview-prep` | "Write a prep card for this guest" / "给这位嘉宾出一份访谈手卡" | A host card with guest brief, jargon list, opening options, segmented questions, a pre-interview message and a clean question sheet for the guest |
| `guest-outreach` | "Invite this person onto my show" / "帮我邀请这位嘉宾" | Ready-to-copy invitation and follow-up messages, plus a follow-up log |

## How to use it

1. Tell Claude about your show: name, host, audience, interview length, and what guests get from appearing. Claude saves this as `show-profile.md` in your working folder when it has file access.
2. Share a guest's résumé or public profile.
3. Ask for research, a prep card, or an outreach message.

## What it reads, writes and connects to

- **No programs:** this plugin contains only instructions and reference text. It installs nothing and runs no scripts.
- **Your files:** when Claude has file access, it reads the material you provide and writes drafts under `guests/<name>/` and `show-profile.md` in your working folder.
- **Claude:** résumés, cards and conversations are handled under your Claude account settings.
- **Web research:** when Claude has web tools, `guest-research` searches for the guest's public information. Search terms may include the guest's name and company.
- **Optional transcript tool:** the third-party tool named in Credits is not included. Claude must ask before you install or use it, and the tool's own documentation explains what it connects to.
- **Messages:** outreach and pre-interview messages are drafts only. You always send them yourself.

## Want the full toolkit?

The [open-podcast-kit repository](https://github.com/coachbhuang/open-podcast-kit) also has an automatic prep-card checker, a local web editor, loudness correction and final-cut QC. Those tools are programs, so they are not part of this plugin.

## 中文说明

这是一个给访谈类播客用的 Claude 插件，帮你做嘉宾调研、出个性化访谈手卡、写邀约和跟进消息。它只包含文字说明和参考资料，不安装也不运行任何程序。消息只出草稿，发送永远由你本人完成。自动检查、网页编辑器、响度校正和成片检查在[完整版项目](https://github.com/coachbhuang/open-podcast-kit)里。

## Credits

The optional transcript tool suggested for guest research, [podcast-transcript-txt-skill](https://github.com/KingJing1/podcast-transcript-txt-skill), is by @一龙小包子 (MIT).

## License

[MIT](LICENSE)
