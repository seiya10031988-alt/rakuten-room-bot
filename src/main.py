"""
main.py
楽天Room自動投稿システムのメインエントリーポイント。

【修正履歴】
- v2: 投稿失敗時に別商品で最大3回再試行する処理を追加
- v3: 投稿済み商品をGitHubのJSONファイルに記録・除外する仕組みを実装
      「要求されたURL存在しません」は投稿済み商品として記録してスキップ
"""

import os
import sys
import json
import base64
import requests
from datetime import datetime

# ── 環境変数 ──────────────────────────────────────────────────────────────────
RAKUTEN_APP_ID = os.environ.get("RAKUTEN_APP_ID", "")
RAKUTEN_ACCESS_KEY = os.environ.get("RAKUTEN_ACCESS_KEY", "")
RAKUTEN_AFFILIATE_ID = os.environ.get("RAKUTEN_AFFILIATE_ID", "")
RAKUTEN_COOKIES = os.environ.get("RAKUTEN_COOKIES", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "seiya10031988-alt/rakuten-room-bot")

POSTED_ITEMS_PATH = "data/posted_items.json"
MAX_POSTED_ITEMS = 500  # 記録する最大件数（古いものから削除）
MAX_RETRY = 5  # 最大再試行回数


def check_env():
    required = {
        "RAKUTEN_APP_ID": RAKUTEN_APP_ID,
        "RAKUTEN_ACCESS_KEY": RAKUTEN_ACCESS_KEY,
        "RAKUTEN_AFFILIATE_ID": RAKUTEN_AFFILIATE_ID,
        "RAKUTEN_COOKIES": RAKUTEN_COOKIES,
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "GITHUB_TOKEN": GITHUB_TOKEN,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"[ERROR] 環境変数が設定されていません: {', '.join(missing)}")
        sys.exit(1)
    print("[INFO] 環境変数チェック: OK")


def get_posted_items() -> dict:
    """
    GitHubリポジトリから投稿済み商品リストを取得する。
    ファイルが存在しない場合は空のリストを返す。
    """
    if not GITHUB_TOKEN:
        return {"items": [], "sha": None}
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{POSTED_ITEMS_PATH}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 404:
            print(f"[INFO] {POSTED_ITEMS_PATH} が存在しないため、新規作成します。")
            return {"items": [], "sha": None}
        response.raise_for_status()
        data = response.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        items_data = json.loads(content)
        sha = data.get("sha")
        print(f"[INFO] 投稿済み商品リスト取得: {len(items_data.get('items', []))} 件")
        return {"items": items_data.get("items", []), "sha": sha}
    except Exception as e:
        print(f"[WARN] 投稿済み商品リストの取得に失敗しました: {e}")
        return {"items": [], "sha": None}


def save_posted_item(item_code: str, item_name: str, posted_data: dict) -> bool:
    """
    投稿済み商品をGitHubリポジトリのJSONファイルに保存する。
    """
    if not GITHUB_TOKEN:
        print("[WARN] GITHUB_TOKENが設定されていないため、投稿済み商品を保存できません。")
        return False
    
    items = posted_data.get("items", [])
    sha = posted_data.get("sha")
    
    # 既に記録済みでなければ追加
    existing_codes = [item.get("item_code") for item in items]
    if item_code not in existing_codes:
        items.append({
            "item_code": item_code,
            "item_name": item_name[:50],
            "posted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    
    # 最大件数を超えたら古いものを削除
    if len(items) > MAX_POSTED_ITEMS:
        items = items[-MAX_POSTED_ITEMS:]
    
    content_json = json.dumps({"items": items}, ensure_ascii=False, indent=2)
    content_b64 = base64.b64encode(content_json.encode("utf-8")).decode("utf-8")
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{POSTED_ITEMS_PATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "message": f"feat: 投稿済み商品を記録 - {item_code}",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha
    
    try:
        response = requests.put(url, headers=headers, json=payload, timeout=15)
        if response.status_code in (200, 201):
            print(f"[INFO] 投稿済み商品を記録しました: {item_code} ({len(items)} 件)")
            return True
        else:
            print(f"[WARN] 投稿済み商品の保存に失敗しました: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"[WARN] 投稿済み商品の保存中にエラー: {e}")
        return False


def generate_caption(product_info: dict) -> str:
    """OpenAI APIを使って商品のキャプションを生成する。"""
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    
    name = product_info.get("name", "")
    price = product_info.get("price", 0)
    review_average = product_info.get("review_average", 0)
    review_count = product_info.get("review_count", 0)
    caption_hint = product_info.get("item_caption", "")[:200]
    
    prompt = f"""以下の楽天市場の商品について、楽天ROOMに投稿するキャプションを作成してください。

商品名: {name}
価格: ¥{price:,}
レビュー: {review_average}点 ({review_count}件)
商品説明: {caption_hint}

要件:
- 一人称は「私」を使用
- 釣り・アウトドア好きの視点で書く
- 商品の魅力を具体的に伝える
- ハッシュタグを3〜5個含める（例: #釣り #アウトドア #楽天ROOM）
- 全体で200〜400文字程度
- 絵文字は使わない
- 自然な日本語で書く"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            temperature=0.7,
        )
        caption = response.choices[0].message.content.strip()
        print(f"[INFO] キャプション生成完了（{len(caption)}文字）")
        return caption
    except Exception as e:
        print(f"[ERROR] キャプション生成に失敗しました: {e}")
        return f"{name}\n\n価格: ¥{price:,}\nレビュー: {review_average}点 ({review_count}件)\n\n#楽天ROOM #釣り #アウトドア"


def main():
    print("[START] 楽天Room自動投稿システム起動")
    now = datetime.now()
    print(f"[INFO] 実行日時: {now.strftime('%Y年%m月%d日 %H:%M:%S')}")
    
    # 環境変数チェック
    check_env()
    
    # 投稿済み商品リストを取得
    print("\n[PHASE 0] 投稿済み商品リスト取得中...")
    posted_data = get_posted_items()
    posted_codes = [item.get("item_code") for item in posted_data.get("items", [])]
    print(f"[INFO] 除外対象: {len(posted_codes)} 件の投稿済み商品")
    
    # 商品検索・選定
    print("\n[PHASE 1] 商品検索・選定中...")
    from product_selector import select_best_product, format_product_info
    
    product = None
    exclude_codes = list(posted_codes)  # 投稿済み商品を除外
    
    for attempt in range(1, MAX_RETRY + 1):
        print(f"[INFO] 商品選定試行 {attempt}/{MAX_RETRY}（除外: {len(exclude_codes)} 件）")
        candidate = select_best_product(exclude_codes=exclude_codes)
        if not candidate:
            print("[WARN] 商品が見つかりませんでした。")
            break
        
        candidate_code = candidate.get("itemCode", "")
        product = candidate
        print(f"[INFO] 選定商品: {candidate.get('itemName', '不明')[:60]}")
        print(f"[INFO] 価格: ¥{candidate.get('itemPrice', 0):,}")
        print(f"[INFO] レビュー: {candidate.get('reviewAverage', 0)}点 ({candidate.get('reviewCount', 0)}件)")
        break
    
    if not product:
        print("[FAILED] 適切な商品が見つかりませんでした。")
        sys.exit(1)
    
    product_info = format_product_info(product)
    
    # キャプション生成
    print("\n[PHASE 2] AIキャプション生成中...")
    caption = generate_caption(product_info)
    print(f"[INFO] キャプション生成完了（{len(caption)}文字）")
    
    # 楽天ROOMへの投稿（最大MAX_RETRY回試行）
    print("\n[PHASE 3] 楽天Roomへ投稿中...")
    from room_poster import post_to_rakuten_room
    
    success = False
    exclude_codes_for_post = list(posted_codes)
    
    for attempt in range(1, MAX_RETRY + 1):
        item_code = product_info.get("item_code_full", "")
        print(f"[INFO] 投稿試行 {attempt}/{MAX_RETRY}: {item_code}")
        
        result = post_to_rakuten_room(product_info, caption)
        
        if result is True:
            # 投稿成功
            success = True
            print(f"[SUCCESS] 投稿が正常に完了しました！")
            print(f"[INFO] 投稿商品: {product_info.get('name', '')[:60]}")
            print(f"[INFO] 投稿日時: {now.strftime('%Y年%m月%d日 %H:%M:%S')}")
            
            # 投稿済み商品として記録
            save_posted_item(item_code, product_info.get("name", ""), posted_data)
            break
            
        elif result == "url_not_found":
            # 投稿できない商品（既投稿 or 存在しない商品）
            print(f"[WARN] 商品 {item_code} は投稿できません（投稿済みまたは存在しない）。")
            
            # 投稿済みとして記録（次回以降スキップ）
            save_posted_item(item_code, product_info.get("name", ""), posted_data)
            # posted_dataを更新（次のsave_posted_itemで正しいSHAを使うため）
            posted_data = get_posted_items()
            
            # 別の商品を選定
            exclude_codes_for_post.append(item_code)
            print(f"[INFO] 別の商品を選定します（除外: {len(exclude_codes_for_post)} 件）")
            
            candidate = select_best_product(exclude_codes=exclude_codes_for_post)
            if not candidate:
                print("[WARN] 代替商品が見つかりませんでした。")
                break
            
            product_info = format_product_info(candidate)
            caption = generate_caption(product_info)
            print(f"[INFO] 代替商品: {product_info.get('name', '')[:60]}")
            
        else:
            # その他の失敗（クッキー切れ、タイムアウトなど）
            print(f"[ERROR] 投稿に失敗しました（試行 {attempt}/{MAX_RETRY}）。")
            if attempt < MAX_RETRY:
                print("[INFO] リトライします...")
            break
    
    if not success:
        print("[FAILED] 投稿に失敗しました。")
        sys.exit(1)


if __name__ == "__main__":
    main()
