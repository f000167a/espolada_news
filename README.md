# エスポラーダ北海道 ニュース自動Xポスト Bot

espolada.com の新着ニュースを自動検知し、X（@espolada_news）に自動投稿するBotです。

## 仕組み

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

## 公開URL

- RSSフィード: https://f000167a.github.io/espolada_news/feed.xml
- トップページ: https://f000167a.github.io/espolada_news/

## ポスト例

```
📢 【トップチーム】メットライフ生命Ｆリーグ2026-27レギュラーシーズン日程決定！
🔗 https://espolada.com/news/...
#エスポラーダ北海道 #Fリーグ
```

## ファイル構成

```
espolada_news/
├── .github/workflows/
│   └── generate-rss.yml    # GitHub Actions（毎時自動実行）
├── docs/
│   ├── index.html           # GitHub Pages トップページ
│   └── feed.xml             # 生成されるRSSフィード（自動更新）
├── generate_rss.py          # スクレイピング・RSS生成・X投稿スクリプト
├── posted.json              # 投稿済み記事URL一覧（自動更新）
├── requirements.txt         # Python依存パッケージ
└── README.md
```

## セットアップ（参考）

### 必要なもの

- GitHubアカウント
- X Developer Portal アカウント（Free tier、月500ポストまで無料）

### GitHub Secrets に登録するキー

| Secret名 | 内容 |
|---|---|
| `X_API_KEY` | X API コンシューマーキー |
| `X_API_SECRET` | X API コンシューマーシークレット |
| `X_ACCESS_TOKEN` | X API アクセストークン（Read and Write権限） |
| `X_ACCESS_SECRET` | X API アクセストークンシークレット |

Settings → Secrets and variables → Actions → New repository secret で登録。

### GitHub Pages 設定

Settings → Pages → Deploy from a branch → main / /docs

## 技術詳細

- **スクレイピング**: BeautifulSoup4 で espolada.com/news/ のリンク一覧を取得
- **RSS生成**: xml.etree.ElementTree で RSS 2.0 XML を生成
- **X投稿**: tweepy (OAuth 1.0a) で X API v2 の create_tweet を実行
- **重複防止**: posted.json に投稿済みURLを記録し、同じ記事を2回投稿しない
- **実行環境**: GitHub Actions (Ubuntu) で毎時0分に自動実行
- **配信**: GitHub Pages で RSS フィードを静的ホスティング

## コスト

すべて無料：
- GitHub Actions: パブリックリポジトリは無制限
- GitHub Pages: 無料
- X API Free tier: 月500ポストまで無料
