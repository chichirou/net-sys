# GitHub に公開する手順

このファイルは **アップロード作業者のメモ** です。リポジトリ公開後は削除しても構いません。

## 1. GitHub でリポジトリを新規作成

ブラウザで以下を実行:

1. https://github.com/new にアクセス
2. **Repository name**: `net-sys`
3. **Description** (任意): `A sleek Windows 11 system monitoring dashboard in Python/Tkinter`
4. **Visibility**: `Public` を選択
5. **Initialize this repository with**: いずれも**チェックを外す**
   - ☐ Add a README file
   - ☐ Add .gitignore
   - ☐ Choose a license
   
   (ローカルですでに用意したので不要)
6. `Create repository` をクリック

## 2. ローカルから push

このフォルダ (`net-sys/` の中身がある場所) で以下を実行。コマンドプロンプトでも PowerShell でも OK。

```cmd
cd C:\path\to\this\folder

git init
git add .
git commit -m "Initial commit: net-sys v1.1.0"
git branch -M main
git remote add origin https://github.com/chichirou/net-sys.git
git push -u origin main
```

最後の `git push` で GitHub の認証を求められたら、**Personal Access Token** を使うのが推奨です。
- https://github.com/settings/tokens → `Generate new token (classic)` → スコープに `repo` をチェック → 生成
- パスワード入力欄にトークンを貼り付け

## 3. スクリーンショットを追加 (任意)

README.md は `docs/screenshot.png` などを参照しています。アプリの画面をキャプチャして:

```
docs/screenshot.png            ← トップに表示するメインスクリーンショット
docs/screenshot-dashboard.png  ← ダッシュボード全体
docs/screenshot-system.png     ← SYSTEM タブ
docs/screenshot-edit.png       ← 編集モード
```

の名前で配置し、再 commit:

```cmd
git add docs/
git commit -m "Add screenshots to README"
git push
```

スクリーンショットの取り方:
- Windows: `Win + Shift + S` で範囲指定キャプチャ
- アプリの DASHBOARD タブを縦長にキャプチャ
- できれば 2 倍ズーム解像度で撮ると README で綺麗に見える

## 4. リリースを作成 (任意、推奨)

タグを付けてリリースを公開すると、ダウンロードしやすくなります。

```cmd
git tag -a v1.1.0 -m "Release v1.1.0"
git push origin v1.1.0
```

その後、GitHub の `Releases` → `Draft a new release` でタグを選び、CHANGELOG.md の内容を貼り付け。

## 5. README のリポジトリ URL を確認

README.md の以下の行が `chichirou` ユーザー名になっています:

```
git clone https://github.com/chichirou/net-sys.git
```

別のユーザー名で公開する場合は、push 前にこの行を修正してください。

## 6. このファイル (SETUP_GITHUB.md) を削除

公開後は不要なので削除:

```cmd
git rm SETUP_GITHUB.md
git commit -m "Remove setup guide"
git push
```

(または手元で削除して push しなければそのままでも OK)

---

## トラブルシューティング

### `git: command not found` と言われる

Git for Windows をインストール: https://git-scm.com/download/win

### Push が拒否される (403)

- Personal Access Token を使っているか確認
- Token のスコープに `repo` がチェックされているか確認

### 大きすぎるファイルがあると警告

`*.db` や `.exe` などが `.gitignore` で除外されているはず。もし手動でコピーしてしまったら:

```cmd
git rm --cached net_sys_history.db
git commit -m "Remove tracked DB file"
```
