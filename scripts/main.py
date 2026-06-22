#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主入口：每晚批量计算全 A 股诊断
用法：python scripts/main.py [--limit 100]
"""
import os
import sys
import argparse
import logging
from datetime import datetime, timedelta

import pandas as pd
import duckdb

# 将 scripts 目录加入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DB_PATH, HISTORY_START, TUSHARE_TOKEN
from fetch import (
    get_trade_date,
    fetch_stock_list,
    fetch_daily,
    fetch_daily_basic,
    fetch_all_history_bulk,
    fetch_fina_indicator,
    fetch_industry_map,
)
from metrics import get_db_conn, upsert_df
from export import export_all_stocks, export_latest_summary, export_index_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("hunzor.main")


def run_pipeline(limit: int = None):
    """主流程"""
    logger.info("=" * 50)
    logger.info("hunzor 数据更新开始")
    logger.info("=" * 50)
    
    # 1. 确定交易日
    trade_date = get_trade_date()
    logger.info(f"目标交易日: {trade_date}")
    
    # 2. 初始化数据库
    conn = get_db_conn()
    
    # 3. 拉取股票列表
    logger.info("拉取股票列表...")
    stock_list = fetch_stock_list()
    if stock_list.empty:
        logger.error("股票列表获取失败，终止")
        return
    
    upsert_df(conn, stock_list, "stock_info", ["ts_code"])
    
    # 4. 拉取当日行情
    logger.info("拉取日行情...")
    daily = fetch_daily(trade_date)
    if not daily.empty:
        upsert_df(conn, daily, "daily", ["ts_code", "trade_date"])
    
    # 5. 拉取估值数据
    logger.info("拉取估值数据...")
    basic = fetch_daily_basic(trade_date)
    if not basic.empty:
        upsert_df(conn, basic, "daily_basic", ["ts_code", "trade_date"])
    
    # 6. 批量拉取历史数据（用于分位数计算）
    # 注意：这是耗时步骤，首次运行需要拉取大量历史数据
    # 后续可以增量更新
    logger.info("拉取历史数据（用于分位数）...")
    
    # 检查是否已有历史数据
    existing = conn.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
    logger.info(f"现有历史数据: {existing} 条")
    
    if existing < 10000:  # 首次运行或数据不足
        codes = stock_list["ts_code"].tolist()
        if limit:
            codes = codes[:limit]
        
        start = HISTORY_START
        end = trade_date
        logger.info(f"批量拉取 {len(codes)} 只股票历史数据 ({start} ~ {end})...")
        
        hist = fetch_all_history_bulk(codes, start, end)
        if not hist.empty:
            upsert_df(conn, hist, "daily", ["ts_code", "trade_date"])
            logger.info(f"历史数据写入完成: {len(hist)} 条")
    
    # 7. 导出全市场诊断
    logger.info("导出全市场诊断...")
    export_all_stocks(conn, trade_date, limit=limit)
    
    # 8. 导出最新快照
    logger.info("导出 latest.json...")
    export_latest_summary(conn, trade_date)
    
    # 9. 导出指数数据
    for idx in ["000001.SH", "000300.SH", "399001.SZ"]:
        export_index_data(conn, idx, trade_date)
    
    conn.close()
    logger.info("=" * 50)
    logger.info("hunzor 数据更新完成")
    logger.info("=" * 50)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="hunzor 数据更新")
    parser.add_argument("--limit", type=int, default=None, help="限制处理股票数量（用于测试）")
    args = parser.parse_args()
    
    run_pipeline(limit=args.limit)
