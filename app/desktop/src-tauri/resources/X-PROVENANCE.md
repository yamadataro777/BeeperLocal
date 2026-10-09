# X Chat integration

Transport: mautrix-twitter/twittermeow commit `5282873f8a8941c11e6e0aa66aeb9c0e0d9fab3d`, AGPL-3.0-or-later. The independent validation copy supplies the raw WebSocket hook and zero-retry redirect-response fix. Sources and the private Go bridge are under `x-adapter/`.

Cryptography: `chatxdk==0.5.0`, from chat-xdk commit `017650c0dec4018e282e878c52a5874abb911b34`, MIT. The Python wheel's native extension is bundled in the signed Core runtime.

The adapted supervisor is `beeperlocal/xcrypto/`, copied from the validated independent connector. Registered-key matching, strict message signature verification, signed UUID identity and one-shot encrypted send remain enabled. The desktop worker adds private IPC, exclusive operation locking, common-model persistence acknowledgements, and a native secure PIN prompt. Account data is never packaged.

`beeperlocal-x` and `beeperlocal-x-login` are signed with stable identifiers by the desktop build. Third-party license text is included in `X-THIRD-PARTY-NOTICES.txt`.
