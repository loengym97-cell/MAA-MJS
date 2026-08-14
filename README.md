# 基于 MaaFramework 流水线语言与接口协议的游戏自动化研究项目

以 [MaaFramework](https://github.com/MaaXYZ/MaaFramework)（任务流水线协议 Pipeline Protocol + ProjectInterface 接口协议）为研究框架，以名将杀「千里走单骑」模式为实验对象，研究 JSON 流水线语言描述、图像识别（模板匹配 / OCR）、自定义识别与动作（Agent 协议）等游戏自动化技术。

> 本版由 **loengym97-cell** 在原作者代码基础上适配维护（原作者已停止维护）。**纯免费、仅供学习交流**，有问题请自行求助 AI（详见软件内公告）。

## 免责声明

1. **软件使用**：本程序旨在帮助用户便捷地享受游戏。用户在使用本程序时，应确保其行为符合当地法律法规及网络使用规定。
2. **责任限制**：本程序及其开发者不对任何因使用或无法使用本程序造成的直接、间接、偶然、特殊及衍生的损失承担责任。这包括但不限于数据丢失、利润损失、业务中断或任何其它商业损害，无论这些损害是否基于合同、侵权或其他行为。
3. **安全性声明**：尽管开发者已尽力确保程序的安全性，但无法保证程序完全没有缺陷或漏洞。用户应自行承担使用本程序可能带来的安全风险。

## 使用说明

1. 本应用基于 mumu 模拟器运行（雷电也可以，反馈效果更好，其他模拟器不保证能跑）。
2. 下载最新 Release 中的压缩包并解压，以管理员身份运行 DependencySetup_依赖库安装_win.bat。
3. 打开模拟器手机设置 → 开发者选项 → 开启 ADB 调试 → 进入游戏 → 关闭陌生人邀请；自定义武将必须在选将的第一页。
4. 运行 MFAAvalonia.exe，根据界面提示选择控制器和任务。

## 版本历史

- **v1.3.1** — 回滚 only_rec（恢复 det+rec 完整识别，保障稳定性）；保留 GPU(DirectML) 推理加速
- **v1.3.0** — 项目更名：《基于 MaaFramework 流水线语言与接口协议的游戏自动化研究项目》；文档清理（移除失效视频链接、致谢两位贡献者）
- **v1.2.1** — 版本号同步（interface.json / README）
- **v1.2.0** — OCR 加速：59 个固定按钮节点启用 only_rec（跳过文字检测直接识别）；agent 配置读取缓存；支持 GPU(DirectML) 推理加速（设置→性能，或 config/config.json 的 UseDirectML）
- **v1.1.0** — 社区适配版基线（事件选项补全、兜底点击、托管链修复等）

## 致谢

- 底层框架：[MaaXYZ/MaaFramework](https://github.com/MaaXYZ/MaaFramework)（LGPL-3.0）
- 感谢 [asdfxsxxs/MAAMJS](https://github.com/asdfxsxxs/MAAMJS) 提供整个软件
- 感谢 [2451123316](https://github.com/2451123316/) 提供各种功能
- AI 协助：**DeepSeek** 与 **DeepSeek Harness（DSH）**
