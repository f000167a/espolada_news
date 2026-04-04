# エスポラーダ北海道 ニュースRSSフィード

espolada.com のニュースページをスクレイピングし、RSSフィード (`feed.xml`) を自動生成するリポジトリ。

GitHub Actions で1時間ごとに更新 → GitHub Pages で公開 → IFTTT で X に自動投稿。

## セットアップ手順

### 1. GitHubリポジトリを作成

```bash
# このフォルダをリポジトリとして初期化
cd espolada-rss
git init
git add .
git commit -m "Initial commit"

# GitHubにリポジトリを作成し、pushする
# リポジトリ名: espolada-rss（Public推奨）
git remote add origin https://github.com/<USERNAME>/espolada-rss.git
git branch -M main
git push -u origin main
```

### 2. GitHub Pages を有効化

1. GitHubのリポジトリページへ
2. **Settings** → **Pages**
3. Source: **Deploy from a branch**
4. Branch: **main** / フォルダ: **/docs**
5. Save

数分後に以下のURLでアクセス可能に：
```
https://<USERNAME>.github.io/espolada-rss/feed.xml
```

### 3. GitHub Actions の権限確認

1. **Settings** → **Actions** → **General**
2. 「Workflow permissions」で **Read and write permissions** を選択
3. Save

### 4. 初回実行

1. リポジトリの **Actions** タブへ
2. 「Generate Espolada RSS Feed」ワークフローを選択
3. **Run workflow** → **Run workflow** で手動実行
4. 完了後、`docs/feed.xml` が生成される

### 5. IFTTT で X 投稿を設定

1. [IFTTT](https://ifttt.com/) にログイン
2. **Create** → **If This** → **RSS Feed** → 「New feed item」
3. Feed URL: `https://<USERNAME>.github.io/espolada-rss/feed.xml`
4. **Then That** → **X (Twitter)** → 「Post a tweet」
5. ツイート内容:
   ```
   📢 {{EntryTitle}}
   🔗 {{EntryUrl}}
   #エスポラーダ北海道 #Fリーグ
   ```
6. **Create action** → **Finish**

## ファイル構成

```
espolada-rss/
├── .github/workflows/
│   └── generate-rss.yml    # GitHub Actions（1時間ごと実行）
├── docs/
│   ├── index.html           # GitHub Pages トップページ
│   └── feed.xml             # 生成されるRSSフィード
├── generate_rss.py          # スクレイピング＆RSS生成スクリプト
├── requirements.txt
└── README.md
```

## コスト

すべて無料：
- GitHub Actions: パブリックリポジトリは無制限
- GitHub Pages: 無料
- IFTTT: 無料プラン（Applet 2個まで）
