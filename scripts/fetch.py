#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据拉取模块
支持 Tushare（优先）和 AKShare（fallback）
原则：每晚批量拉取，一次搞定全市场
"""
import os
import sys
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import duckdb

from config import (
    TUSHARE_TOKEN, HISTORY_START, DATA_DIR, DB_PATH, STOCKS_DIR, INDICES_DIR
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("hunzor.fetch")

# ───────────────────────────────
# 1. 初始化数据接口
# ───────────────────────────────

def _init_tushare():
    """尝试初始化 Tushare"""
    if not TUSHARE_TOKEN:
        return None
    try:
        import tushare as ts
        pro = ts.pro_api(TUSHARE_TOKEN)
        # 验证 token
        pro.trade_cal(exchange="SSE", limit=1)
        logger.info("Tushare 初始化成功")
        return pro
    except Exception as e:
        logger.warning(f"Tushare 初始化失败: {e}，将使用 AKShare")
        return None


def _init_akshare():
    """初始化 AKShare（纯免费）"""
    try:
        import akshare as ak
        logger.info("AKShare 初始化成功")
        return ak
    except Exception as e:
        logger.error(f"AKShare 初始化失败: {e}")
        return None


# 全局接口实例
_pro = _init_tushare()
_ak = _init_akshare()


# ───────────────────────────────
# 2. 交易日历
# ───────────────────────────────

def get_trade_date(days_offset=0) -> str:
    """获取最近交易日（YYYYMMDD）"""
    if _pro:
        today = datetime.now().strftime("%Y%m%d")
        df = _pro.trade_cal(exchange="SSE", start_date="20240101", end_date=today)
        df = df[df["is_open"] == 1].sort_values("cal_date")
        dates = df["cal_date"].tolist()
        if dates:
            idx = max(0, len(dates) - 1 + days_offset)
            return dates[min(idx, len(dates) - 1)]
    
    # fallback：AKShare 或简单逻辑
    if _ak:
        try:
            df = _ak.tool_trade_date_hist_sina()
            df = df[df["trade_date"] <= datetime.now().strftime("%Y-%m-%d")]
            dates = df["trade_date"].tolist()
            if dates:
                d = dates[-1 + days_offset] if -1 + days_offset >= 0 else dates[-1]
                return d.replace("-", "")
        except Exception:
            pass
    
    # 最后 fallback：回退到上一个工作日
    d = datetime.now() - timedelta(days=abs(days_offset))
    while d.weekday() >= 5:  # 周六日
        d -= timedelta(days=1)
    return d.strftime("%Y%m%d")


# ───────────────────────────────
# 3. 股票基础信息
# ───────────────────────────────

def fetch_stock_list() -> pd.DataFrame:
    """获取全 A 股列表：ts_code, name, industry, list_date"""
    if _pro:
        try:
            df = _pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,industry,list_date,market")
            if not df.empty:
                return df
        except Exception as e:
            logger.warning(f"Tushare stock_basic 失败: {e}")
    
    if _ak:
        try:
            df = _ak.stock_zh_a_spot_em()
            # 标准化列名
            df = df[["代码", "名称", "所属行业"]].copy()
            df.columns = ["ts_code", "name", "industry"]
            # 补 suffix
            df["ts_code"] = df["ts_code"].apply(lambda x: x + ".SH" if x.startswith("6") else x + ".SZ" if x.startswith("0") or x.startswith("3") else x)
            df["list_date"] = None
            df["market"] = None
            return df
        except Exception as e:
            logger.error(f"AKShare stock_list 失败: {e}")
    
    return pd.DataFrame()


# ───────────────────────────────
# 4. 日行情数据
# ───────────────────────────────

def fetch_daily(trade_date: str) -> pd.DataFrame:
    """拉取指定交易日的全市场日 K"""
    if _pro:
        try:
            df = _pro.daily(trade_date=trade_date)
            if not df.empty:
                logger.info(f"Tushare daily: {len(df)} 条记录")
                return df
        except Exception as e:
            logger.warning(f"Tushare daily 失败: {e}")
    
    if _ak:
        try:
            df = _ak.stock_zh_a_spot_em()
            # 标准化列名以兼容 Tushare
            rename_map = {
                "代码": "ts_code",
                "名称": "name",
                "最新价": "close",
                "今开": "open",
                "最高": "high",
                "最低": "low",
                "涨跌幅": "pct_chg",
                "成交量": "vol",
                "成交额": "amount",
                "涨跌额": "change",
                "换手率": "turnover_rate",
                "市盈率": "pe",
                "市净率": "pb",
                "总市值": "total_mv",
                "流通市值": "circ_mv",
            }
            df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
            # 补充缺失列
            for col in ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]:
                if col not in df.columns:
                    df[col] = np.nan
            # 标准化 ts_code
            df["ts_code"] = df.get("ts_code", df.get("代码", "")).astype(str)
            df = df[~df["ts_code"].isin(["nan", ""])]
            df["trade_date"] = trade_date
            logger.info(f"AKShare daily: {len(df)} 条记录")
            return df
        except Exception as e:
            logger.error(f"AKShare daily 失败: {e}")
    
    return pd.DataFrame()


def fetch_daily_basic(trade_date: str) -> pd.DataFrame:
    """拉取指定交易日的全市场估值/财务指标"""
    if _pro:
        try:
            df = _pro.daily_basic(trade_date=trade_date)
            if not df.empty:
                logger.info(f"Tushare daily_basic: {len(df)} 条记录")
                return df
        except Exception as e:
            logger.warning(f"Tushare daily_basic 失败: {e}")
    
    # AKShare 的 spot_em 已经包含部分估值字段，在 fetch_daily 中已处理
    return pd.DataFrame()


# ───────────────────────────────
# 5. 历史日线（用于计算分位数）
# ───────────────────────────────

def fetch_history(ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """拉取单只股票历史日线"""
    if _pro:
        try:
            df = _pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if not df.empty:
                return df.sort_values("trade_date")
        except Exception as e:
            logger.warning(f"Tushare history {ts_code} 失败: {e}")
    
    if _ak:
        try:
            code = ts_code.split(".")[0]
            df = _ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_date, end_date=end_date, adjust="qfq")
            if not df.empty and "日期" in df.columns:
                df = df.rename(columns={
                    "日期": "trade_date",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "vol",
                    "成交额": "amount",
                    "涨跌幅": "pct_chg",
                })
                df["ts_code"] = ts_code
                return df.sort_values("trade_date")
        except Exception as e:
            logger.warning(f"AKShare history {ts_code} 失败: {e}")
    
    return pd.DataFrame()


def fetch_all_history_bulk(ts_codes: list, start_date: str, end_date: str) -> pd.DataFrame:
    """批量拉取历史日线（逐个请求，带限流）"""
    all_dfs = []
    for i, code in enumerate(ts_codes):
        df = fetch_history(code, start_date, end_date)
        if not df.empty:
            all_dfs.append(df)
        # 限流：避免 API 被封
        if _pro and (i + 1) % 80 == 0:
            time.sleep(1)
        elif _ak and (i + 1) % 50 == 0:
            time.sleep(1)
    
    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame()


# ───────────────────────────────
# 6. 财务指标（季度）
# ───────────────────────────────

def fetch_fina_indicator(ts_code: str) -> pd.DataFrame:
    """拉取单只股票财务指标（ROE、毛利率等）"""
    if _pro:
        try:
            df = _pro.fina_indicator(ts_code=ts_code)
            if not df.empty:
                df = df.sort_values("end_date", ascending=False)
                return df
        except Exception as e:
            logger.warning(f"Tushare fina {ts_code} 失败: {e}")
    
    # AKShare 获取财务指标（较复杂，暂时返回空）
    return pd.DataFrame()


# ───────────────────────────────
# 7. 行业分类
# ───────────────────────────────

def fetch_industry_map() -> pd.DataFrame:
    """获取股票-行业映射"""
    if _pro:
        try:
            # 申万行业分类
            df = _pro.index_classify(level="L3", src="SW")
            if not df.empty:
                return df
        except Exception as e:
            logger.warning(f"Tushare industry 失败: {e}")
    
    # fallback：用 stock_basic 里的 industry 字段
    return pd.DataFrame()


# ───────────────────────────────
# 8. 指数行情
# ───────────────────────────────

def fetch_index_daily(index_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """拉取指数日线"""
    if _pro:
        try:
            df = _pro.index_daily(ts_code=index_code, start_date=start_date, end_date=end_date)
            if not df.empty:
                return df.sort_values("trade_date")
        except Exception:
            pass
    
    if _ak:
        try:
            # 沪深300
            if index_code in ["000300.SH", "000300"]:
                df = _ak.index_zh_a_hist(symbol="000300", period="daily", start_date=start_date, end_date=end_date)
            elif index_code in ["000001.SH", "000001"]:
                df = _ak.index_zh_a_hist(symbol="000001", period="daily", start_date=start_date, end_date=end_date)
            else:
                df = pd.DataFrame()
            
            if not df.empty and "日期" in df.columns:
                df = df.rename(columns={
                    "日期": "trade_date",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "vol",
                    "成交额": "amount",
                })
                df["ts_code"] = index_code
                return df.sort_values("trade_date")
        except Exception:
            pass
    
    return pd.DataFrame()


# ───────────────────────────────
# 主入口：每晚运行
# ───────────────────────────────

if __name__ == "__main__":
    td = get_trade_date()
    logger.info(f"最近交易日: {td}")
    
    # 测试拉取
    df_list = fetch_stock_list()
    logger.info(f"股票列表: {len(df_list)} 只")
    
    df_daily = fetch_daily(td)
    logger.info(f"日行情: {len(df_daily)} 条")
    
    df_basic = fetch_daily_basic(td)
    logger.info(f"估值数据: {len(df_basic)} 条")
