# Medical Literature Skill - 医学文献技能

## 触发条件

当用户提到以下关键词时自动触发：
- "文献"、"论文"、"研究"
- "PubMed"、"PMID"
- "临床试验"、"meta分析"、"系统综述"
- "查一下这篇文章"、"帮我找相关研究"

## 功能

1. **PMID 精确查找** - 通过 PubMed ID 获取文献摘要
2. **关键词搜索** - 搜索相关医学文献
3. **PDF 下载** - 获取全文 PDF（开放获取）
4. **文献整理** - 格式化输出文献信息

## 使用方法

```python
from skills.load_skill import SkillLoader
loader = SkillLoader(skills_dir)

# 加载技能
skill = loader.load_skill("medical-literature")

# 执行 PMID 查找
result = loader.execute_skill_script("medical-literature", "search_by_pmid", pmid="40845039")
```

## 数据来源

- PubMed API (NCBI)
- DOI 解析
- Open Access PDF 源

## 注意事项

- 医学文献信息可能涉及患者隐私，仅用于学术研究
- PDF 下载仅支持开放获取文献
- 商业文献需通过正规渠道获取
