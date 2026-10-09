import AppKit
import WebKit
import Darwin

// This helper owns a fresh, nonpersistent browser session. No external browser
// profile, persistent WebKit store, or existing cookie database is accessed.
func privatePipe(_ fd: Int32) -> Bool {
    var info = stat()
    return fstat(fd, &info) == 0 && (info.st_mode & S_IFMT) == S_IFIFO
}

func safeCookieDomain(_ domain: String) -> Bool {
    let d = domain.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
    return d == "instagram.com" || d.hasSuffix(".instagram.com")
}

func isInstagramNavigation(_ url: URL) -> Bool {
    guard url.scheme == "https", url.user == nil, url.password == nil, (url.port == nil || url.port == 443), let host = url.host?.lowercased() else { return false }
    return host == "instagram.com" || host.hasSuffix(".instagram.com")
}

final class LoginApp: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var browser: WKWebView!
    let status = NSTextField(labelWithString: "https://instagram.com — このウィンドウでInstagramにログインしてください")
    var completed = false
    var timeout: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        browser = WKWebView(frame: .zero, configuration: config)
        browser.navigationDelegate = self
        browser.uiDelegate = self
        browser.allowsBackForwardNavigationGestures = true
        browser.translatesAutoresizingMaskIntoConstraints = false

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 920, height: 780),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "BeeperLocal Instagram — 本人ログイン"
        window.delegate = self
        window.minSize = NSSize(width: 620, height: 560)
        let container = window.contentView!
        let help = NSTextField(wrappingLabelWithString: "通知が届かない場合は、Instagram画面に表示される別の確認方法を選んでください。認証後に右上のボタンを押すと、このログイン情報をBeeperLocalへ渡します。")
        help.translatesAutoresizingMaskIntoConstraints = false
        let done = NSButton(title: "ログイン完了・接続する", target: self, action: #selector(finishLogin))
        let cancel = NSButton(title: "キャンセル", target: self, action: #selector(cancelLogin))
        let refresh = NSButton(title: "再読み込み", target: self, action: #selector(reloadPage))
        let toolbar = NSStackView(views: [status, refresh, cancel, done])
        toolbar.orientation = .horizontal
        toolbar.spacing = 12
        toolbar.translatesAutoresizingMaskIntoConstraints = false
        status.lineBreakMode = .byTruncatingTail
        status.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        container.addSubview(toolbar)
        container.addSubview(browser)
        container.addSubview(help)
        NSLayoutConstraint.activate([
            toolbar.topAnchor.constraint(equalTo: container.topAnchor, constant: 12),
            toolbar.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 16),
            toolbar.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -16),
            help.topAnchor.constraint(equalTo: toolbar.bottomAnchor, constant: 10),
            help.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 16),
            help.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -16),
            browser.topAnchor.constraint(equalTo: help.bottomAnchor, constant: 12),
            browser.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            browser.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            browser.bottomAnchor.constraint(equalTo: container.bottomAnchor)
        ])
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "終了", action: #selector(cancelLogin), keyEquivalent: "q").target = self
        appItem.submenu = appMenu
        menu.addItem(appItem)
        let editItem = NSMenuItem()
        let edit = NSMenu(title: "編集")
        edit.addItem(withTitle: "コピー", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "ペースト", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "すべて選択", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        menu.addItem(editItem)
        NSApp.mainMenu = menu
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        browser.load(URLRequest(url: URL(string: "https://www.instagram.com/accounts/login/")!))
        timeout = Timer.scheduledTimer(withTimeInterval: 900, repeats: false) { [weak self] _ in
            self?.finish(["ok": false, "error": "web_login_timeout"])
        }
    }

    @objc func reloadPage() { browser.reload() }
    @objc func cancelLogin() { finish(["ok": false, "error": "cancelled"]) }
    func windowWillClose(_ notification: Notification) { cancelLogin() }

    func finish(_ payload: [String: Any]) {
        guard !completed else { return }
        completed = true
        timeout?.invalidate()
        browser?.stopLoading()
        if let data = try? JSONSerialization.data(withJSONObject: payload), data.count < 64 * 1024 {
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data([10]))
        }
        NSApp.terminate(nil)
    }

    @objc func finishLogin() {
        guard !completed, let url = browser.url, isInstagramNavigation(url) else { return }
        browser.configuration.websiteDataStore.httpCookieStore.getAllCookies { [weak self] cookies in
            guard let self = self, !self.completed else { return }
            var selected: [String: String] = [:]
            let allowedNames: Set<String> = ["sessionid", "ds_user_id", "csrftoken", "mid", "ig_did", "ig_nrcb", "rur", "datr"]
            let validName = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
            for cookie in cookies where safeCookieDomain(cookie.domain) {
                guard cookie.isSecure, allowedNames.contains(cookie.name),
                      cookie.name.unicodeScalars.allSatisfy({ validName.contains($0) }),
                      !cookie.value.isEmpty, cookie.value.utf8.count <= 8192,
                      !cookie.value.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }),
                      !cookie.value.contains(";"), !cookie.value.contains("\n"), !cookie.value.contains("\r"),
                      cookie.expiresDate.map({ $0 > Date() }) ?? true else { continue }
                selected[cookie.name] = cookie.value
            }
            guard !(selected["ds_user_id"] ?? "").isEmpty, !(selected["sessionid"] ?? "").isEmpty, !(selected["csrftoken"] ?? "").isEmpty else {
                self.status.stringValue = "ログインがまだ完了していません。Instagramの認証を進めてください。"
                return
            }
            // Never print, log, persist, or expose these values outside this pipe.
            
            self.finish(["ok": true, "cookies": selected])
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        // Third-party HTTPS verification frames are rendered by WebKit normally.
        // Main-frame navigation remains on the Instagram login site, visible to the user.
        if navigationAction.targetFrame?.isMainFrame == false && url.scheme == "https" {
            decisionHandler(.allow)
        } else if isInstagramNavigation(url) {
            decisionHandler(.allow)
        } else {
            status.stringValue = "Instagramのユーザー名／メールとパスワードでログインしてください。"
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = navigationAction.request.url, isInstagramNavigation(url) { webView.load(navigationAction.request) }
        return nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        status.stringValue = "https://instagram.com — 認証完了後、右上の「ログイン完了・接続する」を押してください"
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled {
            status.stringValue = "Instagramの画面を読み込めませんでした。再読み込みを試してください。"
        }
    }
}

// Pure boundary checks; no navigation, account, or persistent storage access.
if CommandLine.arguments.count == 2 && CommandLine.arguments[1] == "--self-test" {
    guard safeCookieDomain(".instagram.com"), safeCookieDomain("api.instagram.com"),
          !safeCookieDomain("instagram.com.example.org"), !safeCookieDomain("notinstagram.com"),
          isInstagramNavigation(URL(string: "https://www.instagram.com/accounts/login/")!),
          !isInstagramNavigation(URL(string: "http://instagram.com/messages/")!),
          !isInstagramNavigation(URL(string: "https://user:pass@instagram.com/")!),
          !isInstagramNavigation(URL(string: "https://instagram.com:444/")!),
          !isInstagramNavigation(URL(string: "https://instagram.com.example.org/login")!),
          !WKWebsiteDataStore.nonPersistent().isPersistent else { exit(1) }
    print("native_login_boundary_checks_passed")
    exit(0)
}

// No command-line secrets or arbitrary URL/cookie-import mode exists.
guard CommandLine.arguments.count == 1, privatePipe(STDIN_FILENO), privatePipe(STDOUT_FILENO),
      let line = readLine(), line.utf8.count < 1024,
      let data = line.data(using: .utf8),
      let request = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
      let operation = request["op"] as? String, operation == "web_login",
      request["protocol"] as? Int == 1, request.count == 2 else { exit(2) }

let app = NSApplication.shared
let delegate = LoginApp()
app.setActivationPolicy(.regular)
app.delegate = delegate
app.run()
