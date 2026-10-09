# 公証とSlack認証を含む配布手順

通常の署名済みビルドと、友人に渡す配布用ZIPは別の段階です。`package-beta.py`の既定動作は公証チケット・Gatekeeper・実際の同梱CoreのSlack設定を検査し、不足があればZIPを作りません。

## Slack側の設定

`slack-send-app-manifest.json`が必要な設定です。本人のユーザー権限のみを使い、bot scopeとClient Secretは使いません。

1. Slackのアプリ設定で、対象アプリの公開Client IDを確認します。既存のBeeperLocal PoCは`A0C5L6H2Q8Y`、公開Client IDは`11683442969584.12190221092304`です。これは秘密情報ではありません。
2. OAuth & PermissionsでPKCEを有効にし、`beeperlocal://oauth/slack`を登録します。PKCE有効化はSlackサポートなしには解除できないため、対象アプリを確認して実行します。
3. manifestの12個のUser Token Scopesとtoken rotationを設定します。既存9権限に追加するものは`users:read`、`files:read`、`files:write`です。
4. Manage Distributionで他ワークスペースへの配布を有効にします。Slack Marketplaceへの掲載申請とは別です。各利用者は自分のブラウザで許可し、ワークスペース管理者の承認が必要な場合はその案内に従います。
5. 実際の保存結果を確認した後に、`beeperlocal/release_config.py`の公開Client IDと`SLACK_DISTRIBUTION_READY = True`を設定します。Client Secretやユーザートークンはソースに書きません。このフラグは設定確認の記録であり、実アカウントでのログイン成功を示すものではありません。

Slack公式仕様: <https://docs.slack.dev/authentication/using-pkce/>

2026-10-03の実設定では、HTTPのlocalhost URLはOAuth設定への保存には成功したものの、Manage DistributionのHTTPS要件で外部ワークスペースへの配布が止まりました。配布用は専用URLに変更し、macOSの`ASWebAuthenticationSession`で受け取る設計です。PKCE verifierはPython Coreのメモリに保持し、コードとstateは署名済みの専用ヘルパーからprivate pipeで受け取ります。認証コードのための外部サーバー、任意URLへの転送、プロセス引数へのコード埋め込みはありません。0.9.5では専用URLの保存と配布有効化をSlackの画面で確認済みです。現行ソースはこのnative経路だけを受け付け、旧localhost認証経路を持ちません。

同日、本人の専用URLへの変更承認後に`beeperlocal://oauth/slack`を保存し、外部配布を有効化しました。保存済みmanifestでPKCE・12 user scopes・token rotationを確認し、Manage Distributionで「Share Your App with Any Workspace」と「Deactivate Public Distribution」を確認しました。公開Client IDと確認済みフラグを0.9.5へ組み込みました。各利用者の権限承認・トークン交換が成功したという記録ではなく、既存利用者も追加権限を反映するには本人がOAuthフローで再承認する必要があります。

## Apple認証の準備

Apple Developerの認証情報はAppleのnotarytoolがKeychainに保存します。未登録の場合、本人がTerminalで次を実行し、対話プロンプトに入力します。パスワードをチャット・シェル引数・ソース・環境変数へ書く必要はありません。

```sh
xcrun notarytool store-credentials beeperlocal-notary
```

既存のプロファイルがある場合は、その保存時の名前を使います。単なるKeychainのサービス名とは区別してください。

## ビルド、公証、パッケージ

以下は`app`ディレクトリから実行します。署名用の`BEEPERLOCAL_SIGN_IDENTITY`と`BEEPERLOCAL_TEAM_ID`は従来の公開証明書識別子です。秘密鍵を取り出しません。

```sh
./scripts/build-desktop.sh --distribution
.release-venv/bin/python -B scripts/macos_notarize.py prepare \
  --app desktop/src-tauri/target/release/bundle/macos/BeeperLocal.app \
  --work .local/notarization-0.9.5
.release-venv/bin/python -B scripts/macos_notarize.py submit \
  --work .local/notarization-0.9.5 --profile beeperlocal-notary
.release-venv/bin/python -B scripts/macos_notarize.py status \
  --work .local/notarization-0.9.5 --profile beeperlocal-notary
```

`prepare`は署名・全同梱実行ファイルを検査し、専用コピーとApple提出用ZIPを作ります。通常アプリと既存ZIPを変更しません。`submit`だけがアプリをAppleへ送ります。申請IDを保存し、処理が継続中なら後で`status`を実行します。固定間隔で待ち続ける処理は含めません。

提出中に通信が途切れた場合は自動再提出を禁止します。Apple側のhistoryから該当の申請IDを確認して`recover --submission-id UUID`を実行します。完了したAppleのログ内のSHA-256が提出ZIPと一致するまで復旧を確定しません。AppleがInvalidを返した場合も配布を停止します。

```sh
.release-venv/bin/python -B scripts/macos_notarize.py staple \
  --work .local/notarization-0.9.5 --profile beeperlocal-notary
.release-venv/bin/python -B scripts/package-beta.py \
  --app .local/notarization-0.9.5/BeeperLocal.app --output ../dist --version 0.9.5
```

`staple`はAppleのAcceptedを再確認し、承認されたアーカイブとの一致を検査してからチケットを付けます。Gatekeeperが`Notarized Developer ID`として認める必要があります。パッケージ作成時も検査し、ZIP展開後にも再検査します。ソース設定と凍結Core設定が違えば配布を停止します。検証結果の`docs/desktop-VERSION-verification.json`も必要です。

開発途中の署名済み候補だけが必要なら`build-desktop.sh --release`と`package-beta.py --candidate`を使います。出力名は`internal-candidate`となり、友人用`beta`と区別します。旧0.9.3 ZIPはこの処理を通過しておらず、公証済みにはなりません。

Apple公式: <https://developer.apple.com/documentation/security/customizing-the-notarization-workflow>

## 配布の残る判定

これらの検査が証明するのは公証と同梱設定です。別Macでの5サービスの本人ログイン・実送受信・画像・再起動・スリープ復帰は別途確認が必要です。モック試験、公証のAccepted、Slack設定完了から実連携の成功を推測しません。
