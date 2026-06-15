# Claude Code Plugin 更新指南

## 概述

Claude Code 的 Plugin（插件）系统允许用户安装第三方 Skill 集合来扩展 Claude 的能力。本文档说明如何查看、更新和管理通过插件安装的 Skill。

---

## 基本概念

| 概念 | 说明 |
|------|------|
| **Plugin** | 插件，一个包含多个 Skill 的发布包（通常来自 npm 或 GitHub） |
| **Skill** | 技能，单个 `.md` 文件，定义 Claude 在特定任务中的行为 |
| **Namespace** | 命名空间，插件名作为前缀，如 `superpowers:debugging` |

Skill 文件存放路径：`~/.claude/skills/<plugin-name>/`

---

## 查看已安装插件

```bash
# 列出所有已安装插件
claude plugins list

# 查看 skill 文件目录
ls ~/.claude/skills/
```

---

## 更新插件

### 方式一：使用 CLI 命令（推荐）

```bash
# 更新指定插件
claude plugins update <plugin-name>

# 更新所有已安装插件
claude plugins update
```

### 方式二：重新安装（保证最新版本）

适用于 CLI update 命令无效、插件版本不对，或来自 GitHub 的插件。

```bash
# 第一步：移除旧版本
claude plugins remove <plugin-name>

# 第二步：重新安装
claude plugins install <plugin-url-or-name>
```

### 方式三：指定版本安装（npm 来源）

```bash
# 安装指定版本
claude plugins install @org/plugin-name@1.2.0

# 安装最新版本
claude plugins install @org/plugin-name@latest
```

---

## 常见插件来源及更新方式

### npm 包

```bash
# 查看当前版本
claude plugins list

# 更新到最新
claude plugins update @org/plugin-name

# 或强制重装
claude plugins remove @org/plugin-name
claude plugins install @org/plugin-name@latest
```

### GitHub 仓库

```bash
# 通过 URL 安装（自动拉取最新 main 分支）
claude plugins install https://github.com/owner/repo

# 更新：重新安装即可（GitHub URL 不缓存版本）
claude plugins remove repo
claude plugins install https://github.com/owner/repo
```

---

## 验证更新结果

更新后，在新会话中确认 Skill 已生效：

```bash
# 查看 skill 文件的修改时间
ls -la ~/.claude/skills/<plugin-name>/

# 查看具体 skill 内容
cat ~/.claude/skills/<plugin-name>/SKILL.md
```

在 Claude Code 对话中，通过 Skill 工具调用对应 skill，观察行为是否与新版本一致。

---

## 故障排除

### 问题：更新后 Skill 行为没有变化

1. 确认新会话已启动（旧会话可能缓存了旧版 skill）
2. 检查文件时间戳确认文件已更新
3. 尝试重新安装插件

### 问题：`claude plugins update` 报错

```bash
# 查看详细错误日志
claude plugins update <plugin-name> --verbose

# 如果是权限问题
sudo claude plugins update <plugin-name>
```

### 问题：不知道插件名称

```bash
# 列出所有插件及其来源
claude plugins list --verbose

# 直接查看 skill 目录名
ls ~/.claude/skills/
```

---

## 参考

- Claude Code 官方文档：https://docs.anthropic.com/claude-code
- 插件问题反馈：https://github.com/anthropics/claude-code/issues
