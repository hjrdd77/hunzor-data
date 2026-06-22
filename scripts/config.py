#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hunzor-data 配置
用户需要在此填入自己的 Tushare token（免费注册）
如果不用 Tushare，可完全依赖 AKShare（零配置）
"""
import os

# === 数据接口配置 ===
# Tushare token：免费注册获取 https://tushare.pro/register
# 设为 None 则完全使用 AKShare（推荐新手）
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", None)

# === 计算参数 ===
# 历史数据起始日期（用于计算分位数）
HISTORY_START = "20150101"

# 行业分类：申万一级/二级/三级
INDUSTRY_LEVEL = 3  # 1=一级, 2=二级, 3=三级

# 分位计算窗口（交易日）
PERCENTILE_WINDOWS = {
    "3y": 750,   # 约 3 年
    "5y": 1250,  # 约 5 年
    "10y": 2500, # 约 10 年
}

# 动量计算窗口（自然日）
MOMENTUM_WINDOWS = {
    "20d": 20,
    "60d": 60,
    "120d": 120,
    "250d": 250,
}

# === 输出配置 ===
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DB_PATH = os.path.join(DATA_DIR, "db", "hunzor.db")
STOCKS_DIR = os.path.join(DATA_DIR, "stocks")
INDICES_DIR = os.path.join(DATA_DIR, "indices")
LATEST_JSON = os.path.join(DATA_DIR, "latest.json")

# === 共振评分阈值 ===
RESONANCE_THRESHOLDS = {
    "strong": 0.7,   # 强共振：>=0.7
    "medium": 0.4,   # 中共振：0.4-0.7
    "weak": 0.0,     # 弱共振：<0.4
}
