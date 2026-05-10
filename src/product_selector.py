"""
product_selector.py
楽天市場APIで釣り・アウトドア関連商品を季節に応じて自動検索・選定するモジュール。

【修正履歴】
- v2: itemcodeバリデーション追加（ferry:10000000 などの不正なitemcodeを除外）
- v3: exclude_codesパラメータを追加（投稿失敗した商品を除外して再選定できる）
- v4: ブラックリストショップを追加（vanilla-vague, ferry など投稿できないショップを除外）
"""

import os
import json
import random
import requests
from datetime import datetime

# ── 定数 ──────────────────────────────────────────────────────────────────────
RAKUTEN_APP_ID = os.environ.get("RAKUTEN_APP_ID", "")
RAKUTEN_ACCESS_KEY = os.environ.get("RAKUTEN_ACCESS_KEY", "")
RAKUTEN_AFFILIATE_ID = os.environ.get("RAKUTEN_AFFILIATE_ID", "")

# 2026年4月更新の新エンドポイント
RAKUTEN_ITEM_SEARCH_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401"

# 季節ごとの検索キーワード（釣り・アウトドア）
SEASONAL_KEYWORDS = {
    3: ["渓流釣り ルアー", "バス釣り ワーム", "テント 春 キャンプ", "釣り リール 春", "アウトドア チェア 軽量"],
    4: ["バス釣り ロッド", "渓流 フライフィッシング", "キャンプ 焚き火台", "釣り ウェーダー", "アウトドア クッカー"],
    5: ["アジング タックル", "メバリング ロッド", "キャンプ テント 夏", "釣り 偏光グラス", "トレッキング シューズ"],
    6: ["海釣り 仕掛け", "磯釣り ロッド", "シュノーケル セット", "釣り クーラーボックス", "アウトドア 虫除け"],
    7: ["夏 海釣り タックル", "サビキ釣り 仕掛け", "キャンプ 夏 テント", "釣り 日焼け止め", "アウトドア 水筒"],
    8: ["青物 ジギング", "タチウオ テンヤ", "川釣り アユ", "キャンプ ハンモック", "アウトドア 扇風機"],
    9: ["秋 青物 ショアジギング", "エギング タコ", "キャンプ 秋 シュラフ", "釣り ジグ 青物", "ハイキング リュック"],
    10: ["エギング イカ", "ショアジギング ロッド", "キャンプ 焚き火 秋", "釣り ライフジャケット", "アウトドア ランタン"],
    11: ["ヒラメ 釣り ルアー", "根魚 ロックフィッシュ", "キャンプ 冬支度", "釣り 防寒 グローブ", "アウトドア ダウン"],
    12: ["ワカサギ 電動リール", "タイラバ 鯛ラバ", "冬キャンプ シュラフ", "釣り 防寒 ウェア", "アウトドア ストーブ"],
    1: ["ワカサギ 電動リール", "タイラバ 鯛ラバ", "冬キャンプ テント", "釣り 防寒 ブーツ", "アウトドア 薪ストーブ"],
    2: ["メバリング 冬 ロッド", "カレイ 投げ釣り", "キャンプ 春支度", "釣り 防寒 インナー", "アウトドア バーナー"],
}

# 不正なitemcodeのパターン（除外対象）
INVALID_ITEM_CODE_PATTERNS = [
    "10000000",  # ダミー値
    "00000000",  # ダミー値
    "99999999",  # ダミー値
]

# 楽天ROOMに投稿できないショップコードのブラックリスト
BLACKLISTED_SHOP_CODES = [
    "vanilla-vague",  # 「要求されたURL存在しません」エラーが発生するショップ
    "ferry",          # 不正なitemcode（ferry:10000000）を返すショップ
]


def get_seasonal_keywords() -> list:
    """現在の月に応じた季節キーワードリストを返す。"""
    month = datetime.now().month
    return SEASONAL_KEYWORDS.get(month, ["釣り 人気", "アウトドア おすすめ"])


def is_valid_item_code(item_code_full: str) -> bool:
    """
    itemcodeが有効かどうかを検証する。
    - shop_code:item_code 形式であること
    - item_codeが不正なダミー値でないこと
    - ショップコードがブラックリストに含まれていないこと
    """
    if not item_code_full or ":" not in item_code_full:
        return False
    parts = item_code_full.split(":", 1)
    if len(parts) != 2:
        return False
    shop_code, item_code = parts
    if not shop_code or not item_code:
        return False
    # ブラックリストチェック
    if shop_code in BLACKLISTED_SHOP_CODES:
        return False
    # ダミー値チェック
    for pattern in INVALID_ITEM_CODE_PATTERNS:
        if item_code == pattern:
            return False
    # item_codeが最低3文字以上あること
    if len(item_code) < 3:
        return False
    return True


def search_products(keyword: str, hits: int = 10, sort: str = "-reviewCount") -> list:
    """
    楽天市場APIで商品を検索する。
    """
    params = {
        "applicationId": RAKUTEN_APP_ID,
        "affiliateId": RAKUTEN_AFFILIATE_ID,
        "keyword": keyword,
        "hits": hits,
        "sort": sort,
        "imageFlag": 1,
        "availability": 1,
        "formatVersion": 2,
    }
    headers = {
        "accessKey": RAKUTEN_ACCESS_KEY,
        "Referer": "https://rakuten.co.jp",
        "Origin": "https://rakuten.co.jp",
    }
    try:
        response = requests.get(RAKUTEN_ITEM_SEARCH_URL, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("Items", [])
    except Exception as e:
        print(f"[ERROR] 商品検索失敗 (keyword={keyword}): {e}")
        return []


def score_product(item: dict) -> float:
    """
    商品のスコアを算出する。
    """
    import math
    review_average = item.get("reviewAverage", 0) or 0
    review_count = item.get("reviewCount", 0) or 0
    score = (review_average * 2) + (math.log1p(review_count) * 1.5)
    if item.get("mediumImageUrls"):
        score += 1.0
    return score


def select_best_product(exclude_codes: list = None) -> dict:
    """
    季節キーワードから商品を検索し、スコアが最も高い商品を1件選定して返す。
    itemcodeが不正な商品・ブラックリストのショップは除外する。
    exclude_codesに含まれるitemcodeの商品も除外する（再試行時に使用）。
    """
    if exclude_codes is None:
        exclude_codes = []

    keywords = get_seasonal_keywords()
    selected_keywords = random.sample(keywords, min(3, len(keywords)))
    all_items = []
    for kw in selected_keywords:
        items = search_products(kw, hits=5)
        all_items.extend(items)
        print(f"[INFO] キーワード「{kw}」で {len(items)} 件取得")

    if not all_items:
        print("[WARN] 商品が取得できませんでした。")
        return None

    seen = set()
    unique_items = []
    skipped = 0
    excluded = 0
    for item in all_items:
        code = item.get("itemCode", "")
        if code and code not in seen:
            # itemcodeバリデーション（ブラックリストチェック含む）
            if not is_valid_item_code(code):
                shop_code = code.split(":")[0] if ":" in code else ""
                if shop_code in BLACKLISTED_SHOP_CODES:
                    print(f"[INFO] ブラックリストショップのためスキップ: {code}")
                else:
                    print(f"[WARN] 不正なitemcodeをスキップ: {code}")
                skipped += 1
                continue
            # 除外リストチェック（投稿失敗した商品を除外）
            if code in exclude_codes:
                print(f"[INFO] 除外リストのためスキップ: {code}")
                excluded += 1
                continue
            seen.add(code)
            unique_items.append(item)

    if skipped > 0:
        print(f"[INFO] 不正/ブラックリストのitemcodeを持つ商品を {skipped} 件スキップしました。")
    if excluded > 0:
        print(f"[INFO] 除外リストの商品を {excluded} 件スキップしました。")

    if not unique_items:
        print("[WARN] 有効なitemcodeを持つ商品が見つかりませんでした。")
        return None

    unique_items.sort(key=score_product, reverse=True)
    best = unique_items[0]
    print(f"[INFO] 選定商品: {best.get('itemName', '不明')} (スコア: {score_product(best):.2f})")
    return best


def format_product_info(item: dict) -> dict:
    """
    投稿に必要な商品情報を整形して返す。
    """
    image_urls = item.get("mediumImageUrls", [])
    image_url = image_urls[0] if image_urls else ""
    item_code_full = item.get("itemCode", "")
    shop_code = item_code_full.split(":")[0] if ":" in item_code_full else ""
    item_code = item_code_full.split(":")[1] if ":" in item_code_full else item_code_full
    return {
        "name": item.get("itemName", ""),
        "price": item.get("itemPrice", 0),
        "shop_name": item.get("shopName", ""),
        "review_average": item.get("reviewAverage", 0),
        "review_count": item.get("reviewCount", 0),
        "item_url": item.get("itemUrl", ""),
        "affiliate_url": item.get("affiliateUrl", ""),
        "image_url": image_url,
        "item_caption": item.get("itemCaption", ""),
        "genre_id": item.get("genreId", ""),
        "item_code": item_code,
        "shop_code": shop_code,
        "item_code_full": item_code_full,
    }


if __name__ == "__main__":
    print(f"[INFO] 現在の月: {datetime.now().month}月")
    print(f"[INFO] 季節キーワード: {get_seasonal_keywords()}")
    product = select_best_product()
    if product:
        info = format_product_info(product)
        print(json.dumps(info, ensure_ascii=False, indent=2))
