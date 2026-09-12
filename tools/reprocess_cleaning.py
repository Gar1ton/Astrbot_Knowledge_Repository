"""手动维护已有实例的 PDF 清洗；默认预览，加 --apply 才重抽取及索引。

示例：python3 tools/reprocess_cleaning.py --url http://127.0.0.1:8080 --apply
密码从 KA_WEB_PASSWORD 环境变量读取；不输出密码，不访问原始数据库。
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="用户选定的 WebUI 实例地址")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--apply", action="store_true", help="实际重抽取及索引；可能消费 embedding")
    args = parser.parse_args()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def post(path: str, payload: dict) -> object:
        request = urllib.request.Request(
            args.url.rstrip("/") + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with opener.open(request, timeout=3600) as response:
            return json.load(response)

    password = os.environ.get("KA_WEB_PASSWORD")
    if password:
        post("/api/login", {"username": args.username, "password": password})
    result = post("/api/documents/reprocess-cleaning", {"dry_run": not args.apply})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
