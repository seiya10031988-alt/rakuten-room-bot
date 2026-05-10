"""
main.py
楽天Room自動投稿システムのメインエントリーポイント。
GitHub Actionsから呼び出される。

【修正履歴】
- v2: 投稿失敗時に別商品で最大3回再試行する処理を追加
      投稿後URLが変わらない場合を失敗と判定
"""

import sys
import os
from datetime import datetime

from product_selector import select_best_product, format_product_info
from caption_generator import generate_caption
from room_poster import post_to_rakuten_room


def validate_env() -> bool:
    required = {
        "RAKUTEN_APP_ID": os.environ.get("RAKUTEN_APP_ID"),
        "RAKUTEN_AFFILIATE_ID": os.environ.get("RAKUTEN_AFFILIATE_ID"),
        "RAKUTEN_COOKIES": os.environ.get("RAKUTEN_COOKIES"),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"[ERROR] 以下の環境変数が設定されていません: {', '.join(missing)}")
        return False
    print("[INFO] 環境変数チェック: OK")
    return True


def run():
    now = datetime.now()
    print(f"\n{'='*50}")
    print(f"[START] 楽天Room自動投稿システム起動")
    print(f"[INFO] 実行日時: {now.strftime('%Y年%m月%d日 %H:%M:%S')}")
    print(f"{'='*50}\n")

    if not validate_env():
        print("[ABORT] 環境変数が不足しているため処理を中断します。")
        sys.exit(1)

    # 最大3回試行（商品を変えながら）
    MAX_RETRY = 3
    tried_codes = []  # 試行済みitemcode

    for attempt in range(1, MAX_RETRY + 1):
        if attempt > 1:
            print(f"\n[INFO] 再試行 {attempt}/{MAX_RETRY}...")

        print("\n[PHASE 1] 商品検索・選定中...")
        product = select_best_product(exclude_codes=tried_codes)
        if not product:
            print("[ABORT] 商品が選定できませんでした。処理を中断します。")
            sys.exit(1)

        product_info = format_product_info(product)
        item_code_full = product_info.get("item_code_full", "")
        tried_codes.append(item_code_full)

        print(f"[INFO] 選定商品: {product_info['name']}")
        print(f"[INFO] 価格: ¥{product_info['price']:,}")
        print(f"[INFO] レビュー: {product_info['review_average']}点 ({product_info['review_count']}件)")

        print("\n[PHASE 2] AIキャプション生成中...")
        caption = generate_caption(product_info)
        print(f"[INFO] キャプション生成完了（{len(caption)}文字）")

        print("\n[PHASE 3] 楽天Roomへ投稿中...")
        result = post_to_rakuten_room(product_info, caption)

        # result は True（成功）、False（失敗）、"url_not_found"（商品存在しない）
        if result is True:
            print(f"\n{'='*50}")
            print("[SUCCESS] 投稿が正常に完了しました！")
            print(f"[INFO] 投稿商品: {product_info['name']}")
            print(f"[INFO] 投稿日時: {now.strftime('%Y年%m月%d日 %H:%M:%S')}")
            print(f"{'='*50}\n")
            return
        elif result == "url_not_found":
            print(f"[WARN] 商品 {item_code_full} はROOMに投稿できません。別の商品で再試行します。")
            continue
        else:
            print(f"[WARN] 投稿失敗（試行 {attempt}/{MAX_RETRY}）。別の商品で再試行します。")
            continue

    print(f"\n{'='*50}")
    print("[FAILED] 全ての試行が失敗しました。ログを確認してください。")
    print(f"{'='*50}\n")
    sys.exit(1)


if __name__ == "__main__":
    run()
