# Artemis 技能系统

## 概述

Artemis 采用按需加载的技能系统，每个技能独立目录，支持版本管理和动态加载。

## 目录结构

```
skills/
├── SKILL.md          # 技能元数据
├── scripts/          # 技能脚本
├── references/       # 参考文档
└── templates/        # 模板文件
```

## 技能格式约定

每个技能目录必须包含 `SKILL.md` 文件，格式如下：

```markdown
---
name: skill-name
version: 1.0.0
trigger: ["触发关键词1", "触发关键词2"]
description: 技能描述
dependencies: ["依赖1", "依赖2"]
author: 作者名
created: 2024-01-01
updated: 2024-01-01
---

# 技能名称

## 描述
详细描述技能功能和用途。

## 触发条件
- 包含关键词：XXX
- 任务类型：medical/vision/code 等
- 其他条件：XXX

## 使用方法
1. 步骤一
2. 步骤二

## 依赖
- Python 包：xxx
- 外部工具：xxx

## 示例
```
示例输入和输出
```

## 注意事项
- 注意点1
- 注意点2
```

## 版本管理

- 版本号格式：`MAJOR.MINOR.PATCH`
- 更新时需修改 `updated` 字段
- 保持向后兼容

## 内置技能

### medical-guidelines
- **描述**：医学指南查询技能
- **触发**：医学相关问题
- **功能**：快速查询临床指南、诊疗规范

### image-analysis
- **描述**：医学影像分析
- **触发**：CT/MRI/X线 等关键词
- **功能**：影像解读、异常检测

### code-development
- **描述**：代码开发辅助
- **触发**：代码、程序、开发 等关键词
- **功能**：代码生成、调试、代码审查

## 技能市场

可从以下地址获取更多技能：
- 主市场：https://artemis-skills.market
- 本地目录：~/.hermes/artemis/skills/

## 按需加载

技能在需要时动态加载，不需要预先导入。加载后缓存在内存中，提高后续访问速度。

---

*最后更新：2026-04-23*
