#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
指标计算模块
核心功能：
  1. 估值分位数（PE/PB/PS/股息率）
  2. 行业排名
  3. 盈利质量与趋势
  4. 动量与情绪
  5. 综合共振评分
"""
import os
import logging
from typing import Dict, Any, Optional

import pandas as pd
import numpy as np
import duckdb

from config import (
    HISTORY_START, PERCENTILE_WINDOWS, MOMENTUM_WINDOWS,
    DB_PATH, RESONANCE_THRESHOLDS, INDUSTRY_LEVEL
)

logger = logging.getLogger("hunzor.metrics")


# ───────────────────────────────
# 1. DuckDB 工具
# ───────────────────────────────

def get_db_conn() -> duckdb.DuckDBPyConnection:
    """获取数据库连接（自动创建表）"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = duckdb.connect(DB_PATH)
    # 初始化表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily (
            ts_code VARCHAR,
            trade_date VARCHAR,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            vol DOUBLE,
            amount DOUBLE,
            pct_chg DOUBLE,
            PRIMARY KEY (ts_code, trade_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_basic (
            ts_code VARCHAR,
            trade_date VARCHAR,
            pe DOUBLE,
            pe_ttm DOUBLE,
            pb DOUBLE,
            ps DOUBLE,
            dv_ttm DOUBLE,
            total_mv DOUBLE,
            circ_mv DOUBLE,
            turnover_rate DOUBLE,
            PRIMARY KEY (ts_code, trade_date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_info (
            ts_code VARCHAR PRIMARY KEY,
            name VARCHAR,
            industry VARCHAR,
            list_date VARCHAR,
            market VARCHAR
        )
    """)
    return conn


def upsert_df(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame, table: str, key_cols: list):
    """批量写入 DataFrame（先删后插）"""
    if df.empty:
        return
    # 创建临时表
    conn.register("tmp_df", df)
    # 删除已存在记录
    where_clause = " AND ".join([f"t.{c} = tmp.{c}" for c in key_cols])
    conn.execute(f"""
        DELETE FROM {table} t
        WHERE EXISTS (
            SELECT 1 FROM tmp_df tmp
            WHERE {where_clause}
        )
    """)
    # 插入新数据
    conn.execute(f"INSERT INTO {table} SELECT * FROM tmp_df")
    conn.execute("DROP VIEW tmp_df")
    logger.info(f"Upsert {table}: {len(df)} rows")


# ───────────────────────────────
# 2. 分位数计算
# ───────────────────────────────

def calculate_percentile(current: float, history: pd.Series) -> Optional[float]:
    """计算当前值在历史序列中的分位数（0-100）"""
    if pd.isna(current) or history.empty:
        return None
    hist = history.dropna()
    if hist.empty:
        return None
    # 使用排名法，避免极端值影响
    return (hist <= current).mean() * 100


def get_valuation_percentiles(conn: duckdb.DuckDBPyConnection, ts_code: str, trade_date: str) -> Dict[str, Any]:
    """
    获取某只股票的估值分位数
    返回：{"pe": {"3y": 25.0, "5y": 30.0, ...}, "pb": {...}, ...}
    """
    result = {}
    
    for metric in ["pe", "pe_ttm", "pb", "ps", "dv_ttm"]:
        result[metric] = {}
        # 拉取历史数据
        df = conn.execute(f"""
            SELECT trade_date, {metric} 
            FROM daily_basic 
            WHERE ts_code = '{ts_code}' AND {metric} IS NOT NULL
            ORDER BY trade_date
        """).df()
        
        if df.empty:
            continue
        
        current = df[df["trade_date"] == trade_date][metric].values
        if len(current) == 0:
            # 取最新
            current = df[metric].iloc[-1]
        else:
            current = current[0]
        
        series = df[metric]
        
        for window_name, window_size in PERCENTILE_WINDOWS.items():
            hist = series.tail(window_size)
            pct = calculate_percentile(current, hist)
            result[metric][window_name] = round(pct, 2) if pct is not None else None
        
        # 同时记录当前值
        result[metric]["current"] = round(current, 2) if pd.notna(current) else None
    
    return result


# ───────────────────────────────
# 3. 行业排名
# ───────────────────────────────

def get_industry_rank(conn: duckdb.DuckDBPyConnection, ts_code: str, trade_date: str) -> Dict[str, Any]:
    """
    获取股票在同行业中的排名
    返回：{"pe_ttm_rank": 15, "pe_ttm_total": 120, "pb_rank": ...}
    """
    result = {}
    
    # 获取行业
    info = conn.execute(f"SELECT industry FROM stock_info WHERE ts_code = '{ts_code}'").df()
    if info.empty or pd.isna(info["industry"].iloc[0]):
        return result
    
    industry = info["industry"].iloc[0]
    
    # 获取同行业所有股票当日数据
    df = conn.execute(f"""
        SELECT d.ts_code, d.pe_ttm, d.pb, d.ps, d.dv_ttm, d.total_mv
        FROM daily_basic d
        JOIN stock_info s ON d.ts_code = s.ts_code
        WHERE s.industry = '{industry}' 
          AND d.trade_date = '{trade_date}'
          AND d.pe_ttm IS NOT NULL
    """).df()
    
    if df.empty:
        return result
    
    total = len(df)
    
    # PE 排名（从高到低，值越小排名越后）
    for metric in ["pe_ttm", "pb", "ps", "total_mv"]:
        if metric not in df.columns or df[metric].isna().all():
            continue
        
        val_df = df[["ts_code", metric]].dropna()
        val_df = val_df.sort_values(metric, ascending=True).reset_index(drop=True)
        val_df["rank"] = val_df.index + 1
        
        row = val_df[val_df["ts_code"] == ts_code]
        if not row.empty:
            rank = row["rank"].iloc[0]
            result[f"{metric}_rank"] = int(rank)
            result[f"{metric}_total"] = int(total)
            result[f"{metric}_percentile"] = round((rank / total) * 100, 2)
    
    return result


# ───────────────────────────────
# 4. 动量计算
# ───────────────────────────────

def get_momentum(conn: duckdb.DuckDBPyConnection, ts_code: str, trade_date: str) -> Dict[str, Any]:
    """
    计算动量指标
    返回：{"return_20d": 5.2, "max_drawdown_250d": -15.3, "volatility_20d": ...}
    """
    result = {}
    
    df = conn.execute(f"""
        SELECT trade_date, close
        FROM daily
        WHERE ts_code = '{ts_code}' AND close IS NOT NULL
        ORDER BY trade_date
    """).df()
    
    if df.empty or len(df) < 20:
        return result
    
    closes = df["close"].values
    
    # 各窗口收益率
    for window_name, window in MOMENTUM_WINDOWS.items():
        if len(closes) >= window + 1:
            ret = (closes[-1] - closes[-(window+1)]) / closes[-(window+1)] * 100
            result[f"return_{window_name}"] = round(ret, 2)
    
    # 波动率（20日收益率标准差）
    if len(closes) >= 21:
        daily_returns = np.diff(closes[-21:]) / closes[-21:-1]
        vol = daily_returns.std() * np.sqrt(252) * 100  # 年化
        result["volatility_annual"] = round(vol, 2)
    
    # 250日最大回撤
    if len(closes) >= 250:
        rolling_max = np.maximum.accumulate(closes[-250:])
        drawdowns = (closes[-250:] - rolling_max) / rolling_max * 100
        result["max_drawdown_250d"] = round(drawdowns.min(), 2)
    
    return result


# ───────────────────────────────
# 5. 盈利趋势（简化版）
# ───────────────────────────────

def get_profit_trend(conn: duckdb.DuckDBPyConnection, ts_code: str) -> Dict[str, Any]:
    """
    基于日行情数据估算盈利趋势（简化）
    完整版需要财务季报，这里用价格趋势作为代理
    """
    result = {}
    
    df = conn.execute(f"""
        SELECT trade_date, close, amount
        FROM daily
        WHERE ts_code = '{ts_code}' 
          AND trade_date >= '{(pd.Timestamp.now() - pd.Timedelta(days=365)).strftime("%Y%m%d")}'
          AND close IS NOT NULL
        ORDER BY trade_date
    """).df()
    
    if len(df) < 60:
        return result
    
    # 60 日 vs 120 日均价趋势
    closes = df["close"]
    ma60 = closes.tail(60).mean()
    ma120 = closes.tail(120).mean()
    
    if pd.notna(ma60) and pd.notna(ma120) and ma120 > 0:
        trend = (ma60 - ma120) / ma120 * 100
        result["price_trend_ma"] = round(trend, 2)
        result["trend_direction"] = "up" if trend > 2 else "down" if trend < -2 else "flat"
    
    # 量价关系（近20日）
    if len(df) >= 20:
        recent = df.tail(20)
        price_change = (recent["close"].iloc[-1] - recent["close"].iloc[0]) / recent["close"].iloc[0]
        vol_change = (recent["amount"].iloc[-1] - recent["amount"].iloc[0]) / (recent["amount"].iloc[0] + 1)
        result["price_vol_divergence"] = round(price_change - vol_change, 4)
    
    return result


# ───────────────────────────────
# 6. 综合共振评分
# ───────────────────────────────

def calculate_resonance(val_pct: Dict[str, Any], industry_rank: Dict[str, Any], 
                        momentum: Dict[str, Any], profit: Dict[str, Any]) -> Dict[str, Any]:
    """
    综合共振评分（0-1）
    
    维度1：估值（权重 40%）
      - PE 分位 < 30% → 满分
      - 30-50% → 中等
      - > 50% → 低分
      
    维度2：行业相对（权重 20%）
      - 行业 PE 排名 < 30% → 满分（行业中最便宜）
      
    维度3：盈利趋势（权重 20%）
      - price_trend_ma > 0 且趋势向上 → 满分
      
    维度4：动量（权重 20%）
      - 20日收益为正但不过热（<15%）→ 中等
      - 波动率适中 → 加分
    """
    scores = {"valuation": 0.5, "industry": 0.5, "profit": 0.5, "momentum": 0.5}
    
    # 估值评分
    pe_5y = val_pct.get("pe_ttm", {}).get("5y", 50)
    if pe_5y is not None:
        if pe_5y < 20:
            scores["valuation"] = 1.0
        elif pe_5y < 30:
            scores["valuation"] = 0.8
        elif pe_5y < 50:
            scores["valuation"] = 0.5
        elif pe_5y < 70:
            scores["valuation"] = 0.3
        else:
            scores["valuation"] = 0.0
    
    # 行业评分
    pe_rank_pct = industry_rank.get("pe_ttm_percentile", 50)
    if pe_rank_pct is not None:
        # 排名越低（越便宜）越好
        scores["industry"] = max(0, 1 - pe_rank_pct / 100)
    
    # 盈利趋势
    trend_dir = profit.get("trend_direction", "flat")
    if trend_dir == "up":
        scores["profit"] = 0.8
    elif trend_dir == "down":
        scores["profit"] = 0.2
    else:
        scores["profit"] = 0.5
    
    # 动量
    ret_20d = momentum.get("return_20d", 0)
    if ret_20d is not None:
        if -5 <= ret_20d <= 10:
            scores["momentum"] = 0.7  # 温和上涨，最理想
        elif ret_20d > 10:
            scores["momentum"] = 0.4  # 过热
        elif ret_20d > -10:
            scores["momentum"] = 0.5
        else:
            scores["momentum"] = 0.2
    
    # 加权总分
    weights = {"valuation": 0.4, "industry": 0.2, "profit": 0.2, "momentum": 0.2}
    total_score = sum(scores[k] * weights[k] for k in weights)
    
    # 共振等级
    if total_score >= RESONANCE_THRESHOLDS["strong"]:
        level = "strong"
        label = "🟢 强共振"
    elif total_score >= RESONANCE_THRESHOLDS["medium"]:
        level = "medium"
        label = "🟡 中共振"
    else:
        level = "weak"
        label = "🔴 弱共振"
    
    return {
        "score": round(total_score, 3),
        "level": level,
        "label": label,
        "dimensions": scores,
    }


# ───────────────────────────────
# 7. 单股诊断（汇总）
# ───────────────────────────────

def diagnose_stock(conn: duckdb.DuckDBPyConnection, ts_code: str, trade_date: str) -> Dict[str, Any]:
    """
    对单只股票做完整诊断，返回前端可用 JSON 结构
    """
    # 基础信息
    info = conn.execute(f"""
        SELECT name, industry, market 
        FROM stock_info 
        WHERE ts_code = '{ts_code}'
    """).df()
    
    name = info["name"].iloc[0] if not info.empty else ts_code
    industry = info["industry"].iloc[0] if not info.empty else ""
    market = info["market"].iloc[0] if not info.empty else ""
    
    # 当日行情
    daily = conn.execute(f"""
        SELECT close, pct_chg, vol, amount, open, high, low
        FROM daily
        WHERE ts_code = '{ts_code}' AND trade_date = '{trade_date}'
    """).df()
    
    # 估值
    val_pct = get_valuation_percentiles(conn, ts_code, trade_date)
    
    # 行业排名
    industry_rank = get_industry_rank(conn, ts_code, trade_date)
    
    # 动量
    momentum = get_momentum(conn, ts_code, trade_date)
    
    # 盈利趋势
    profit = get_profit_trend(conn, ts_code)
    
    # 共振评分
    resonance = calculate_resonance(val_pct, industry_rank, momentum, profit)
    
    # 组装结果
    result = {
        "code": ts_code,
        "name": name,
        "industry": industry,
        "market": market,
        "trade_date": trade_date,
        "price": {
            "close": round(daily["close"].iloc[0], 2) if not daily.empty else None,
            "change_pct": round(daily["pct_chg"].iloc[0], 2) if not daily.empty else None,
            "volume": int(daily["vol"].iloc[0]) if not daily.empty else None,
            "amount": round(daily["amount"].iloc[0], 2) if not daily.empty else None,
        },
        "valuation": val_pct,
        "industry_rank": industry_rank,
        "momentum": momentum,
        "profit_trend": profit,
        "resonance": resonance,
        "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    return result
