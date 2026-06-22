#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包脚本：将 data/stocks/*.json 合并为前端可直接加载的 JS 数据文件
用法：python scripts/build_embedded.py
"""
import os
import json
import glob

# 路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "..", "hunzor-pwa")

def build():
    stocks_dir = os.path.join(DATA_DIR, "stocks")
    if not os.path.exists(stocks_dir):
        print("错误：找不到 data/stocks/ 目录，请先运行 python scripts/main.py")
        return False
    
    files = glob.glob(os.path.join(stocks_dir, "*.json"))
    if not files:
        print("错误：data/stocks/ 为空，请先运行数据更新")
        return False
    
    print(f"正在打包 {len(files)} 只股票数据...")
    
    embedded = {}
    for f in files:
        code = os.path.basename(f).replace("_", ".").replace(".json", "")
        with open(f, "r", encoding="utf-8") as fp:
            embedded[code] = json.load(fp)
    
    # 同时打包 latest.json
    latest_path = os.path.join(DATA_DIR, "latest.json")
    if os.path.exists(latest_path):
        with open(latest_path, "r", encoding="utf-8") as fp:
            embedded["_latest"] = json.load(fp)
    
    # 生成 JS 文件
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, "all_stocks_data.js")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("// hunzor 嵌入数据 - 由 build_embedded.py 自动生成\n")
        f.write("// 生成时间: " + __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
        f.write("const HUNZOR_EMBEDDED_DATA = ")
        json.dump(embedded, f, ensure_ascii=False, indent=2)
        f.write(";\n")
        f.write("if (typeof window !== 'undefined') window.HUNZOR_EMBEDDED_DATA = HUNZOR_EMBEDDED_DATA;\n")
    
    # 同时生成纯 JSON 版本（供局域网模式使用）
    json_output = os.path.join(DATA_DIR, "all_stocks.json")
    with open(json_output, "w", encoding="utf-8") as f:
        json.dump(embedded, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 打包完成：")
    print(f"   - {output_path} ({len(embedded)-1} 只股票)")
    print(f"   - {json_output}")
    return True

if __name__ == "__main__":
    build()
