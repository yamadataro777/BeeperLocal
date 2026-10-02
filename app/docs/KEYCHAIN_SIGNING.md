# キーチェーン許可の維持とMac署名

更新: 2026-10-01。対象は既存macOSアプリ。別のMacでの受入確認はユーザー指定で後回し。

## 修正内容

従来のkeyring 25.7.0のmacOS backendは、`set_password`で既存項目を削除して再作成していた。BeeperLocalの接続情報や会話選択の更新に伴い、項目の同一性・既存アクセス許可が失われる経路があった。

`beeperlocal/native_keychain.py`でAppleのSecurity.frameworkを直接利用する。既存項目は`SecItemUpdate`で値だけを更新し、項目が存在しないときだけ`SecItemAdd`する。許可拒否・ロック・署名エラーを「項目がない」と扱わず、削除再作成や別ストレージへのfallbackをしない。作成競合では既存項目の更新を一度試す。CF参照を解放し、失敗情報はOSStatusだけを上位層へ返す。

service `BeeperLocalPoC.v1`と各account名、保存形式、DB鍵を維持するため、再ログインやDB再暗号化は不要。既存のアクセス許可は変更しない。新規項目にはmacOS標準の作成元アプリに対するアクセス制御を使う。全アプリへの許可、partition list変更、手書きの緩いコード要件は追加しない。

LINE認証情報の保存は同梱LINE helperの既存native Keychain実装を継続する。その実装も更新を先に試す方式である。

## 署名の作成

`scripts/build-desktop.sh --development`はローカル検証用の仮署名。`--release`は明示したDeveloper ID Application証明書を必須とする。未設定・別Team・Apple Development証明書の場合は、ビルド開始前に停止し、仮署名へ切り替えない。

固定の署名識別子:

| 対象 | Identifier |
|---|---|
| アプリ | `local.beeperlocal.desktop` |
| Core | `local.beeperlocal.desktop.core` |
| LINE helper | `local.beeperlocal.desktop.line` |
| Instagram helper（同梱時） | `local.beeperlocal.desktop.instagram` |

製品版では同じTeamの証明書で、PyInstallerに埋め込むPython runtime/native extensionsも署名する。helperから外側のアプリへ順に、Hardened Runtimeとsecure timestampを付ける。新たなentitlement例外は付けない。最終検証でbundle全体・全helper・アーカイブ内のMach-Oライブラリを確認する。`--deep`は検証だけに使う。手書きのdesignated requirementを設定せず、Developer IDの標準要件を使う。

```bash
# 証明書のSHA-1とTeam IDは識別情報。秘密鍵・パスワードをここに書かない。
export BEEPERLOCAL_SIGN_IDENTITY='<security find-identityに出る40桁のSHA-1>'
export BEEPERLOCAL_TEAM_ID='<10文字のTeam ID>'
bash scripts/build-desktop.sh --release
```

次回の正式署名版への更新では、`macos_signing.py verify --mode release --app NEW.app --previous-app PREVIOUS.app`で新旧の署名要件を相互検証する。初めて仮署名版から正式署名版へ移る際は、旧版と署名主体が変わるため項目ごとの再承認が必要な場合がある。固定Identifierだけで仮署名版の再ビルド時の再確認をなくせるわけではない。

この工程は署名まで。Appleへの公証送信を暗黙に行わない。一般配布前には別途公証・staple・Gatekeeper確認も必要。公証はキーチェーンのACLを直す機能ではない。

## 証明書設定（このMacでは完了）

2026-10-01の作業開始時は有効な署名identityが0件だった。ユーザーがXcodeでサインインと証明書設定を行い、Developer ID Application証明書を利用可能になった。同日、0.8.1へ正式署名を適用し、普段のBeeperLocal.appへ配置済み。以下は他の開発Macを設定するときの手順。

1. XcodeのSettings → AccountsでApple Accountを追加し、所属Teamを選ぶ。
2. Manage Certificatesから **Developer ID Application** を作成する。既存の証明書を使う場合は対応する秘密鍵もこのMacに必要。秘密鍵をチャットへ貼り付けたり、公開フォルダへ置いたりしない。
3. 証明書と秘密鍵がKeychainへ登録されたら、署名対象Teamとidentityを指定して上記のrelease buildを実行する。

Xcodeを使わない場合は、Keychain AccessのCertificate AssistantでCSRを作成し、Apple DeveloperのCertificatesでDeveloper ID Applicationを発行、ダウンロードした証明書をKeychainへ追加する。CSRを生成したMacには対応する秘密鍵が残る。利用可能な操作はApple側のアカウント権限に従う。

## 検証と完了条件

- 自動テスト: 更新時の既存項目維持、拒否時の無変更、作成競合、固定エラー、署名の必須条件・Team・helper対象を確認。
- `scripts/probe-native-keychain.py --live`: ランダムな専用serviceの一時項目だけを使用。旧backend作成項目と新backend作成項目について、値の更新前後でpersistent referenceが同一、旧新backend両方で読める、最後に削除されたことを検証する。本番serviceやユーザーの資格情報を読まない。
- Developer ID署名の適用を完了。本体・全helperの4対象、Core内蔵の67 Mach-Oについて同一Team・Apple署名・Hardened Runtime・secure timestampを検証済み。
- `scripts/probe-signed-update.py --live`: 内容とcode hashが異なる2本の専用テストプログラムを同じDeveloper IDと固定Identifierで署名。新旧の署名要件を相互検証し、プロセス内の確認UIを禁止した状態で同じ一時項目の作成・読み出し・更新6操作が成功。削除と削除後のnot foundも確認。本番項目は使わない。これはこのMacでの専用fixture検証であり、別MacでのBeeperLocal製品更新試験の代わりではない。
- 別のMacでの初回導入・連携・再起動・正式署名版間の更新は未実施。ユーザーが後で実施する。

参照: [Apple: コード要件と更新時の同一性](https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements)、[Apple: Keychain項目の更新](https://developer.apple.com/documentation/security/updating-and-deleting-keychain-items)、[Apple: Developer ID証明書](https://developer.apple.com/help/account/certificates/create-developer-id-certificates/)、[PyInstaller: macOS署名](https://pyinstaller.org/en/stable/feature-notes.html#macos-binary-code-signing)。

実測記録: `keychain-signing-20261001-native.json`、`keychain-signing-20261001-update-probe.json`、`keychain-signing-20261001-release-verify.json`、`keychain-signing-20261001-installed.json`。最初の署名検証で要件文字列をファイル名として渡す不備があり、inline指定に修正後に再検証して成功。秘密鍵はKeychain内に保持し、署名証明書の作成・OS承認はユーザー操作で実施。
