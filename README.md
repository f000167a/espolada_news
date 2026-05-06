# エスポラーダ北海道 ニュース自動Xポスト Bot

espolada.com の新着ニュースを自動検知し、X（@espolada_news）に自動投稿するBotです。  
試合結果記事を検知した場合は、espolada_chants の `schedule.json` も自動更新します。

---

## 仕組み

### ニュース自動投稿
```
GitHub Actions（毎時実行）
  ↓
espolada.com/news/ をスクレイピング
  ↓
RSSフィード（feed.xml）を生成 → GitHub Pagesで公開
  ↓
posted.json と照合して新着記事を検出
  ↓
X API v2 で @espolada_news に自動投稿
```

### 試合結果自動反映
```
GitHub Actions（毎日3回実行）
  ↓
espolada.com/news/ から「試合」カテゴリの試合結果記事を検出
  ↓
記事本文からスコア・節番号を抽出
  ↓
GitHub API で espolada_chants/schedule.json を更新
  ↓
next-match.html に試合結果が自動反映
```

---

## 公開URL

- RSSフィード: https://f000167a.github.io/espolada_news/feed.xml
- トップページ: https://f000167a.github.io/espolada_news/

---

## ポスト例

```
📢 【トップチーム】メットライフ生命Ｆリーグ2026-27レギュラーシーズン日程決定！
🔗 https://espolada.com/news/...
#エスポラーダ北海道 #Fリーグ
```

---

## ファイル構成

```
espolada_news/
├── .github/workflows/
│   ├── generate-rss.yml       # ニュース投稿（毎時自動実行）
│   └── update_result.yml      # 試合結果反映（毎日3回実行）
├── docs/
│   ├── index.html              # GitHub Pages トップページ
│   └── feed.xml                # 生成されるRSSフィード（自動更新）
├── generate_rss.py             # スクレイピング・RSS生成・X投稿スクリプト
├── update_result.py            # 試合結果検出・schedule.json更新スクリプト
├── posted.json                 # 投稿済み記事URL一覧（自動更新）
├── posted_results.json         # 処理済み試合結果記事URL一覧（自動更新）
├── requirements.txt            # Python依存パッケージ
└── README.md
```

---

## セットアップ

### 必要なもの

- GitHubアカウント
- X Developer Portal アカウント（Free tier、月500ポストまで無料）
- espolada_chants リポジトリへの書き込み権限付き Personal Access Token（PAT）

### GitHub Secrets に登録するキー

| Secret名 | 内容 |
|---|---|
| `X_API_KEY` | X API コンシューマーキー |
| `X_API_SECRET` | X API コンシューマーシークレット |
| `X_ACCESS_TOKEN` | X API アクセストークン（Read and Write権限） |
| `X_ACCESS_SECRET` | X API アクセストークンシークレット |
| `CHANTS_PAT` | espolada_chants リポジトリへの write 権限付き PAT |

Settings → Secrets and variables → Actions → New repository secret で登録。

### CHANTS_PAT の作成方法

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. Generate new token
3. Repository access: `espolada_chants` のみ選択
4. Permissions: Contents → **Read and write**
5. 生成したトークンを `CHANTS_PAT` として登録

### GitHub Pages 設定

Settings → Pages → Deploy from a branch → main / /docs

---

## 技術詳細

- **スクレイピング**: BeautifulSoup4 で espolada.com/news/ のリンク一覧を取得
- **RSS生成**: xml.etree.ElementTree で RSS 2.0 XML を生成
- **X投稿**: tweepy (OAuth 1.0a) で X API v2 の create_tweet を実行
- **重複防止**: posted.json に投稿済みURLを記録し、同じ記事を2回投稿しない
- **試合結果抽出**: 記事本文から節番号・スコアを正規表現で抽出
- **schedule.json更新**: GitHub Contents API 経由でクロスリポジトリ更新
- **実行環境**: GitHub Actions (Ubuntu) で自動実行
- **配信**: GitHub Pages で RSS フィードを静的ホスティング

---

## 実行スケジュール

| ワークフロー | スケジュール | 内容 |
|---|---|---|
| `generate-rss.yml` | 毎時0分 | ニュース検知・X投稿 |
| `update_result.yml` | JST 9:00 / 18:00 / 23:00 | 試合結果反映 |

---

## コスト

すべて無料：

- GitHub Actions: パブリックリポジトリは無制限
- GitHub Pages: 無料
- X API Free tier: 月500ポストまで無料
