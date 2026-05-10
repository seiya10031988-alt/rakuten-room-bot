"""
product_selector.py
楽天市場APIで釣り・アウトドア関連商品を季節に応じて自動検索・選定するモジュール。
【修正履歴】
- v2: itemcodeバリデーション追加（ferry:10000000 などの不正なitemcodeを除外）
- v3: exclude_codesパラメータを追加（投稿失敗した商品を除外して再選定できる）
- v4: ブラックリストショップを追加（vanilla-vague, ferry など投稿できないショップを除外）
- v5: キーワードを大幅増加（各月20〜25個）、ランダム選択数を5個に増加、ソート方法もランダム化
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

# 季節ごとの検索キーワード（釣り・アウトドア・DIY・日用品など幅広く）
SEASONAL_KEYWORDS = {
    1: [
        "ワカサギ 電動リール", "タイラバ 鯛ラバ", "冬キャンプ テント", "釣り 防寒 ブーツ", "アウトドア 薪ストーブ",
        "ワカサギ 釣り セット", "メバリング ロッド 冬", "カレイ 投げ釣り 仕掛け", "冬 シュラフ 寝袋", "防寒 フィッシングウェア",
        "釣り グローブ 防寒", "アウトドア バーナー コンパクト", "焚き火台 冬キャンプ", "ランタン LED アウトドア", "釣り ライン 冬",
        "スノーブーツ アウトドア", "防水 リュック 釣り", "ヒーター アウトドア 小型", "釣り 竿 万能", "アウトドア 保温 水筒",
        "DIY 工具 セット", "収納 ボックス アウトドア", "防水 バッグ 釣り", "ジギング ロッド 冬", "ライフジャケット 釣り",
    ],
    2: [
        "メバリング 冬 ロッド", "カレイ 投げ釣り", "キャンプ 春支度", "釣り 防寒 インナー", "アウトドア バーナー",
        "春 キャンプ テント", "釣り ウキ 仕掛け", "アウトドア チェア 軽量", "ロックフィッシュ ロッド", "防水 ジャケット 釣り",
        "渓流釣り 準備", "フィッシング バッグ", "アウトドア クッカー セット", "釣り ライン 新品", "ランタン キャンプ",
        "タックルボックス 収納", "釣り ウェーダー 春", "アウトドア テーブル 折りたたみ", "磯釣り 仕掛け", "釣り 偏光グラス",
        "DIY 棚 収納", "工具 電動ドライバー", "アウトドア 調理器具", "シュラフ 春用", "釣り 帽子 UV",
    ],
    3: [
        "渓流釣り ルアー", "バス釣り ワーム", "テント 春 キャンプ", "釣り リール 春", "アウトドア チェア 軽量",
        "バス釣り スピナーベイト", "渓流 フライフィッシング", "キャンプ 焚き火台 春", "釣り ウェーダー 渓流", "アウトドア クッカー",
        "ルアー セット バス", "磯釣り ロッド 春", "キャンプ テント ソロ", "釣り 偏光グラス 春", "トレッキング シューズ 春",
        "アウトドア リュック 軽量", "釣り クーラーボックス 小型", "フィッシング グローブ 春", "キャンプ 椅子 コンパクト", "釣り 帽子 春",
        "DIY ペンキ 塗料", "ガーデニング 工具", "アウトドア サンダル", "釣り ベスト フィッシング", "スピニングリール 春",
    ],
    4: [
        "バス釣り ロッド", "渓流 フライフィッシング", "キャンプ 焚き火台", "釣り ウェーダー", "アウトドア クッカー",
        "バス釣り ジグ", "アジング ロッド 春", "メバリング ワーム", "キャンプ タープ", "釣り 日焼け止め 春",
        "ショアジギング ロッド", "エギング タックル 春", "アウトドア テント ファミリー", "釣り ライン PE", "フィッシング バッグ 大容量",
        "キャンプ 調理 セット", "釣り 仕掛け セット", "アウトドア ハンモック", "トレッキング ポール", "釣り ジャケット 春",
        "DIY 木材 加工", "アウトドア テーブル", "ランタン ガス", "釣り 竿 万能 堤防", "スピニングリール 万能",
    ],
    5: [
        "アジング タックル", "メバリング ロッド", "キャンプ テント 夏", "釣り 偏光グラス", "トレッキング シューズ",
        "アジング ワーム セット", "メバリング ジグヘッド", "シーバス ルアー 春", "キャンプ テント 2人用", "釣り クーラーボックス",
        "ショアジギング ジグ", "エギング ロッド 春", "アウトドア 日焼け止め", "釣り ウェア 速乾", "フィッシング サングラス",
        "キャンプ 焚き火 グリル", "釣り ベスト 多機能", "アウトドア 水筒 保冷", "磯釣り 仕掛け 春夏", "釣り 帽子 UVカット",
        "DIY 塗料 外壁", "ガーデン チェア", "アウトドア サンダル 軽量", "釣り ライン フロロ", "タックルケース 収納",
    ],
    6: [
        "海釣り 仕掛け", "磯釣り ロッド", "シュノーケル セット", "釣り クーラーボックス", "アウトドア 虫除け",
        "アジ サビキ 仕掛け", "シーバス ルアー 夏", "青物 ジグ 夏", "キャンプ 虫除け スプレー", "釣り 日焼け止め 強力",
        "ショアジギング タックル", "エギング 夏 ロッド", "アウトドア テント 防水", "釣り ウェア 夏 速乾", "フィッシング 帽子 UVカット",
        "キャンプ 扇風機 充電式", "釣り クーラー 保冷力", "アウトドア 水筒 大容量", "磯釣り 道具 セット", "釣り グローブ 夏",
        "DIY 防水 塗料", "アウトドア レジャーシート", "ビーチ サンダル", "釣り ライン ナイロン", "タックルバッグ 防水",
    ],
    7: [
        "夏 海釣り タックル", "サビキ釣り 仕掛け", "キャンプ 夏 テント", "釣り 日焼け止め", "アウトドア 水筒",
        "青物 ショアジギング 夏", "タチウオ 釣り 夏", "アジング 夏 タックル", "キャンプ 夏 ハンモック", "釣り 冷感 ウェア",
        "シュノーケリング セット 夏", "釣り クーラーボックス 大型", "アウトドア 折りたたみ テーブル", "釣り 帽子 夏 UVカット", "フィッシング ベスト 夏",
        "キャンプ 扇風機 ポータブル", "釣り 虫除け 夏", "アウトドア 保冷 バッグ", "磯釣り 夏 道具", "釣り ライン 夏",
        "DIY ウッドデッキ 材料", "アウトドア BBQ グリル", "水遊び 用品", "釣り 偏光グラス 夏", "タックル ケース 大型",
    ],
    8: [
        "青物 ジギング", "タチウオ テンヤ", "川釣り アユ", "キャンプ ハンモック", "アウトドア 扇風機",
        "ショアジギング 青物 秋準備", "タチウオ ワインド", "アユ 友釣り 仕掛け", "キャンプ 夏 クーラーボックス", "釣り 冷感 タオル",
        "シーバス ルアー 夏秋", "エギング 秋 準備", "アウトドア テント 大型", "釣り ウェア 速乾 夏", "フィッシング グローブ 夏",
        "キャンプ 調理 ダッチオーブン", "釣り 保冷 バッグ", "アウトドア 虫除け 強力", "磯釣り 秋 準備", "釣り ライン 秋",
        "DIY 外構 材料", "アウトドア レジャー 用品", "BBQ セット 大型", "釣り サングラス 偏光", "タックル ロッドケース",
    ],
    9: [
        "秋 青物 ショアジギング", "エギング タコ", "キャンプ 秋 シュラフ", "釣り ジグ 青物", "ハイキング リュック",
        "ショアジギング 秋 ジグ", "エギング イカ 秋", "タチウオ 秋 仕掛け", "キャンプ 秋 テント", "釣り 防寒 秋",
        "青物 ルアー 秋", "ロックフィッシュ 秋 ロッド", "アウトドア ダウン ジャケット 秋", "釣り ウェア 秋 防寒", "フィッシング ライフジャケット",
        "キャンプ 焚き火 秋", "釣り クーラーボックス 秋", "アウトドア リュック 登山", "磯釣り 秋 道具", "釣り ライン 秋 PE",
        "DIY 棚 木材", "アウトドア ブランケット 秋", "トレッキング シューズ 秋", "釣り 帽子 秋", "タックル バッグ 大容量",
    ],
    10: [
        "エギング イカ", "ショアジギング ロッド", "キャンプ 焚き火 秋", "釣り ライフジャケット", "アウトドア ランタン",
        "エギング 秋 タックル", "ショアジギング 秋 ロッド", "タチウオ 秋 テンヤ", "キャンプ 秋冬 シュラフ", "釣り 防寒 ジャケット 秋",
        "ヒラメ 釣り 秋 ルアー", "根魚 ロックフィッシュ 秋", "アウトドア ダウン 軽量", "釣り ウェア 秋冬", "フィッシング グローブ 秋",
        "キャンプ 薪 焚き火台", "釣り 偏光グラス 秋", "アウトドア テント 秋冬", "磯釣り 秋冬 道具", "釣り ライン 秋冬",
        "DIY 工具 電動", "アウトドア ブーツ 秋", "登山 リュック 軽量", "釣り 帽子 防寒 秋", "タックル ロッド 秋",
    ],
    11: [
        "ヒラメ 釣り ルアー", "根魚 ロックフィッシュ", "キャンプ 冬支度", "釣り 防寒 グローブ", "アウトドア ダウン",
        "ヒラメ ルアー 秋冬", "ロックフィッシュ ワーム", "タチウオ 冬 仕掛け", "冬キャンプ シュラフ 極暖", "釣り 防寒 インナー 冬",
        "ショアジギング 冬 ロッド", "メバリング 冬 準備", "アウトドア 防寒 ジャケット", "釣り ウェア 冬 防水", "フィッシング ブーツ 防寒",
        "キャンプ 薪ストーブ 冬", "釣り 保温 水筒", "アウトドア テント 冬用", "磯釣り 冬 道具", "釣り ライン 冬 フロロ",
        "DIY 棚 収納 木材", "アウトドア ヒーター 小型", "登山 防寒 ウェア", "釣り 帽子 ニット 防寒", "タックル ケース 防水",
    ],
    12: [
        "ワカサギ 電動リール", "タイラバ 鯛ラバ", "冬キャンプ シュラフ", "釣り 防寒 ウェア", "アウトドア ストーブ",
        "ワカサギ 釣り 道具 セット", "タイラバ ロッド 冬", "ジギング 冬 ロッド", "冬キャンプ テント 耐寒", "釣り 防寒 グローブ 冬",
        "メバリング 冬 タックル", "カレイ 冬 仕掛け", "アウトドア 薪ストーブ 小型", "釣り ウェア 冬 極暖", "フィッシング ブーツ 防水",
        "キャンプ 焚き火 冬 道具", "釣り 保温 ボトル", "アウトドア テント 冬 防風", "磯釣り 冬 仕掛け", "釣り ライン 冬 ナイロン",
        "DIY 工具 クリスマス ギフト", "アウトドア ギア ギフト 冬", "防寒 インナー アウトドア", "釣り 帽子 防寒 冬", "タックル セット ギフト",
    ],
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

# 検索ソート方法（ランダムに選択して同じ商品が出にくくする）
SEARCH_SORTS = [
    "-reviewCount",   # レビュー数が多い順
    "-reviewAverage", # レビュー評価が高い順
    "standard",       # 標準（楽天おすすめ順）
    "-itemPrice",     # 価格が高い順
    "+itemPrice",     # 価格が安い順
]


def get_seasonal_keywords() -> list:
    """現在の月に応じた季節キーワードリストを返す。"""
    month = datetime.now().month
    return SEASONAL_KEYWORDS.get(month, ["釣り 人気", "アウトドア おすすめ"])


def is_valid_item_code(item_code_full: str) -> bool:
    """
    itemcodeが有効かどうかを検証する。
    有効な条件:
    - shop_code:item_code の形式であること
    - shop_codeとitem_codeが空でないこと
    - ブラックリストに含まれていないこと
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
    毎回5個のキーワードをランダム選択し、ソート方法もランダムに変える。
    """
    if exclude_codes is None:
        exclude_codes = []

    keywords = get_seasonal_keywords()
    # 毎回5個をランダム選択（商品の多様性を確保）
    selected_keywords = random.sample(keywords, min(5, len(keywords)))
    # ソート方法もランダムに選択
    sort_method = random.choice(SEARCH_SORTS)
    print(f"[INFO] 選択キーワード数: {len(selected_keywords)}, ソート: {sort_method}")

    all_items = []
    for kw in selected_keywords:
        items = search_products(kw, hits=10, sort=sort_method)
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

    # スコア上位からランダムに選択（上位10件の中からランダム選択で多様性を確保）
    unique_items.sort(key=score_product, reverse=True)
    top_items = unique_items[:10]
    best = random.choice(top_items)
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
    print(f"[INFO] 季節キーワード数: {len(get_seasonal_keywords())}個")
    product = select_best_product()
    if product:
        info = format_product_info(product)
        print(json.dumps(info, ensure_ascii=False, indent=2))
