"""
main.py
楽天Room自動投稿システムのメインエントリーポイント。
GitHub Actionsから呼び出される。
"""

import sys
import json
import os
from datetime import datetime

# 各モジュールのインポート
from product_selector import select_best_product, format_product_info
from caption_generator import generate_caption
from room_poster import post_to_rakuten_room


def validate_env() -> bool:
    """必要な環境変数が設定されているか確認する。"""
    required = {
        "RAKUTEN_APP_ID": os.environ.get("RAKUTEN_APP_ID"),
        "RAKUTEN_AFFILIATE_ID": os.environ.get("RAKUTEN_AFFILIATE_ID"),
        "RAKUTEN_EMAIL": os.environ.get("RAKUTEN_EMAIL"),
        "RAKUTEN_PASSWORD": os.environ.get("RAKUTEN_PASSWORD"),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"[ERROR] 以下の環境変数が設定されていません: {', '.join(missing)}")
        return False
    print("[INFO] 環境変数チェック: OK")
    return True


def run():
    """自動投稿のメイン処理を実行する。"""
    now = datetime.now()
    print(f"\n{'='*50}")
    print(f"[START] 楽天Room自動投稿システム起動")
    print(f"[INFO] 実行日時: {now.strftime('%Y年%m月%d日 %H:%M:%S')}")
    print(f"{'='*50}\n")

    # ── Step 1: 環境変数チェック ──────────────────────────
    if not validate_env():
        print("[ABORT] 環境変数が不足しているため処理を中断します。")
        sys.exit(1)

    # ── Step 2: 商品検索・選定 ────────────────────────────
    print("\n[PHASE 1] 商品検索・選定中...")
    product = select_best_product()
    if not product:
        print("[ABORT] 商品が選定できませんでした。処理を中断します。")
        sys.exit(1)

    product_info = format_product_info(product)
    print(f"[INFO] 選定商品: {product_info['name']}")
    print(f"[INFO] 価格: ¥{product_info['price']:,}")
    print(f"[INFO] レビュー: {product_info['review_average']}点 ({product_info['review_count']}件)")

    # ── Step 3: キャプション生成 ──────────────────────────
    print("\n[PHASE 2] AIキャプション生成中...")
    caption = generate_caption(product_info)
    print(f"\n--- 生成されたキャプション ---\n{caption}\n{'─'*30}")

    # ── Step 4: 楽天Roomへ投稿 ───────────────────────────
    print("\n[PHASE 3] 楽天Roomへ投稿中...")
    success = post_to_rakuten_room(product_info, caption)

    # ── Step 5: 結果レポート ──────────────────────────────
    print(f"\n{'='*50}")
    if success:
        print("[SUCCESS] 投稿が正常に完了しました！")
        print(f"[INFO] 投稿商品: {product_info['name']}")
        print(f"[INFO] 投稿日時: {now.strftime('%Y年%m月%d日 %H:%M:%S')}")
    else:
        print("[FAILED] 投稿に失敗しました。ログを確認してください。")
        sys.exit(1)
    print(f"{'='*50}\n")


if __name__ == "__main__":
    run()
