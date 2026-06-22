#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON 导出模块
将计算结果输出为前端可直接消费的 JSON 格式
"""
import os
import json
import logging
from typing import Dict, List, Any

import pandas as pd
import numpy as np
import duckdb

from config import STOCKS_DIR, INDICES_DIR, LATEST_JSON
from metrics import diagnose_stock, get_db_conn

logger = logging.getLogger("hunzor.export")


def ensure_dirs():
    """确保输出目录存在"""
    os.makedirs(STOCKS_DIR, exist_ok=True)
    os.makedirs(INDICES_DIR, exist_ok=True)


def export_stock(conn: duckdb.DuckDBPyConnection, ts_code: str, trade_date: str) -> str:
    """导出单只股票诊断 JSON，返回文件路径"""
    data = diagnose_stock(conn, ts_code, trade_date)
    
    # 同时导出历史数据用于画图
    history = conn.execute(f"""
        SELECT trade_date, close, pe_ttm, pb, ps, dv_ttm
        FROM daily_basic
        WHERE ts_code = '{ts_code}' AND pe_ttm IS NOT NULL
        ORDER BY trade_date
    """).df()
    
    if not history.empty:
        data["history_chart"] = {
            "indicator": "pe_ttm",
            "data": history.tail(250)[["trade_date", "pe_ttm", "close"]].rename(
                columns={"trade_date": "date", "pe_ttm": "value", "close": "index"}
            ).to_dict("records")
        }
    
    path = os.path.join(STOCKS_DIR, f"{ts_code.replace('.', '_')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return path


def export_all_stocks(conn: duckdb.DuckDBPyConnection, trade_date: str, limit: int = None):
    """导出全市场股票诊断"""
    ensure_dirs()
    
    # 获取所有股票
    stocks = conn.execute("SELECT ts_code FROM stock_info").df()
    codes = stocks["ts_code"].tolist()
    
    if limit:
        codes = codes[:limit]
    
    logger.info(f"开始导出 {len(codes)} 只股票...")
    
    exported = 0
    for i, code in enumerate(codes):
        try:
            export_stock(conn, code, trade_date)
            exported += 1
        except Exception as e:
            logger.warning(f"导出 {code} 失败: {e}")
        
        if (i + 1) % 100 == 0:
            logger.info(f"已导出 {i+1}/{len(codes)}")
    
    logger.info(f"导出完成: {exported}/{len(codes)}")
    return exported


def export_latest_summary(conn: duckdb.DuckDBPyConnection, trade_date: str):
    """导出全市场快照 JSON（供前端首页快速加载）"""
    ensure_dirs()
    
    # 获取全市场关键指标
    df = conn.execute(f"""
        SELECT 
            s.ts_code,
            s.name,
            s.industry,
            d.close,
            d.pct_chg,
            db.pe_ttm,
            db.pb,
            db.total_mv
        FROM stock_info s
        LEFT JOIN daily d ON s.ts_code = d.ts_code AND d.trade_date = '{trade_date}'
        LEFT JOIN daily_basic db ON s.ts_code = db.ts_code AND db.trade_date = '{trade_date}'
        WHERE d.close IS NOT NULL
    """).df()
    
    if df.empty:
        logger.warning("latest summary 无数据")
        return
    
    # 计算市场温度
    pe_median = df["pe_ttm"].median()
    pb_median = df["pb"].median()
    
    # 涨跌停统计
    limit_up = len(df[df["pct_chg"] >= 9.5])
    limit_down = len(df[df["pct_chg"] <= -9.5])
    
    summary = {
        "trade_date": trade_date,
        "total_stocks": len(df),
        "market_temp": {
            "pe_median": round(pe_median, 2) if pd.notna(pe_median) else None,
            "pb_median": round(pb_median, 2) if pd.notna(pb_median) else None,
            "limit_up": limit_up,
            "limit_down": limit_down,
        },
        "stocks": df[["ts_code", "name", "industry", "close", "pct_chg", "pe_ttm", "pb"]].to_dict("records"),
        "updated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    with open(LATEST_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    logger.info(f"latest.json 已导出: {len(df)} 只股票")


def export_index_data(conn: duckdb.DuckDBPyConnection, index_code: str, trade_date: str):
    """导出指数历史数据"""
    df = conn.execute(f"""
        SELECT trade_date, close, open, high, low, vol
        FROM daily
        WHERE ts_code = '{index_code}' AND close IS NOT NULL
        ORDER BY trade_date
    """).df()
    
    if df.empty:
        return
    
    path = os.path.join(INDICES_DIR, f"{index_code.replace('.', '_')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(df.to_dict("records"), f, ensure_ascii=False, indent=2)
