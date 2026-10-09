import AppKit
import AuthenticationServices
import Darwin

func privatePipe(_ fd: Int32) -> Bool {
    var value = stat()
    return fstat(fd, &value) == 0 && (value.st_mode & S_IFMT) == S_IFIFO
}

func query(_ url: URL) -> [String: String]? {
    guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
          url.user == nil, url.password == nil, url.port == nil, url.fragment == nil else { return nil }
    var result: [String: String] = [:]
    for item in components.queryItems ?? [] {
        guard result[item.name] == nil, let value = item.value, value.utf8.count <= 4096,
              !value.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }) else { return nil }
        result[item.name] = value
    }
    return result
}

func authorization(_ raw: String, state: String) -> URL? {
    guard raw.utf8.count <= 16384, let url = URL(string: raw), url.scheme == "https", url.host == "slack.com",
          url.path == "/oauth/v2/authorize", let fields = query(url),
          fields["state"] == state, state.count >= 32, state.count <= 256,
          fields["redirect_uri"] == "beeperlocal://oauth/slack", fields["scope"] == "",
          fields["code_challenge_method"] == "S256", fields["code_challenge"]?.count == 43,
          fields["client_secret"] == nil, fields["code_verifier"] == nil else { return nil }
    return url
}

func callback(_ url: URL, state: String) -> [String: Any]? {
    guard url.scheme == "beeperlocal", url.host == "oauth", url.path == "/slack", let fields = query(url),
          fields["state"] == state else { return nil }
    if fields["error"] != nil { return ["ok": false, "error": "cancelled"] }
    guard let code = fields["code"], !code.isEmpty else { return nil }
    return ["ok": true, "state": state, "code": code]
}

final class LoginApp: NSObject, NSApplicationDelegate, NSWindowDelegate, ASWebAuthenticationPresentationContextProviding {
    let url: URL
    let state: String
    var session: ASWebAuthenticationSession?
    var window: NSWindow!
    var finished = false
    init(url: URL, state: String) { self.url = url; self.state = state }
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor { window }
    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 150),
                          styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "BeeperLocal — Slackログイン"
        window.delegate = self
        let text = NSTextField(wrappingLabelWithString: "Slackの認証画面でワークスペースと権限を確認してください。完了するとBeeperLocalに戻ります。")
        text.frame = NSRect(x: 24, y: 70, width: 392, height: 55)
        let button = NSButton(title: "キャンセル", target: self, action: #selector(cancel))
        button.frame = NSRect(x: 300, y: 22, width: 116, height: 32)
        window.contentView?.addSubview(text); window.contentView?.addSubview(button)
        window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        session = ASWebAuthenticationSession(url: url, callbackURLScheme: "beeperlocal") { [weak self] returned, error in
            DispatchQueue.main.async {
                guard let self = self, !self.finished else { return }
                if let returned = returned, let result = callback(returned, state: self.state) { self.finish(result) }
                else if (error as? ASWebAuthenticationSessionError)?.code == .canceledLogin { self.finish(["ok": false, "error": "cancelled"]) }
                else { self.finish(["ok": false, "error": "authentication_failed"]) }
            }
        }
        session?.presentationContextProvider = self
        session?.prefersEphemeralWebBrowserSession = false
        if session?.start() != true { finish(["ok": false, "error": "authentication_failed"]) }
        DispatchQueue.main.asyncAfter(deadline: .now() + 180) { [weak self] in self?.finish(["ok": false, "error": "timeout"]) }
    }
    @objc func cancel() { finish(["ok": false, "error": "cancelled"]) }
    func windowWillClose(_ notification: Notification) { cancel() }
    func finish(_ result: [String: Any]) {
        guard !finished else { return }
        finished = true; session?.cancel()
        if let data = try? JSONSerialization.data(withJSONObject: result) {
            FileHandle.standardOutput.write(data); FileHandle.standardOutput.write(Data([10]))
        }
        NSApp.terminate(nil)
    }
}

if CommandLine.arguments == [CommandLine.arguments[0], "--self-test"] {
    let state = String(repeating: "s", count: 43)
    let valid = URL(string: "beeperlocal://oauth/slack?state=\(state)&code=fixture")!
    let evil = URL(string: "beeperlocal://oauth/slack?state=wrong&code=fixture")!
    guard callback(valid, state: state)?["code"] as? String == "fixture", callback(evil, state: state) == nil,
          callback(URL(string: "https://evil.invalid/?state=\(state)&code=fixture")!, state: state) == nil,
          callback(URL(string: "beeperlocal://oauth/slack?state=\(state)&code=a&code=b")!, state: state) == nil else { exit(1) }
    print("{\"selfTest\":true}"); exit(0)
}
guard CommandLine.arguments.count == 1, privatePipe(STDIN_FILENO), privatePipe(STDOUT_FILENO),
      let line = readLine(), line.utf8.count <= 32768, let data = line.data(using: .utf8),
      let request = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
      request["protocol"] as? Int == 1, let raw = request["url"] as? String, let state = request["state"] as? String,
      let url = authorization(raw, state: state) else { exit(2) }
let app = NSApplication.shared
let delegate = LoginApp(url: url, state: state)
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
