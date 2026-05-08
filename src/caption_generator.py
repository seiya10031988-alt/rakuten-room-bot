"""
caption_generator.py
OpenAI GPT-4.1-miniを使って楽天Room投稿用のキャプションを自動生成するモジュール。
コスト最小化のため、軽量モデル（gpt-4.1-mini）を使用する。
"""

import os
from datetime import datetime
from openai import OpenAI

# OpenAI クライアント初期化（環境変数 OPENAI_API_KEY を自動参照）
client = OpenAI()

# 投稿URLの掲載ルール
# - 毎日夜の投稿のみURLを掲載
# - ただし毎月25〜27日はすべての投稿にURLを掲載


def should_include_url() -> bool:
    """
    商品紹介URLを掲載するかどうかを判定する。
    - 毎月25〜27日: 常にTrue
    - それ以外: 夜の投稿（20時以降）のみTrue
    """
    now = datetime.now()
    day = now.day
    hour = now.hour

    if 25 <= day <= 27:
        return True
    # GitHub Actionsのスケジュールは20時（JST）に設定するため、夜の投稿として扱う
    return hour >= 20


def generate_caption(product_info: dict) -> str:
    """
    商品情報を受け取り、楽天Room投稿用のキャプションを生成する。
    """
    name = product_info.get("name", "")
    price = product_info.get("price", 0)
    shop_name = product_info.get("shop_name", "")
    review_average = product_info.get("review_average", 0)
    review_count = product_info.get("review_count", 0)
    item_caption = product_info.get("item_caption", "")[:300]  # 長すぎる場合は切り詰め
    affiliate_url = product_info.get("affiliate_url", "")
    item_url = product_info.get("item_url", "")

    # URL掲載判定
    include_url = should_include_url()
    url_to_use = affiliate_url if affiliate_url else item_url

    # 季節感を加えるための現在月
    month = datetime.now().month
    season_map = {
        12: "冬", 1: "冬", 2: "冬",
        3: "春", 4: "春", 5: "春",
        6: "夏", 7: "夏", 8: "夏",
        9: "秋", 10: "秋", 11: "秋",
    }
    season = season_map.get(month, "")

    # プロンプト構築
    url_instruction = (
        f"\n\n最後に必ず以下のURLを掲載してください：\n{url_to_use}"
        if include_url and url_to_use
        else "\n\nURLは掲載しないでください。"
    )

    prompt = f"""あなたは釣り・アウトドア好きのインフルエンサーです。
以下の商品を楽天Roomに紹介する投稿文を作成してください。

【商品情報】
- 商品名: {name}
- 価格: ¥{price:,}
- ショップ: {shop_name}
- レビュー: {review_average}点（{review_count}件）
- 商品説明（参考）: {item_caption}
- 季節: {season}

【投稿文の条件】
- 文字数: 150〜250文字程度
- 語尾は「です・ます調」または「だ・である調」どちらでも可
- 釣り人・アウトドア好きの目線で、実際に使いたくなるような魅力を伝える
- ハッシュタグを3〜5個つける（#釣り #アウトドア など関連タグ）
- 絵文字を2〜4個使って親しみやすくする
- 商品の季節感や使用シーンを具体的に描写する{url_instruction}

投稿文のみを出力してください（前置きや説明は不要）。"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",  # コスト最小化のため軽量モデルを使用
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.8,
        )
        caption = response.choices[0].message.content.strip()
        print(f"[INFO] キャプション生成完了（{len(caption)}文字）")
        return caption
    except Exception as e:
        print(f"[ERROR] キャプション生成失敗: {e}")
        # フォールバック: シンプルなキャプション
        fallback = f"🎣 {name}\n\n釣り・アウトドア好きにおすすめの一品です！\n¥{price:,}で購入できます。\n\n#釣り #アウトドア #楽天room"
        if include_url and url_to_use:
            fallback += f"\n\n{url_to_use}"
        return fallback


if __name__ == "__main__":
    # 動作確認用
    test_product = {
        "name": "シマノ スピニングリール 22 サハラ 2500",
        "price": 6980,
        "shop_name": "釣具のポイント",
        "review_average": 4.5,
        "review_count": 320,
        "item_caption": "軽量・高剛性のスピニングリール。アジング・メバリングに最適。",
        "affiliate_url": "https://hb.afl.rakuten.co.jp/xxx",
        "item_url": "https://item.rakuten.co.jp/xxx",
    }
    caption = generate_caption(test_product)
    print("\n=== 生成されたキャプション ===")
    print(caption)
