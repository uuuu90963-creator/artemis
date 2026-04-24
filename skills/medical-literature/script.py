#!/usr/bin/env python3
"""
Medical Literature Skill - 医学文献查找
支持 PMID 精确查找和关键词搜索
"""

import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional


def search_by_pmid(pmid: str) -> Dict[str, Any]:
    """
    通过 PMID 查找文献摘要

    Args:
        pmid: PubMed ID (如 "40845039")
    """
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    params = {
        "db": "pubmed",
        "id": pmid,
        "rettype": "abstract",
        "retmode": "xml"
    }

    url = f"{base_url}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            xml_content = resp.read().decode("utf-8")

        # 解析 XML
        root = ET.fromstring(xml_content)
        article = root.find(".//PubmedArticle")

        if article is None:
            return {"success": False, "error": f"未找到 PMID: {pmid}"}

        # 提取信息
        medline_cit = article.find("MedlineCitation")
        article_node = medline_cit.find("Article") if medline_cit else None

        result = {
            "success": True,
            "pmid": pmid,
            "data": {}
        }

        if article_node is not None:
            # 标题
            title_node = article_node.find("ArticleTitle")
            result["data"]["title"] = title_node.text if title_node is not None else "N/A"

            # 摘要
            abstract_node = article_node.find("Abstract")
            if abstract_node is not None:
                abstract_texts = []
                for ab in abstract_node.findall("AbstractText"):
                    label = ab.get("Label", "")
                    text = ab.text or ""
                    if label:
                        abstract_texts.append(f"[{label}] {text}")
                    else:
                        abstract_texts.append(text)
                result["data"]["abstract"] = "\n".join(abstract_texts)

            # 作者
            author_list = article_node.find("AuthorList")
            if author_list is not None:
                authors = []
                for author in author_list.findall("Author")[:10]:  # 最多10个
                    last_name = author.find("LastName")
                    fore_name = author.find("ForeName")
                    if last_name is not None:
                        name = f"{last_name.text}"
                        if fore_name is not None:
                            name += f" {fore_name.text}"
                        authors.append(name)
                result["data"]["authors"] = authors
                result["data"]["author_count"] = len(author_list.findall("Author"))

            # 期刊
            journal_node = article_node.find("Journal")
            if journal_node is not None:
                title_j = journal_node.find("Title")
                iso_j = journal_node.find("ISOAbbreviation")
                result["data"]["journal"] = title_j.text if title_j is not None else (iso_j.text if iso_j is not None else "N/A")

                # 年份
                pub_date = journal_node.find("JournalIssue/pubDate")
                if pub_date is not None:
                    year = pub_date.find("Year")
                    result["data"]["year"] = year.text if year is not None else "N/A"

        # PMID 和 DOI
        pubmed_db = article.find("PubmedData")
        if pubmed_db is not None:
            article_id_list = pubmed_db.find("ArticleIdList")
            if article_id_list is not None:
                for art_id in article_id_list.findall("ArticleId"):
                    if art_id.get("IdType") == "doi":
                        result["data"]["doi"] = art_id.text
                    elif art_id.get("IdType") == "pmc":
                        result["data"]["pmc"] = art_id.text

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}


def search_by_keyword(keyword: str, max_results: int = 5) -> Dict[str, Any]:
    """
    通过关键词搜索 PubMed

    Args:
        keyword: 搜索关键词
        max_results: 最大返回数量
    """
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

    search_params = {
        "db": "pubmed",
        "term": keyword,
        "retmax": max_results,
        "retmode": "json"
    }

    try:
        # 搜索
        search_url = f"{base_url}?{urllib.parse.urlencode(search_params)}"
        with urllib.request.urlopen(search_url, timeout=15) as resp:
            search_result = json.loads(resp.read().decode("utf-8"))

        ids = search_result.get("esearchresult", {}).get("idlist", [])

        if not ids:
            return {"success": True, "results": [], "count": 0}

        # 获取摘要
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "json"
        }
        fetch_url_full = f"{fetch_url}?{urllib.parse.urlencode(fetch_params)}"
        with urllib.request.urlopen(fetch_url_full, timeout=15) as resp:
            summary_result = json.loads(resp.read().decode("utf-8"))

        results = []
        for uid in ids:
            article = summary_result.get("result", {}).get(uid, {})
            if article.get("uid"):
                results.append({
                    "pmid": uid,
                    "title": article.get("title", "N/A"),
                    "source": article.get("source", "N/A"),
                    "pubdate": article.get("pubdate", "N/A"),
                    "authors": [a.get("name", "") for a in article.get("authors", [])[:3]]
                })

        return {"success": True, "results": results, "count": len(results)}

    except Exception as e:
        return {"success": False, "error": str(e)}


def format_citation(result: Dict[str, Any]) -> str:
    """格式化文献引用"""
    if not result.get("success"):
        return f"错误: {result.get('error', '未知错误')}"

    data = result.get("data", {})
    parts = []

    # 作者
    authors = data.get("authors", [])
    if authors:
        if len(authors) > 3:
            parts.append(f"{', '.join(authors[:3])} et al.")
        else:
            parts.append(", ".join(authors))

    # 年份
    year = data.get("year", "N/A")
    if year != "N/A":
        parts.append(f"({year})")

    # 标题
    title = data.get("title", "N/A")
    if title != "N/A":
        parts.append(f"{title}.")

    # 期刊
    journal = data.get("journal", "N/A")
    if journal != "N/A":
        parts.append(f"{journal}")

    # PMID
    pmid = result.get("pmid", "")
    if pmid:
        parts.append(f"PMID: {pmid}")

    # DOI
    doi = data.get("doi", "")
    if doi:
        parts.append(f"DOI: {doi}")

    return " ".join(parts)


def execute(task: str = "search", **kwargs) -> Dict[str, Any]:
    """
    技能执行入口

    Args:
        task: 任务类型 ("search_by_pmid" | "search_by_keyword")
        **kwargs: 任务参数
    """
    if task == "search_by_pmid":
        result = search_by_pmid(kwargs.get("pmid", ""))
        result["citation"] = format_citation(result)
        return result
    elif task == "search_by_keyword":
        return search_by_keyword(kwargs.get("keyword", ""), kwargs.get("max_results", 5))
    else:
        return {"success": False, "error": f"未知任务: {task}"}
